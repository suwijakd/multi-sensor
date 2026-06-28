#!/usr/bin/env python3
"""Multi-sensor wearable logger (PC side).

Reads the CSV stream the ESP32-C3 emits over USB serial, writes a timestamped
CSV file, shows a live scrolling dashboard, and lets you drop **event markers**
(e.g. rest / active) that are saved alongside the data for later segmentation.

Examples
--------
    python record.py                       # autodetect port, log + live plot
    python record.py --port COM14          # pick the port explicitly
    python record.py --no-plot             # headless logging only
    python record.py --labels "r=rest,a=active,s=squat"   # custom marker keys
    python record.py --protocol "rest:60,active:60,rest:60,active:60"  # auto-marked
    python record.py --list                # just list serial ports and exit

Event markers
-------------
With the plot window focused, press a label key (default `r`=rest, `a`=active)
to start a labelled state, or <space> for a one-off timestamp mark. In
--no-plot mode, type the key (or a full custom label) and press Enter; type
`s` for status, `q` to quit.

Guided protocol
---------------
--protocol "rest:60,active:60,..." runs a timed schedule, auto-marking each
phase transition (no human reaction lag) and showing a live countdown in the
plot title. --protocol-reps N repeats the whole sequence; --lead-in gives a
"get ready" countdown first. By default recording stops when the protocol ends
(--no-autostop keeps it running). The phases reuse the marker system, so each
becomes a `state` label in the data + events files exactly like a manual press.

Each session writes two files:
  * session_*.csv         — one row per sample, with a trailing `label` column
                            carrying the current state (so you can filter rows
                            by condition directly).
  * session_*_events.csv  — one row per marker: host time, MCU `t_us`, `seq`,
                            type (state/mark) and label. Join to the data on
                            `seq` or `t_us` for exact alignment.
"""
import argparse
import csv
import os
import socket
import sys
import threading
import time
from collections import deque

import serial
import serial.tools.list_ports

# Must match the firmware's "# columns:" line (the leading host_unix_time and
# the trailing label are added by this script).
COLUMNS = [
    "t_us", "seq", "ppg_raw", "gsr_raw",
    "ax", "ay", "az", "gx", "gy", "gz", "mx", "my", "mz",
    "temp_obj_c", "temp_amb_c",
]
N_FIELDS = len(COLUMNS)
ESPRESSIF_VID = 0x303A  # native USB on the ESP32-C3


# --------------------------------------------------------------------------- #
# Port discovery
# --------------------------------------------------------------------------- #
def list_ports():
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("No serial ports found.")
        return
    print("Available serial ports:")
    for p in ports:
        vid = f"{p.vid:04X}" if p.vid is not None else "----"
        print(f"  {p.device:<12} VID:{vid}  {p.description}")


def autodetect_port():
    """Return the device path of a likely ESP32-C3, or None if ambiguous."""
    ports = list(serial.tools.list_ports.comports())
    cands = [p for p in ports if p.vid == ESPRESSIF_VID]
    if not cands:
        cands = [
            p for p in ports
            if (p.description and ("USB JTAG" in p.description or "CDC" in p.description))
            or (p.device and "ttyACM" in p.device)
        ]
    if len(cands) == 1:
        return cands[0].device
    return None


def parse_labels(spec):
    """Parse 'r=rest,a=active' into an ordered {key: label} dict."""
    label_map = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            print(f"[labels] ignoring '{pair}' (expected key=label)")
            continue
        k, v = pair.split("=", 1)
        if k.strip():
            label_map[k.strip()] = v.strip()
    return label_map


def flush_stale_input(ser, seconds=0.5):
    """Discard the stale prefix from a board that's been running unconnected.

    Opening the C3's USB Serial/JTAG port does NOT reset the chip, so a board
    left powered keeps streaming; the firmware drops rows with no listener, but
    its TX buffer still holds an old banner + early samples. Reading those first
    would put junk rows and a huge `seq`/time gap at the start of the recording.
    Drain them so we begin on live data (clean t0, no phantom drops). Returns the
    number of stale data rows discarded; `#` lines seen are printed so the boot
    banner / sensor status stays visible."""
    ser.reset_input_buffer()
    end = time.monotonic() + seconds
    discarded = 0
    while time.monotonic() < end:
        raw = ser.readline()
        if not raw:
            continue
        line = raw.decode("utf-8", errors="ignore").strip()
        if line.startswith("#"):
            print(line)
        elif line:
            discarded += 1
    return discarded


class TcpLineSource:
    """Minimal pyserial-compatible wrapper around a TCP socket so the rest of
    the recorder (which calls .readline()/.reset_input_buffer()/.close()) works
    over Wi-Fi unchanged. readline() returns b'' on timeout (so the reader can
    re-check stop_event) and raises OSError if the device closes the link."""

    def __init__(self, host, port, timeout=1.0):
        self._sock = socket.create_connection((host, port), timeout=5.0)
        self._sock.settimeout(timeout)
        self._buf = bytearray()

    def readline(self):
        while b"\n" not in self._buf:
            try:
                chunk = self._sock.recv(4096)
            except (socket.timeout, TimeoutError):
                return b""              # timeout: let the reader loop re-check stop
            if not chunk:               # peer closed the connection
                raise OSError("connection closed by device")
            self._buf.extend(chunk)
        idx = self._buf.index(b"\n") + 1
        line = bytes(self._buf[:idx])
        del self._buf[:idx]
        return line

    def reset_input_buffer(self):
        self._buf.clear()

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass


def parse_protocol(spec, reps=1):
    """Parse 'rest:60,active:30' into [(label, seconds), ...], repeated `reps`
    times. Returns None (after printing why) on a malformed spec."""
    phases = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        label, sep, secs = item.partition(":")
        label = label.strip()
        if not sep:
            print(f"[protocol] bad phase '{item}' (expected label:seconds)")
            return None
        try:
            secs = float(secs)
        except ValueError:
            print(f"[protocol] bad duration in '{item}'")
            return None
        if not label or secs <= 0:
            print(f"[protocol] bad phase '{item}' (need a label and positive seconds)")
            return None
        phases.append((label, secs))
    if not phases:
        print("[protocol] empty schedule")
        return None
    return phases * max(1, reps)


# --------------------------------------------------------------------------- #
# Background reader: serial -> CSV file + in-memory ring buffers + markers
# --------------------------------------------------------------------------- #
class Recorder:
    def __init__(self, ser, writer, csv_file, events_writer, events_file, window_pts):
        self.ser = ser
        self.writer = writer
        self.csv_file = csv_file
        self.events_writer = events_writer
        self.events_file = events_file
        self.lock = threading.Lock()
        self.buffers = {c: deque(maxlen=window_pts) for c in COLUMNS}
        self.stop_event = threading.Event()
        self.count = 0
        self.drops = 0
        self.marks = 0
        self.last_seq = None
        self.last_t_us = None
        self.t0_us = None
        self.current_label = ""   # persistent state, written into every data row
        self.events = []          # [{t_us, label, kind}] for the live dashboard
        # Guided-protocol display state: set by the protocol thread, read by the UI.
        self.proto_active = False
        self.proto_done = False
        self.proto_idx = 0
        self.proto_n = 0
        self.proto_label = ""
        self.proto_end = 0.0      # time.monotonic() deadline of the current phase
        self.start_time = time.time()

    def run(self):
        while not self.stop_event.is_set():
            try:
                raw = self.ser.readline()
            except (serial.SerialException, OSError) as exc:
                print(f"\n[serial] read error: {exc}")
                break
            if not raw:
                continue  # readline timeout; loop so we can see stop_event
            line = raw.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            if line.startswith("#"):
                print(line)  # device banner / stats / errors
                continue

            parts = line.split(",")
            if len(parts) != N_FIELDS:
                continue  # partial or malformed line

            host_t = time.time()
            # Snapshot the label so a marker landing mid-write can't tear the row.
            self.writer.writerow([f"{host_t:.6f}"] + parts + [self.current_label])
            self.count += 1

            try:
                vals = [float(x) for x in parts]
            except ValueError:
                continue

            seq = int(vals[1])
            if self.last_seq is not None:
                gap = seq - self.last_seq - 1
                if gap > 0:
                    self.drops += gap
            self.last_seq = seq
            self.last_t_us = vals[0]
            if self.t0_us is None:
                self.t0_us = vals[0]

            with self.lock:
                for c, v in zip(COLUMNS, vals):
                    self.buffers[c].append(v)

            if self.count % 500 == 0:
                self.csv_file.flush()

        # Reader has exited (stop requested or serial error): let watchers know.
        self.stop_event.set()

    def mark(self, label, kind="state"):
        """Record an event marker. kind='state' sets the persistent label that
        every subsequent data row carries; kind='mark' is a one-off annotation."""
        host_t = time.time()
        seq, t_us, t0 = self.last_seq, self.last_t_us, self.t0_us
        if kind == "state":
            self.current_label = label
        self.events_writer.writerow([
            f"{host_t:.6f}",
            "" if t_us is None else f"{t_us:.0f}",
            "" if seq is None else seq,
            kind, label,
        ])
        self.events_file.flush()
        self.marks += 1
        with self.lock:
            self.events.append({"t_us": t_us, "label": label, "kind": kind})
        if t_us is not None and t0 is not None:
            when = f"t={ (t_us - t0) / 1e6:7.2f}s seq={seq}"
        else:
            when = "t=  --   (no samples yet)"
        tag = "STATE" if kind == "state" else "mark "
        print(f"  [{tag}] {when}  ->  {label!r}")

    def print_status(self):
        dur = time.time() - self.start_time
        rate = self.count / dur if dur > 0 else 0.0
        print(f"  [status] samples={self.count} ~{rate:.1f}Hz drops={self.drops} "
              f"markers={self.marks} label={self.current_label!r} elapsed={dur:.1f}s")

    def snapshot(self):
        """Thread-safe copy of the ring buffers for the live dashboard."""
        with self.lock:
            return {c: list(self.buffers[c]) for c in COLUMNS}

    def protocol_banner(self):
        """Short live status string for the protocol, or '' if none is running."""
        if not self.proto_active:
            return ""
        if self.proto_done:
            return "PROTOCOL complete"
        remaining = max(0.0, self.proto_end - time.monotonic())
        if self.proto_idx == 0:  # lead-in
            return f"PROTOCOL: {self.proto_label}  {remaining:4.0f}s"
        return (f"PROTOCOL {self.proto_idx}/{self.proto_n}: "
                f"{self.proto_label}  {remaining:4.0f}s left")

    def stop(self):
        self.stop_event.set()


# --------------------------------------------------------------------------- #
# Headless marker console (used with --no-plot)
# --------------------------------------------------------------------------- #
def console_loop(rec, label_map):
    keys = " ".join(f"{k}={v}" for k, v in label_map.items()) or "(none configured)"
    print(f"[markers] type a key + Enter:  {keys}  |  <Enter>=mark  s=status  q=quit")
    while not rec.stop_event.is_set():
        try:
            cmd = input()
        except EOFError:
            break
        low = cmd.strip().lower()
        if low == "q":
            rec.stop()
            break
        if low == "s":
            rec.print_status()
        elif cmd.strip() == "":
            rec.mark("mark", kind="mark")
        elif cmd.strip() in label_map:
            rec.mark(label_map[cmd.strip()], kind="state")
        else:
            rec.mark(cmd.strip(), kind="state")  # full custom label


# --------------------------------------------------------------------------- #
# Guided protocol: run a timed schedule and auto-mark each transition
# --------------------------------------------------------------------------- #
def protocol_loop(rec, schedule, lead_in, autostop):
    total = sum(d for _, d in schedule)
    print(f"[protocol] {len(schedule)} phases, ~{total:.0f}s total"
          + (f" (+{lead_in:.0f}s lead-in)" if lead_in > 0 else "")
          + (", auto-stops at end" if autostop else ""))
    for i, (label, dur) in enumerate(schedule, 1):
        print(f"           {i:>2}. {label:<12}{dur:>5.0f}s")

    rec.proto_active = True
    rec.proto_n = len(schedule)

    def wait_until(deadline):
        """Sleep until the deadline; return True if recording was stopped early."""
        while time.monotonic() < deadline:
            if rec.stop_event.is_set():
                return True
            time.sleep(0.05)
        return False

    if lead_in > 0:
        rec.proto_idx, rec.proto_label = 0, "get ready"
        rec.proto_end = time.monotonic() + lead_in
        if wait_until(rec.proto_end):
            return

    for i, (label, dur) in enumerate(schedule, 1):
        if rec.stop_event.is_set():
            return
        rec.proto_idx, rec.proto_label = i, label
        rec.proto_end = time.monotonic() + dur
        rec.mark(label, kind="state")          # auto-marker at the phase boundary
        if wait_until(rec.proto_end):
            return

    rec.proto_done = True
    rec.mark("protocol_end", kind="mark")
    rec.current_label = ""                      # stop labelling any trailing data
    print("[protocol] complete.")
    if autostop:
        rec.stop()


# --------------------------------------------------------------------------- #
# Live dashboard (matplotlib, imported lazily so --no-plot stays dependency-light)
# --------------------------------------------------------------------------- #
STATE_COLORS = {"rest": "tab:blue", "active": "tab:red"}
_COLOR_CYCLE = ["tab:green", "tab:purple", "tab:orange", "tab:brown", "tab:pink", "tab:olive"]


def run_dashboard(rec, window_seconds, label_map):
    import matplotlib
    import matplotlib.pyplot as plt

    # Inline / non-interactive backends (Spyder's default "Inline", or Agg on a
    # headless box) can't open a live window. Detect that and keep recording
    # rather than silently doing nothing.
    backend = matplotlib.get_backend().lower()
    if "inline" in backend or backend == "agg":
        print(f"[plot] matplotlib backend '{matplotlib.get_backend()}' can't open a live "
              "window — no plot will show.")
        print("       Spyder: Tools > Preferences > IPython console > Graphics >")
        print("       'Graphics backend' = Automatic (or Qt5), then restart the kernel.")
        print("       Or use --no-plot, or run from a plain terminal. Recording anyway...")
        try:
            while not rec.stop_event.is_set():
                time.sleep(1.0)
        except KeyboardInterrupt:
            pass
        return

    # Free our marker keys from matplotlib's default shortcuts (e.g. 'r' is bound
    # to "home/reset view") so pressing them only drops a marker.
    for k in list(label_map.keys()) + [" "]:
        for name, val in matplotlib.rcParams.items():
            if name.startswith("keymap.") and isinstance(val, list) and k in val:
                val.remove(k)

    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(10, 8))
    keyhelp = "  ".join(f"[{k}] {v}" for k, v in label_map.items())
    base_title = f"markers: {keyhelp}  [space] mark   (close window to stop)"
    suptitle = fig.suptitle(base_title, fontsize=10)
    ax_ppg, ax_gsr, ax_acc, ax_tmp = axes

    (l_ppg,) = ax_ppg.plot([], [], lw=0.8)
    ax_ppg.set_ylabel("PPG\n(counts)")
    (l_gsr,) = ax_gsr.plot([], [], lw=0.8, color="tab:green")
    ax_gsr.set_ylabel("GSR\n(counts)")
    (l_ax,) = ax_acc.plot([], [], lw=0.6, label="ax")
    (l_ay,) = ax_acc.plot([], [], lw=0.6, label="ay")
    (l_az,) = ax_acc.plot([], [], lw=0.6, label="az")
    ax_acc.set_ylabel("accel\n(m/s$^2$)")
    ax_acc.legend(loc="upper right", ncol=3, fontsize=8)
    (l_to,) = ax_tmp.plot([], [], lw=1.0, label="object")
    (l_ta,) = ax_tmp.plot([], [], lw=1.0, label="ambient")
    ax_tmp.set_ylabel("temp\n(°C)")
    ax_tmp.set_xlabel("time (s)")
    ax_tmp.legend(loc="upper right", fontsize=8)

    label_colors = dict(STATE_COLORS)

    def color_for(ev):
        if ev["kind"] == "mark":
            return "0.5"
        lbl = ev["label"]
        if lbl not in label_colors:
            label_colors[lbl] = _COLOR_CYCLE[len(label_colors) % len(_COLOR_CYCLE)]
        return label_colors[lbl]

    drawn = {"n": 0}

    def on_key(event):
        if event.key in label_map:
            rec.mark(label_map[event.key], kind="state")
        elif event.key == " ":
            rec.mark("mark", kind="mark")

    fig.canvas.mpl_connect("key_press_event", on_key)

    def update():
        banner = rec.protocol_banner()
        suptitle.set_text((banner + "      |      " if banner else "") + base_title)
        snap = rec.snapshot()
        t_us = snap["t_us"]
        if not t_us:
            return
        t0 = rec.t0_us if rec.t0_us is not None else t_us[0]
        ts = [(x - t0) / 1e6 for x in t_us]

        l_ppg.set_data(ts, snap["ppg_raw"])
        l_gsr.set_data(ts, snap["gsr_raw"])
        l_ax.set_data(ts, snap["ax"])
        l_ay.set_data(ts, snap["ay"])
        l_az.set_data(ts, snap["az"])
        l_to.set_data(ts, snap["temp_obj_c"])
        l_ta.set_data(ts, snap["temp_amb_c"])

        # Draw any markers that arrived since the last frame (they stay put in
        # time and scroll with the x-axis).
        with rec.lock:
            new = rec.events[drawn["n"]:]
            drawn["n"] = len(rec.events)
        for ev in new:
            if ev["t_us"] is None:
                continue
            x = (ev["t_us"] - t0) / 1e6
            color = color_for(ev)
            for ax in axes:
                ax.axvline(x, color=color, ls="--", lw=1.0, alpha=0.7)
            ax_ppg.text(x, 0.98, " " + ev["label"], color=color, fontsize=8,
                        rotation=90, va="top", ha="left",
                        transform=ax_ppg.get_xaxis_transform())

        tmax = ts[-1]
        for ax in axes:
            ax.set_xlim(max(0.0, tmax - window_seconds), max(window_seconds, tmax))
            ax.relim()
            ax.autoscale_view(scalex=False, scaley=True)

    closed = {"flag": False}
    fig.canvas.mpl_connect("close_event", lambda _evt: closed.__setitem__("flag", True))

    plt.tight_layout()
    # Don't rely on plt.show() blocking — under IPython/Spyder it returns
    # immediately. Show non-blocking, then pump the GUI loop ourselves until the
    # window is closed or the serial reader stops.
    plt.show(block=False)
    try:
        while not closed["flag"] and not rec.stop_event.is_set():
            update()
            plt.pause(0.08)  # ~12 FPS: smooth enough, leaves CPU for the serial reader
    except Exception:
        # A closing window legitimately raises here; anything else is a real bug
        # we don't want to swallow silently (that masked an earlier regression).
        if not closed["flag"]:
            import traceback
            print("[plot] dashboard loop error:")
            traceback.print_exc()

    # Close the window promptly (e.g. when the protocol auto-stops the session).
    try:
        plt.close(fig)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="ESP32-C3 multi-sensor serial logger.")
    ap.add_argument("--port", help="serial port (e.g. COM5 or /dev/ttyACM0); autodetected if omitted")
    ap.add_argument("--tcp", help="stream over Wi-Fi instead of USB, e.g. 192.168.4.1:3333")
    ap.add_argument("--baud", type=int, default=115200, help="ignored by native USB CDC, but set anyway")
    ap.add_argument("--outdir", default="recordings", help="directory for CSV files")
    ap.add_argument("--no-plot", action="store_true", help="log only, no live dashboard")
    ap.add_argument("--window", type=float, default=15.0, help="dashboard time window (seconds)")
    ap.add_argument("--rate-hz", type=float, default=100.0, help="expected sample rate (sizes the plot buffer)")
    ap.add_argument("--flush-seconds", type=float, default=0.5,
                    help="drain stale buffered data on connect before recording (0 to disable)")
    ap.add_argument("--labels", default="r=rest,a=active",
                    help="marker keys, e.g. \"r=rest,a=active,s=squat\"")
    ap.add_argument("--protocol",
                    help='guided timed schedule, e.g. "rest:60,active:60,rest:60"; '
                         "auto-marks each transition")
    ap.add_argument("--protocol-reps", type=int, default=1,
                    help="repeat the whole --protocol sequence N times")
    ap.add_argument("--lead-in", type=float, default=3.0,
                    help="'get ready' countdown (s) before the protocol starts")
    ap.add_argument("--autostop", action=argparse.BooleanOptionalAction, default=True,
                    help="stop recording when the protocol finishes (default: on)")
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return 0

    label_map = parse_labels(args.labels)

    schedule = None
    if args.protocol:
        schedule = parse_protocol(args.protocol, args.protocol_reps)
        if schedule is None:
            return 1

    if args.tcp:
        host, _, p = args.tcp.partition(":")
        tcp_port = int(p) if p else 3333
        try:
            ser = TcpLineSource(host, tcp_port)
        except OSError as exc:
            print(f"Failed to connect to {host}:{tcp_port}: {exc}")
            return 1
        src_name = f"{host}:{tcp_port}"
    else:
        port = args.port or autodetect_port()
        if not port:
            print("Could not autodetect the device. Use --list to see ports, then "
                  "pass --port <PORT> (or --tcp HOST:PORT to stream over Wi-Fi).")
            return 1
        try:
            ser = serial.Serial(port, args.baud, timeout=1)
        except serial.SerialException as exc:
            print(f"Failed to open {port}: {exc}")
            return 1
        src_name = port

    # The stale-prefix flush is a USB-CDC quirk; a fresh TCP stream has none.
    if args.flush_seconds > 0 and not args.tcp:
        print(f"[sync] draining stale buffer from {src_name} ...")
        n = flush_stale_input(ser, args.flush_seconds)
        print(f"[sync] discarded {n} stale rows; recording live data.")

    os.makedirs(args.outdir, exist_ok=True)
    base = os.path.join(args.outdir, time.strftime("session_%Y%m%d_%H%M%S"))
    fname, events_fname = base + ".csv", base + "_events.csv"

    csv_file = open(fname, "w", newline="")
    writer = csv.writer(csv_file)
    writer.writerow(["host_unix_time"] + COLUMNS + ["label"])

    events_file = open(events_fname, "w", newline="")
    events_writer = csv.writer(events_file)
    events_writer.writerow(["host_unix_time", "t_us", "seq", "type", "label"])

    window_pts = max(100, int(args.window * args.rate_hz * 1.5))
    rec = Recorder(ser, writer, csv_file, events_writer, events_file, window_pts)

    print(f"Recording from {src_name} -> {fname}")
    print(f"Markers -> {events_fname}")

    reader = threading.Thread(target=rec.run, daemon=True)
    reader.start()

    if schedule:
        threading.Thread(target=protocol_loop,
                         args=(rec, schedule, args.lead_in, args.autostop),
                         daemon=True).start()

    try:
        if args.no_plot:
            console = threading.Thread(target=console_loop, args=(rec, label_map), daemon=True)
            console.start()
            while not rec.stop_event.is_set():
                time.sleep(0.3)
        else:
            keyhelp = "  ".join(f"[{k}]={v}" for k, v in label_map.items())
            print(f"Focus the plot window, then press: {keyhelp}  [space]=mark. "
                  "Close the window to stop.")
            run_dashboard(rec, args.window, label_map)
    except KeyboardInterrupt:
        pass
    finally:
        rec.stop()
        reader.join(timeout=2.0)
        csv_file.flush()
        csv_file.close()
        events_file.flush()
        events_file.close()
        try:
            ser.close()
        except Exception:
            pass
        dur = time.time() - rec.start_time
        rate = rec.count / dur if dur > 0 else 0.0
        print(f"\nStopped. {rec.count} samples in {dur:.1f}s "
              f"(~{rate:.1f} Hz, {rec.drops} dropped, {rec.marks} markers).")
        print(f"Saved:  {fname}")
        print(f"Events: {events_fname}")
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # Hard-exit so a --no-plot console thread still blocked on input() (common
    # when a wireless link drops) can't trigger a CPython shutdown error. All
    # files are already closed in main()'s finally block.
    os._exit(code or 0)

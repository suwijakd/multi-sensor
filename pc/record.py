#!/usr/bin/env python3
"""Multi-sensor wearable logger (PC side).

Reads the CSV stream the ESP32-C3 emits over USB serial, writes a timestamped
CSV file, and (by default) shows a live scrolling dashboard.

Examples
--------
    python record.py                 # autodetect port, log + live plot
    python record.py --port COM5     # pick the port explicitly
    python record.py --no-plot       # headless logging only
    python record.py --list          # just list serial ports and exit
"""
import argparse
import csv
import os
import sys
import threading
import time
from collections import deque

import serial
import serial.tools.list_ports

# Must match the firmware's "# columns:" line (the leading host_unix_time is
# added by this script).
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


# --------------------------------------------------------------------------- #
# Background reader: serial -> CSV file + in-memory ring buffers
# --------------------------------------------------------------------------- #
class Recorder:
    def __init__(self, ser, writer, csv_file, window_pts):
        self.ser = ser
        self.writer = writer
        self.csv_file = csv_file
        self.lock = threading.Lock()
        self.buffers = {c: deque(maxlen=window_pts) for c in COLUMNS}
        self.stop_event = threading.Event()
        self.count = 0
        self.drops = 0
        self.last_seq = None
        self.t0_us = None
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
            self.writer.writerow([f"{host_t:.6f}"] + parts)
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
            if self.t0_us is None:
                self.t0_us = vals[0]

            with self.lock:
                for c, v in zip(COLUMNS, vals):
                    self.buffers[c].append(v)

            if self.count % 500 == 0:
                self.csv_file.flush()

    def snapshot(self):
        with self.lock:
            return {c: list(self.buffers[c]) for c in COLUMNS}

    def stop(self):
        self.stop_event.set()


# --------------------------------------------------------------------------- #
# Live dashboard (matplotlib, imported lazily so --no-plot stays dependency-light)
# --------------------------------------------------------------------------- #
def run_dashboard(rec, window_seconds):
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation

    fig, axes = plt.subplots(4, 1, sharex=True, figsize=(10, 8))
    fig.suptitle("Multi-sensor live  —  close this window to stop recording")
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

    def update(_frame):
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

        tmax = ts[-1]
        for ax in axes:
            ax.set_xlim(max(0.0, tmax - window_seconds), max(window_seconds, tmax))
            ax.relim()
            ax.autoscale_view(scalex=False, scaley=True)

    # Keep a reference to the animation so it isn't garbage-collected.
    _ani = FuncAnimation(fig, update, interval=50, blit=False, cache_frame_data=False)
    plt.tight_layout()
    plt.show()  # blocks until the window is closed


# --------------------------------------------------------------------------- #
def main():
    ap = argparse.ArgumentParser(description="ESP32-C3 multi-sensor serial logger.")
    ap.add_argument("--port", help="serial port (e.g. COM5 or /dev/ttyACM0); autodetected if omitted")
    ap.add_argument("--baud", type=int, default=115200, help="ignored by native USB CDC, but set anyway")
    ap.add_argument("--outdir", default="recordings", help="directory for CSV files")
    ap.add_argument("--no-plot", action="store_true", help="log only, no live dashboard")
    ap.add_argument("--window", type=float, default=15.0, help="dashboard time window (seconds)")
    ap.add_argument("--rate-hz", type=float, default=100.0, help="expected sample rate (sizes the plot buffer)")
    ap.add_argument("--list", action="store_true", help="list serial ports and exit")
    args = ap.parse_args()

    if args.list:
        list_ports()
        return 0

    port = args.port or autodetect_port()
    if not port:
        print("Could not autodetect the device. Use --list to see ports, "
              "then pass --port <PORT>.")
        return 1

    try:
        ser = serial.Serial(port, args.baud, timeout=1)
    except serial.SerialException as exc:
        print(f"Failed to open {port}: {exc}")
        return 1

    os.makedirs(args.outdir, exist_ok=True)
    fname = os.path.join(args.outdir, time.strftime("session_%Y%m%d_%H%M%S.csv"))
    csv_file = open(fname, "w", newline="")
    writer = csv.writer(csv_file)
    writer.writerow(["host_unix_time"] + COLUMNS)

    window_pts = max(100, int(args.window * args.rate_hz * 1.5))
    rec = Recorder(ser, writer, csv_file, window_pts)

    print(f"Recording from {port} -> {fname}")
    print("Press Ctrl+C to stop." if args.no_plot else "Close the plot window to stop.")

    reader = threading.Thread(target=rec.run, daemon=True)
    reader.start()

    try:
        if args.no_plot:
            while reader.is_alive():
                time.sleep(2.0)
                dur = time.time() - rec.start_time
                rate = rec.count / dur if dur > 0 else 0.0
                print(f"  samples={rec.count}  ~{rate:5.1f} Hz  drops={rec.drops}  "
                      f"elapsed={dur:6.1f}s", end="\r", flush=True)
        else:
            run_dashboard(rec, args.window)
    except KeyboardInterrupt:
        pass
    finally:
        rec.stop()
        reader.join(timeout=2.0)
        csv_file.flush()
        csv_file.close()
        try:
            ser.close()
        except Exception:
            pass
        dur = time.time() - rec.start_time
        rate = rec.count / dur if dur > 0 else 0.0
        print(f"\nStopped. {rec.count} samples in {dur:.1f}s "
              f"(~{rate:.1f} Hz, {rec.drops} dropped).")
        print(f"Saved: {fname}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

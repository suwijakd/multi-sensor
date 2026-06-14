# Wearable multi-sensor logger (ESP32-C3)

Firmware + PC tooling to record four health sensors **simultaneously against a
single clock** and stream them to a CSV file with a live dashboard.

| Role | Part | Interface | How it's read |
|------|------|-----------|----------------|
| MCU  | ESP32-C3 Super Mini | — | native USB CDC serial |
| PPG  | DFRobot SEN0203 (Gravity Heart Rate) | **analog** | ADC1, raw waveform |
| IMU  | Adafruit ICM-20948 (9-DoF) | **I²C** | accel + gyro + mag |
| TEMP | MLX90614 / GY-906 | **I²C** | object + ambient °C |
| EDA  | Grove GSR v1.2 | **analog** | ADC1, raw signal |

The firmware samples PPG + GSR + IMU every tick (100 Hz by default) and the
slow MLX90614 on a decimated schedule (2 Hz, last value held), emitting one
timestamped CSV row per tick. Because every row shares the MCU's `micros()`
timebase, the channels are aligned with no cross-sensor drift.

> **Alternative sensor set:** a drop-in variant for a **GY-MAX30102** PPG and a
> **GY-521 / MPU-6050** IMU lives in
> [`arduino/multi_sensor_alt/`](arduino/multi_sensor_alt/). It emits the same
> CSV, so `record.py` works unchanged — just re-wire and flash that sketch. See
> its [README](arduino/multi_sensor_alt/README.md).

---

## 1. Wiring

**Power every sensor from `3V3` and `GND`** on the Super Mini. This keeps both
analog outputs within the ESP32-C3's 0–3.3 V ADC range — powering PPG/GSR from
5 V would clip the ADC at 4095.

| Sensor | Sensor pin | → ESP32-C3 pin | Notes |
|--------|-----------|----------------|-------|
| SEN0203 PPG | signal (`S`) | **GPIO0** | ADC1_CH0 |
| Grove GSR   | signal (`SIG`) | **GPIO1** | ADC1_CH1 |
| ICM-20948   | SDA | **GPIO5** | shared I²C |
| ICM-20948   | SCL | **GPIO6** | shared I²C |
| MLX90614    | SDA | **GPIO5** | shared I²C (addr `0x5A`) |
| MLX90614    | SCL | **GPIO6** | shared I²C |
| all         | VCC | **3V3** | |
| all         | GND | **GND** | common ground |

Both I²C breakouts (Adafruit ICM-20948, GY-906) have onboard pull-ups, so no
extra resistors are needed. The I²C bus runs at **100 kHz** — the MLX90614 is
SMBus and won't tolerate faster.

Pins are defined in [`arduino/multi_sensor/config.h`](arduino/multi_sensor/config.h); change them in one place.

---

## 2. Build & flash the firmware — pick one toolchain

The firmware lives in [`arduino/multi_sensor/`](arduino/multi_sensor/) as a
plain Arduino sketch. All three toolchains below compile that same folder, so
you only need one of them. **Board settings that matter in every case:** board
= *ESP32C3 Dev Module*, and **USB CDC On Boot = Enabled** (this is what makes
`Serial` the USB port on the Super Mini — without it the PC sees nothing).

> **Disk space:** the ESP32 compiler toolchain (~a few hundred MB) is needed by
> every option. The savings come from *how* it's managed: **arduino-cli** keeps
> one shared core under `~/.arduino15` with no per-project build tree, whereas
> PlatformIO stores a per-platform copy under `~/.platformio` (often 1–2 GB)
> plus a `.pio/` folder in each project. If you're tight on space, use Option B.

### Option A — Arduino IDE (GUI)

1. **Add ESP32 support:** *File → Preferences → Additional Boards Manager URLs*,
   add `https://espressif.github.io/arduino-esp32/package_esp32_index.json`,
   then *Tools → Board → Boards Manager* → install **esp32 by Espressif**.
2. **Libraries:** *Tools → Manage Libraries* → install **Adafruit ICM20X** and
   **Adafruit MLX90614 Library** (click *Install all* when it offers to add
   their dependencies, e.g. Adafruit BusIO + Unified Sensor).
3. Open `arduino/multi_sensor/multi_sensor.ino`.
4. *Tools* → Board = **ESP32C3 Dev Module**, **USB CDC On Boot = Enabled**,
   Port = your COM port → click **Upload**.

### Option B — arduino-cli (lightest, scriptable)

```bash
# one-time: install the shared ESP32 core (used by every sketch)
arduino-cli config init
arduino-cli config add board_manager.additional_urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core update-index
arduino-cli core install esp32:esp32

# one-time: libraries (dependencies are pulled in automatically)
arduino-cli lib install "Adafruit ICM20X" "Adafruit MLX90614 Library"

# build (from the project root) — the :CDCOnBoot=cdc flag = "USB CDC On Boot: Enabled"
arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc arduino/multi_sensor

# find the port, then flash
arduino-cli board list
arduino-cli upload -p COM5 --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc arduino/multi_sensor

# optional: watch the raw serial stream
arduino-cli monitor -p COM5 -c baudrate=115200
```

### Option C — PlatformIO

```bash
# from the project root (where platformio.ini lives)
pio run                 # build
pio run -t upload       # build + flash over USB
pio device monitor      # optional: watch the raw serial stream
```

`platformio.ini` sets `src_dir = arduino/multi_sensor` so PlatformIO builds the
same sketch; the USB-CDC build flags are already in there. In VS Code you can
use the ✓ (build) and → (upload) buttons instead.

**To reclaim PlatformIO's space later:** uninstall the PlatformIO VS Code
extension and delete the `~/.platformio` folder
(`C:\Users\<you>\.platformio`), or run `pio system prune -f` to clear caches.

---

**First upload tip (any option):** if the board isn't detected, hold **BOOT**,
tap/replug, then release, and upload again.

On boot the device prints a metadata block, e.g.:

```
# multi-sensor wearable logger
# sample_rate_hz=100 temp_rate_hz=2
# icm20948=ok mlx90614=ok
# units: ppg,gsr=adc_counts(0-4095) accel=m/s^2 gyro=rad/s mag=uT temp=degC t_us=micros
# columns: t_us,seq,ppg_raw,gsr_raw,ax,ay,az,gx,gy,gz,mx,my,mz,temp_obj_c,temp_amb_c
```

If a sensor reads `MISSING`, check wiring/address before recording (see
Troubleshooting).

---

## 3. Record on the PC

```bash
cd pc
python -m venv .venv && .venv\Scripts\activate    # Windows (use source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt

python record.py                              # autodetect port, log + live dashboard
python record.py --port COM14                 # specify the port
python record.py --no-plot                    # headless logging only
python record.py --labels "r=rest,a=active"   # marker keys (this is the default)
python record.py --list                       # list serial ports and exit
```

Close the dashboard window (or press `q`/Ctrl+C in `--no-plot` mode) to stop.
Files are written to `pc/recordings/session_YYYYMMDD_HHMMSS.csv`.

The dashboard shows PPG, GSR, the three accelerometer axes, and object/ambient
temperature. Gyro and magnetometer are still recorded to CSV — they're just not
plotted to keep the view readable.

### Event markers (rest / active, etc.)

Markers let you tag *when* conditions change so you can segment the data later.

- **With the dashboard:** click the plot window to focus it, then press a label
  key — `r` (rest) or `a` (active) by default — to begin that labelled state, or
  **space** for a one-off timestamp mark. A coloured dashed line + label appears
  at that instant on every panel.
- **Headless (`--no-plot`):** type the key and press **Enter** (`r`, `a`, or any
  full custom label like `squat`); **Enter** alone drops a one-off mark, `s`
  prints status, `q` quits.
- **Custom keys:** `--labels "r=rest,a=active,s=squat"`.

A "state" marker is *persistent*: every data row from then on carries that label
in its `label` column, so a typical rest/active protocol is just alternating
`r` and `a` presses at each transition.

### Guided protocol (auto-marked timing)

For a structured experiment, let the software run the schedule and mark the
transitions for you — no human reaction lag, identical timing every trial:

```bash
# 4 phases of 60 s each, auto-marked; live countdown in the plot title
python record.py --protocol "rest:60,active:60,rest:60,active:60"

# repeat a rest/squat block 5 times, headless
python record.py --no-plot --protocol "rest:30,active:30" --protocol-reps 5
```

- Each phase becomes a persistent `state` label, exactly like a manual press, so
  it lands in both the data `label` column and the events file.
- `--lead-in N` gives an N-second "get ready" countdown first (default 3 s).
- Recording **auto-stops when the protocol ends** (`--no-autostop` keeps it
  running); manual markers (`space`, label keys) still work during a protocol.

---

## 4. Output files & schema

Each session writes two files: the per-sample data and a marker log.

**`session_*.csv`** — one row per sample. The PC adds `host_unix_time` (front)
and `label` (back); everything between is straight from the device.

| Column | Unit | Source |
|--------|------|--------|
| `host_unix_time` | seconds (PC clock) | added by `record.py` on receipt |
| `t_us` | microseconds (MCU clock) | authoritative inter-sample timing |
| `seq` | counter | gaps ⇒ dropped samples |
| `ppg_raw`, `gsr_raw` | ADC counts 0–4095 | analog sensors |
| `ax`,`ay`,`az` | m/s² | ICM-20948 accelerometer |
| `gx`,`gy`,`gz` | rad/s | ICM-20948 gyroscope |
| `mx`,`my`,`mz` | µT | ICM-20948 magnetometer |
| `temp_obj_c`, `temp_amb_c` | °C | MLX90614 (held at the 2 Hz cadence) |
| `label` | text | current marker state (empty until first marker) |

**`session_*_events.csv`** — one row per marker.

| Column | Meaning |
|--------|---------|
| `host_unix_time` | PC time the key was pressed |
| `t_us`, `seq` | the most recent sample at press time — join key into the data file |
| `type` | `state` (persistent label) or `mark` (one-off annotation) |
| `label` | e.g. `rest`, `active`, `squat`, `mark` |

Use `t_us` (not `host_unix_time`) for anything timing-sensitive like heart-rate
or HRV analysis — it's jitter-free relative to the host. To segment by
condition you can either filter the data file directly on `label`, or join the
events file on `seq`/`t_us`. PPG/GSR are stored raw so you keep full fidelity;
convert to volts on the PC with `volts = counts / 4095 * 3.3`.

---

## 5. Tuning

Edit [`arduino/multi_sensor/config.h`](arduino/multi_sensor/config.h) and re-flash:

- `SAMPLE_RATE_HZ` — base rate. 100 Hz is comfortable for PPG/HR and IMU motion;
  the 100 kHz I²C bus and ICM magnetometer cap practical rates near ~100–150 Hz.
- `TEMP_RATE_HZ` — MLX90614 read cadence (it changes slowly; 1–2 Hz is plenty).
- `ICM_ADDR` — `0x69` default; set `0x68` if the ICM-20948's ADR pin is tied low.

---

## 6. Troubleshooting

- **`icm20948=MISSING`** — wrong address (try `0x68`), or SDA/SCL swapped.
- **`mlx90614=MISSING` or temp = `nan`/`-273`** — I²C wiring/pull-ups, or the
  bus crept above 100 kHz.
- **PPG/GSR pinned at 4095** — sensor powered from 5 V; move it to 3V3.
- **No data / garbage on the PC** — the firmware must be built with USB CDC on
  boot: *USB CDC On Boot = Enabled* in Arduino IDE, `:CDCOnBoot=cdc` in the
  arduino-cli FQBN, or the `ARDUINO_USB_CDC_ON_BOOT` flag (already in
  `platformio.ini`). Also confirm you opened the right port. The board may reset
  when the port opens — you'll see the `#` banner reprint, which is normal.
- **`txdrop` climbing in `# stats`** (and nonzero `dropped` on the PC) — the PC
  isn't draining the USB port fast enough, so the device dropped whole rows to
  keep the sample clock steady. The data that *did* arrive is uniformly timed.
  Reduce the host load (e.g. run `--no-plot`, or widen `--window` less) or raise
  the device TX buffer (`Serial.setTxBufferSize`).
- **A big `dropped` count *at startup* / first samples look old** — the C3 is
  not reset by opening the port, so a board left powered keeps running and its
  TX buffer holds a stale prefix. `record.py` drains it on connect
  (`--flush-seconds`, default 0.5 s), so the recording starts on live data.
  Note the device's `txdrop` in `# stats` is cumulative since power-on and won't
  reset until you power-cycle the board — the PC summary's `dropped` is the
  session-accurate figure.
- **`overruns` climbing in `# stats`** — the sampling tick itself can't finish
  in time (not a USB issue); lower `SAMPLE_RATE_HZ`.
- **Wrong COM port chosen** — `python record.py --list`, then pass `--port`.

---

## Layout

```
platformio.ini                 PlatformIO config (points src_dir at the sketch)
arduino/
  multi_sensor/
    multi_sensor.ino           sampling loop + CSV-over-USB output
    config.h                   pin map, sample rates, I2C settings
pc/
  record.py                    serial -> CSV logger + live dashboard
  requirements.txt
```

The firmware is one Arduino sketch built by any of Arduino IDE, arduino-cli, or
PlatformIO — there's a single copy of the code, not one per toolchain.

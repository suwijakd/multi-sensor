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

Pins are defined in [`src/config.h`](src/config.h); change them in one place.

---

## 2. Flash the firmware (PlatformIO)

```bash
# from the project root (where platformio.ini lives)
pio run                 # build
pio run -t upload       # build + flash over USB
pio device monitor      # optional: watch the raw serial stream
```

In VS Code with the PlatformIO extension you can use the ✓ (build) and →
(upload) buttons instead.

**First upload tip:** if the board isn't detected, hold **BOOT**, tap/replug,
then release, and upload again. If PlatformIO picks the wrong port, set
`upload_port` / `monitor_port` in `platformio.ini`.

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

python record.py                 # autodetect port, log + live dashboard
python record.py --port COM5     # specify the port
python record.py --no-plot       # headless logging only
python record.py --list          # list serial ports and exit
```

Close the dashboard window (or press Ctrl+C in `--no-plot` mode) to stop. Files
are written to `pc/recordings/session_YYYYMMDD_HHMMSS.csv`.

The dashboard shows PPG, GSR, the three accelerometer axes, and object/ambient
temperature. Gyro and magnetometer are still recorded to CSV — they're just not
plotted to keep the view readable.

---

## 4. CSV schema

The PC adds `host_unix_time`; everything else is straight from the device.

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

Use `t_us` (not `host_unix_time`) for anything timing-sensitive like heart-rate
or HRV analysis — it's jitter-free relative to the host. PPG/GSR are stored raw
so you keep full fidelity; convert to volts on the PC with
`volts = counts / 4095 * 3.3`.

---

## 5. Tuning

Edit [`src/config.h`](src/config.h) and re-flash:

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
- **No data / garbage on the PC** — confirm the firmware built with
  `ARDUINO_USB_CDC_ON_BOOT` (set in `platformio.ini`) and that you opened the
  right port. The board may reset when the port opens — you'll see the `#`
  banner reprint, which is normal.
- **`overruns` climbing in `# stats`** — the tick can't finish in time; lower
  `SAMPLE_RATE_HZ`.
- **Wrong COM port chosen** — `python record.py --list`, then pass `--port`.

---

## Layout

```
platformio.ini        PlatformIO project + library pins
src/
  config.h            pin map, sample rates, I2C settings
  main.cpp            sampling loop + CSV-over-USB output
pc/
  record.py           serial -> CSV logger + live dashboard
  requirements.txt
```

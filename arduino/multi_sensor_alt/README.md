# Alternative sensor set (temporary swap)

A drop-in firmware variant that swaps two sensors, **without touching the
default sketch, `pc/record.py`, or `platformio.ini`**:

| Role | Default (`../multi_sensor/`) | This variant | Interface change |
|------|------------------------------|--------------|------------------|
| PPG  | DFRobot SEN0203 (analog) | **GY-MAX30102** | analog → **I²C** |
| IMU  | ICM-20948 (9-DoF) | **GY-521 / MPU-6050** | 9-DoF → **6-DoF** (no mag) |
| GSR  | Grove GSR v1.2 (analog) | *unchanged* | — |
| TEMP | MLX90614 / GY-906 (I²C) | *unchanged* | — |

**Why no PC changes are needed:** this sketch emits the *identical* 15-column
CSV. The new sensors map into the existing columns — `ppg_raw` carries the
MAX30102 **IR** channel, `ax..gz` carry the MPU-6050 accel/gyro, and `mx,my,mz`
are sent as `nan` (the MPU-6050 has no magnetometer). So `record.py` (markers,
protocol, dashboard) works exactly the same; the PPG panel just plots IR counts
and auto-scales.

## Wiring

PPG is now on I²C, so the old analog PPG pin (GPIO0) is unused. Everything is
powered from **3V3 / GND**.

| Sensor | Pin | → ESP32-C3 | Notes |
|--------|-----|------------|-------|
| MAX30102 | SDA | **GPIO5** | shared I²C, addr `0x57` |
| MAX30102 | SCL | **GPIO6** | |
| MPU-6050 (GY-521) | SDA | **GPIO5** | shared I²C, addr `0x68` |
| MPU-6050 | SCL | **GPIO6** | (`0x69` if AD0 tied high → set `MPU_ADDR`) |
| MLX90614 | SDA | **GPIO5** | shared I²C, addr `0x5A` |
| MLX90614 | SCL | **GPIO6** | |
| Grove GSR | SIG | **GPIO1** | analog, unchanged |
| all | VCC / GND | **3V3 / GND** | |

Three I²C devices now share the bus (`0x57`, `0x68`, `0x5A` — no conflicts).
The bus stays at **100 kHz** for the MLX90614. All breakouts have onboard
pull-ups.

## Libraries

Two new libraries (plus the MLX90614 one you already have):

- **SparkFun MAX3010x Pulse and Proximity Sensor Library** (MAX30102)
- **Adafruit MPU6050** (pulls in Adafruit BusIO + Unified Sensor)
- Adafruit MLX90614 Library

## Build & flash

Pick whichever toolchain you use — just point it at **this folder**
(`arduino/multi_sensor_alt/`). Board = *ESP32C3 Dev Module*, **USB CDC On Boot =
Enabled**, exactly like the default sketch.

```bash
# arduino-cli
arduino-cli lib install "SparkFun MAX3010x Pulse and Proximity Sensor Library" \
                        "Adafruit MPU6050" "Adafruit MLX90614 Library"
arduino-cli compile --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc arduino/multi_sensor_alt
arduino-cli upload  -p COM14 --fqbn esp32:esp32:esp32c3:CDCOnBoot=cdc arduino/multi_sensor_alt
```

- **Arduino IDE:** install the three libraries, open `multi_sensor_alt.ino`, set
  the board options above, Upload.
- **PlatformIO:** the project's `platformio.ini` points at the *default* sketch.
  To build this one without editing it permanently, temporarily set
  `src_dir = arduino/multi_sensor_alt` (and add the two `lib_deps`), or just use
  arduino-cli / Arduino IDE for the swap.

## Swapping back and forth

1. **Re-wire** the sensors for the set you want.
2. **Flash** the matching sketch: `arduino/multi_sensor/` (default) or
   `arduino/multi_sensor_alt/` (this one).
3. Run `python record.py` as usual — **no PC-side changes either way.**

The boot banner tells you which build is running (`# variant=...`) and whether
each sensor came up `ok`, so you can confirm before recording.

## Notes

- `ppg_raw` here is the MAX30102 **IR count** (~0–262143), not the 0–4095 analog
  range — different magnitude, same column. Convert/interpret accordingly.
- The CSV itself doesn't record which variant produced it (same columns); track
  it via the filename or the `# variant=` banner line. The MAX30102 red channel
  and SpO₂ aren't logged (IR is the PPG signal) — ask if you want them added.
- If the PPG signal is weak, raise the LED power in `setup()` (the `0x1F`
  argument) in `multi_sensor_alt.ino`.

# Wearable hardware plan — rev A

Status: **rev A schematic, routed board and case are done (see [README.md](README.md)). Nothing ordered yet.**

Goal: turn the breadboard logger (ESP32-C3 Super Mini + 4 breakout sensors, USB-tethered)
into a battery-powered, wireless wearable on a custom PCB in a 3D-printed case, **without
losing what the current firmware does well**: one MCU timebase, 100 Hz rows, `seq` numbers
for drop detection, and the same CSV schema so `pc/record.py` and `pc/analyze.py` keep working.

---

## 1. Why the current wireless is weak

The repo's firmware only streams over USB, so the "wireless module" is the ESP32-C3 Super
Mini's own radio. That board's 2.4 GHz problems are well documented and come from the
hardware, not from your code:

- **Poor antenna design on early Super Mini revisions.** The ceramic antenna sits next to
  the crystal and LDO with no proper keep-out, so it is badly matched. At full TX power a
  lot of energy is reflected, and the link fails or drops. The common workaround is
  `WiFi.setTxPower(WIFI_POWER_8_5dBm)`, which trades range for stability. It doesn't fix
  every unit.
- **Unit-to-unit variation.** Clones differ, and some fail even at reduced power.
- **On the body it gets worse.** The wrist absorbs and detunes 2.4 GHz. A marginal antenna
  that works on the desk drops packets when worn.

**Takeaway for the PCB:** use a **pre-certified radio module**, which has a matched antenna
and RF already designed and tested. Follow its antenna keep-out exactly, put the antenna at
the board edge facing away from the skin, and keep the battery and ground pours out from
under it. Also, don't rely on the radio alone: log to on-board flash with sequence numbers,
so dropouts can be backfilled (§4.6).

---

## 2. Proposed architecture

```
            USB-C ──ESD──┬─────────────── D+/D- ─────────────┐
                         │ VBUS                              │
                   ┌─────▼─────┐   VSYS    ┌─────────────────▼──────────┐
 LiPo 150–300 mAh ─┤ Charger + ├──────────►│  nRF52840 module           │
 (+NTC, PCM)       │ power path│           │  (BLE 5, USB, QSPI, SAADC) │
                   └─────┬─────┘           │  antenna at board edge     │
                   MAX17048 fuel gauge     └──┬───────┬───────┬───────┬─┘
                         │                    │ I²C   │ QSPI  │ ADC   │ GPIO
                         └────────────────────┤       │       │       │
          MAXM86161 PPG (green/red/IR) ───────┤   NOR flash   │   button, RGB LED,
          BMI270 IMU (6-axis, FIFO) ──────────┤   (ring buf)  │   (opt.) haptic
          TMP117 skin temp (contact) ─────────┤               │
          [opt. BMM350 magnetometer, DNP] ────┘     EDA front end (0.5 V CV + TIA)
                                                     2× dry electrodes (+ snap jack)
```

Data budget: one binary sample is about 32 B (timestamp, seq, PPG green+IR, EDA, accel,
gyro, temp). At 100 Hz that's about 3.2 kB/s, well within BLE (packed 7–8 samples per
notification with Data Length Extension).

---

## 3. Module recommendations (best fit for practical + robust)

| Block | Current part | Recommended | Why | Alternative |
|---|---|---|---|---|
| **MCU / radio** | ESP32-C3 Super Mini | **nRF52840 module: Raytac MDBT50Q-1MV2** (same module as the Adafruit Feather nRF52840) | Certified module with a matched antenna. BLE streaming draws roughly 1–3 mA vs tens of mA on ESP32. Native USB. Mature **Arduino** support (Adafruit nRF52 core + Bluefruit), so the sketch ports with little change. | **Ezurio BL654** (same chip). **nRF54L15** modules (Raytac AN54L15Q, Ezurio BL54L15) are lower power, but Arduino support is only an experimental community core (Jul 2026); not recommended for rev A. **ESP32-C3-MINI-1 / ESP32-S3-MINI-1** if you need Wi-Fi: much less firmware change, but 5–10× the power. |
| **PPG** | SEN0203 (analog) / MAX30102 | **MAXM86161** (or the single-supply **MAXM86161A**): integrated green + red + IR LEDs, photodiode, optical barrier, 19-bit AFE, I²C, ambient-light rejection | Green light is what works at the wrist (MAX30102 only has red/IR). The integrated optics avoid designing your own LED/PD barrier. Tiny LGA, so it needs machine assembly. | ADPD4101 (one chip for PPG + EDA + temp, but 0.4 mm-pitch WLCSP with external LEDs/PDs and complex config). Better as a rev B upgrade. |
| **IMU** | ICM-20948 (9-DoF) | **Bosch BMI270** (accel + gyro, about 0.7 mA full mode, 2 KB FIFO, wrist-gesture/step features) | ICM-20948 has been *not recommended for new designs* since 2022. `analyze.py` only uses the accelerometer. The FIFO lets the MCU batch-read and sleep. | **ST LSM6DSV16X** (4.5 KB FIFO, ~0.65 mA). Optional **BMM350** mag footprint, not populated, if you ever need heading. |
| **Temperature** | MLX90614 (IR, TO-39 can) | **TI TMP117** contact sensor on a thermal pad touching a metal disc in the case floor | ±0.1 °C near body temperature (designed to exceed ASTM E1112), ~3.5 µA, 2×2 mm. The MLX90614 is big, draws ~1.5 mA, needs 100 kHz SMBus (which throttles the whole I²C bus), and measures whatever is in its field of view. | **MAX30208** (±0.1 °C, FIFO). **MLX90632** (3×3 mm SMD IR) if you specifically want non-contact. |
| **EDA / GSR** | Grove GSR v1.2 (LM324, designed for 5 V) | **Discrete constant-voltage front end:** 0.5 V DC across two electrodes, low-leakage zero-drift op-amp as a transimpedance amp (e.g. OPA333/OPA2333 class), into the nRF SAADC (12-bit, 14-bit with oversampling). Two gain ranges selected by GPIO. | Standard method (conductance ∝ current). Clean at 1.8–3.3 V, about 50 µA, and you control the range. | ADPD4101 / TI AFE4500 (integrated EDA). Note: **EDA at the wrist is weak** (fewer sweat glands than palm/fingers), so add a **snap-lead jack** for finger electrodes in experiments. |
| **Storage** | none | **QSPI NOR flash, 8–16 MB** (e.g. Macronix MX25R6435F ultra-low-power, as on the nRF52840 DK) as a ring buffer | 3.2 kB/s means 8 MB ≈ 40 min and 16 MB ≈ 80 min of backfill. BLE dropouts become recoverable instead of lost. | 128 MB SPI NAND (W25N01GV) for ~11 h fully offline sessions, at the cost of more firmware work. |
| **Charger** | none | **TI BQ25180**: I²C, power path (runs from USB with a dead battery), ship mode, NTC input | Designed for small wearables. Ship mode prevents drain on the shelf. | MCP73831 (SOT-23, trivially simple, no power path). Fine if you want to hand-solder. |
| **Fuel gauge** | none | **MAX17048** (ModelGauge, no sense resistor, 4 µA hibernate) | Accurate %-battery over BLE. BQ25180 has no ADC. | Read battery voltage on the SAADC through a switched divider (cheaper, less accurate). |
| **Battery** | USB power | **LiPo 200–300 mAh pouch with protection circuit** (e.g. 402535 / 502030 class) | Estimated draw is ~4–6 mA (BLE ~2, PPG ~1, IMU ~0.7, EDA + flash + rest ~1), so **~1.5–2 days per charge** at 100 Hz continuous. | 150 mAh for a slimmer case (~1 day). |
| **USB / ESD / UI** | Super Mini USB | USB-C 16-pin receptacle (5.1 kΩ CC pull-downs), TPD2E2U06 ESD on D±, 1 button, 1 RGB LED, Tag-Connect TC2030 SWD pads | Charge + USB CDC (same CSV path as today) + DFU. | Optional ERM/LRA haptic for protocol cues. |

*Current figures are datasheet/typical values or estimates. A real power budget is measured on rev A.*

---

## 4. Design rules that make it robust

1. **RF:** module at a board corner, antenna overhanging or at the edge, with the datasheet
   keep-out on **all layers** (no copper, battery, screws or metal case parts nearby). Plastic
   case. Antenna on the side away from the wrist. Reserve a π-network footprint if the module
   allows it.
2. **One supply rail, 1.8 V** for all logic (nRF52840, BMI270, TMP117, W25Q128JW, op-amp),
   from a TPS62840 buck rather than the nRF's REG0, which can only supply 25 mA to external
   loads. That means no level shifters. *(Resolved in the schematic: the MAXM86161 is
   single-supply from VLED with its own internal LDO, and every I²C device's VIH is ≤ 1.4 V.
   Still to measure on rev A: PPG VLED headroom at a low battery, since green LED Vf is up
   to 3.4 V and VLED needs ≥ 3.0 V.)*
3. **I²C at 400 kHz** (no MLX90614 limit any more) with one set of pull-ups on the board.
   Interrupt lines from the PPG (FIFO-ready) and IMU (FIFO watermark) to GPIOs.
4. **Sensor timing:** keep the single MCU timebase. PPG and IMU sample on their own
   oscillators into FIFOs, and firmware timestamps each FIFO burst from one RTC tick, so you
   still get one row per 10 ms.
5. **Optics:** PPG module on the board's skin side, flush with or slightly proud of the case
   floor. Matte black case around a clear window. Firm, even skin contact matters more than
   LED current.
6. **Thermal:** TMP117 on an isolated board peninsula (routed slots) with a thermal pad to a
   stainless disc. Keep it away from the charger and LED.
7. **EDA electrodes:** stainless steel (316L) snaps or screws through the case floor, ~15–20 mm
   apart. Series resistors and ESD protection on both electrode nets.
8. **Manufacturability:** 4-layer, 0.8 mm board. Parts from the JLCPCB/LCSC catalogue where
   possible (with LCSC numbers in the BOM) so assembly is a one-click order. Test points on
   every rail and bus.

---

## 5. Firmware and PC changes (follow the hardware)

- Port `multi_sensor.ino` to the **Adafruit nRF52 Arduino core**. Keep the USB CDC CSV
  output byte-identical, so `record.py` works over USB on day one.
- Add a **BLE GATT stream:** binary packets of N samples, each with `seq` + `t_us`. A
  "resend from seq X" request is served from the flash ring buffer.
- `record.py`: add `--ble` transport (Python `bleak`) that decodes into the **same CSV rows**.
  Analysis is untouched.
- Add a battery %, charge-state and sensor-status characteristic.

---

## 6. Rollout

| Phase | What | Exit criterion |
|---|---|---|
| **0. Validate on dev boards** | Adafruit Feather nRF52840 (same MDBT50Q module) + TMP117, BMI270, MAX17048 breakouts + a MAXM86161 eval/breakout. Port firmware + BLE + `record.py --ble`. | 30 min worn session over BLE with <0.1 % unrecovered drops |
| **1. Rev A PCB (dev-friendly)** | ~35×45 mm, all footprints and options, test points, jumpers on rails, SWD | Each block brought up. Power measured. RF range measured on the wrist |
| **2. Rev B (wearable size)** | Shrink to ~30×35 mm, drop unused options, design the case | Fits the case. Full-day battery |
| **3. Case** | SLA/MJF 3D print, 20/22 mm quick-release strap pins, clear PPG window, metal contacts | Comfortable for 8 h. Stable PPG at rest |

---

## 7. Toolchain

- **KiCad** (schematic + layout). I can write the schematic and netlist and the BOM with LCSC
  numbers, do footprint/symbol work and placement, run ERC/DRC, and generate fab/assembly
  outputs. Final RF-sensitive placement and routing should get your eyes in the KiCad GUI.
- Case in a parametric CAD (FreeCAD / OpenSCAD / Fusion) driven by the board outline.

---

## 8. Decisions (agreed 2026-11-06)

1. **MCU platform:** nRF52840 module (Raytac MDBT50Q-1MV2), BLE only.
2. **Wear location:** wrist, watch-style case, plus a snap jack for finger EDA electrodes.
3. **Assembly:** JLCPCB PCBA, so parts are chosen from the JLC/LCSC catalogue where possible.
4. **Offline logging:** 16 MB QSPI NOR ring buffer for BLE backfill.

Agreed 2026-11-11, replacing the dev-board-first rollout in §6:

5. **Rev A is one wearable-size board** (36 × 42 mm), not a larger dev board first.
6. **Case:** ordered from a print service (SLA or MJF), closed with screws.
7. **Battery:** 250 mAh 502030 cell on solder pads.
8. **Strap:** bars for a 20 mm velcro strap.

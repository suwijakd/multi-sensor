# Hardware — rev A

Plan and part choices: [PLAN.md](PLAN.md). This folder holds the rev A schematic.

| Path | What |
|---|---|
| `tools/gen_schematic.py` | **The design.** Every part, value, footprint and pin→net. Edit this, not the `.kicad_sch` files. |
| `tools/customlib.py` | Pin tables for symbols KiCad doesn't ship (MAXM86161, BMI270, MAX17048, BQ25180, TPS62840) and the VSYS/VBAT power symbols. |
| `tools/kicadgen.py`, `tools/sexpr.py` | Generator: writes a hierarchical KiCad 10 schematic (labels on every pin, no hand-drawn wires). |
| `tools/verify_netlist.py` | Checks KiCad's exported netlist pin-by-pin against the design. |
| `kicad/` | Generated KiCad project: `wearable.kicad_sch` (root) + `power`, `mcu`, `sensors`, `eda` sheets, `wearable.kicad_sym`. |
| `wearable_revA_schematic.pdf`, `wearable_revA_bom.csv` | Generated outputs. |
| `datasheets/` | Put vendor PDFs here (not committed). |

## Regenerate and check

```bash
python hardware/tools/gen_schematic.py
kicad-cli sch erc --severity-all hardware/kicad/wearable.kicad_sch
kicad-cli sch export netlist --format kicadsexpr -o wearable.net hardware/kicad/wearable.kicad_sch
python hardware/tools/verify_netlist.py wearable.net
```

Status on 2026-11-09:
- **ERC:** 0 errors, 0 warnings.
- **Netlist check:** 62 nets and 292 pins, all matching the design.
- **Pinouts:** all 5 custom symbols checked against the vendor datasheets.
- **Footprints:** every part has one. `tools/footprints.py` builds the two project
  footprints in `kicad/wearable.pretty`:
  - BQ25180: TI YBG0008.
  - MAXM86161: Maxim land pattern 90-100106.

## Blocks

- **Power:** USB-C (5.1 kΩ Rd, USBLC6 ESD) → **BQ25180** charger with power path → `VSYS` (3.0–4.5 V)
  → **TPS62840** buck → `+1V8`, which powers *all* logic. **MAX17048** gauge on `VBAT`.
  10 k NTC on TS. JST-PH battery. Test points on every rail.
- **MCU:** **MDBT50Q-1MV2** (nRF52840) in normal-voltage mode (VDD = VDDH = 1.8 V). 32.768 kHz
  crystal. **W25Q128JW** 16 MB 1.8 V QSPI flash. 2.2 kΩ I²C pull-ups, 47 kΩ pull-ups on the
  open-drain interrupts. 10-pin Cortex SWD header. Reset + user buttons. Common-anode RGB LED
  on VSYS through 1.8 V-drivable FETs. DNP expansion header.
  **Pins follow the Adafruit Feather nRF52840 Express** (QSPI P0.17/19–23, SDA P0.12, SCL
  P0.11, button P1.02, LEDs P1.15/P1.10/P0.16), so its UF2 bootloader and Arduino variant
  work for first bring-up.
- **Sensors (one 400 kHz I²C bus):** MAXM86161 0x62, BMI270 0x68, TMP117 0x48,
  BQ25180 0x6A, MAX17048 0x36. No address conflicts. Every device's VIH is ≤ 1.4 V, so
  1.8 V pull-ups work for all of them.
- **PPG:** the MAXM86161 is single-supply. It runs from VLED = VSYS (3.0–5.5 V) and makes
  its own 1.8 V internally (VLDO), so it never loads `+1V8`. LDO_EN is driven by
  `PPG_EN` (P0.13) with a 100 k pull-down, so the module is fully off (≈0.05 µA) until
  firmware enables it. Pins 6–8 are the LED driver nodes: soldered down, connected to
  nothing. The MAXM86161A is a drop-in alternative (same pinout and land pattern).
- **EDA:** a 909k/499k/402k 0.1 % divider gives 0.90 V (TIA reference) and 0.40 V
  (excitation), so the skin sees 0.50 V. LPV812 half A holds electrode E1 at 0.40 V, with
  the loop closed at the electrode so the 10 kΩ protection resistor causes no error. Half B
  is a TIA: 392 kΩ for 0–4.3 µS, plus 43.2 kΩ switched in by TS5A3166 for 0–44 µS. The ADC
  reads EDA_OUT, EDA_VREF and EDA_VEXC_SET, which allows ratiometric calibration. Case
  electrode pads, a JST-SH jack for finger electrodes, and TPD1E05U06 ESD diodes.

### nRF52840 pin map

| Pin | Net | Pin | Net |
|---|---|---|---|
| P0.00/P0.01 | 32 kHz crystal | P0.04 (AIN2) | EDA_OUT |
| P0.11 / P0.12 | I2C_SCL / I2C_SDA | P0.05 (AIN3) | EDA_VREF |
| P0.17,22,23,21 | QSPI IO0–IO3 | P0.30 (AIN6) | EDA_VEXC_SET |
| P0.19 / P0.20 | QSPI SCK / CS | P1.08 | EDA_RANGE |
| P0.18 | nRESET | P0.07 | PPG_INT |
| P1.00 | SWO | P0.26 / P0.27 | IMU_INT1 / INT2 |
| P1.02 | BTN_USER | P0.06 | GAUGE_ALRT |
| P1.15 / P0.16 / P1.10 | LED R / G / B | P0.08 | CHG_INT |
| P0.02,03,28,31,24,25 | expansion header | P1.09 | TEMP_ALERT |
| P0.13 | PPG_EN (MAXM86161 LDO_EN) | | |

## Datasheet verification (2026-11-09)

| Part | Checked | Result / change |
|---|---|---|
| BQ25180 | Table 6-1, §9.2, YBG0008 drawing | Ball map **corrected** (A1 /INT, A2 IN, B1 SCL, B2 SYS, C1 SDA, C2 BAT, D1 TS/MR, D2 GND). TS biased internally (38 µA): NTC only. IN 1–10 µF and SYS 10 µF, both 25 V rated. VIH 1.3 V. Footprint drawn: 0.4 mm pitch, all balls on the perimeter. |
| TPS62840 | Pin Functions (DLC), Table 1, Table 2 | Pin order **corrected** (1 GND, 2 VIN, 3 MODE, 4 EN, 5 VSET, 6 STOP, 7 SW, 8 VOS). VSET to GND = 1.8 V, so R3 = 0 Ω. Inductor changed to the datasheet part DFE201612E-2R2M. |
| MAXM86161 | Pin Description, app circuit, layout guide | Pinout **corrected**. It's single-supply (VLED + internal LDO), with VLDO/VREF 1 µF each and VLED 10 µF. LDO_EN is now on a GPIO. VIH 1.4 V. |
| MAX17048 | Pin table (TDFN), EC table | Pinout confirmed. VIH 1.4 V. KiCad footprint drawn from Maxim 21-0168. |
| BMI270 | Table 22 | Pinout identical to the BMI160. Unused ASDx/ASCx/OCSB/OSDO may be left unconnected (never tied to GND). |
| MDBT50Q-1MV2 | §8 reference circuits | Normal-voltage mode confirmed (VDDH = VDD, DCCH open). 12 pF crystal caps match. Raytac shows 27 Ω on D+/D−, so R25/R26 were added as 0 Ω options. |

## Still open

1. **MAXM86161 optical window position:** the footprint is done, from land pattern
   90-100106: 2 × 7 pads, 0.66 × 0.40 mm, 0.6 mm pitch, 1.9 mm column spacing. Pins
   run 1–7 down the left and 8–14 up the right in top view; pin 1 is at the chamfered
   corner. The case window still needs the LED/photodiode positions from package outline
   **21-100309**, which isn't downloaded yet.
2. **LCSC part numbers** for every BOM line, plus JLCPCB stock. LCSC/JLCPCB block scripted
   lookups, so this needs the browser. The RGB LED, crystal and 0.1 % 0402 resistors may
   need substitutes.
3. **Battery connector polarity** against the actual cell you buy.
4. **JLCPCB capability** for the 0.4 mm-pitch BQ25180 (0.25 mm pads): confirm when quoting.

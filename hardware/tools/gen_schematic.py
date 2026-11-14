#!/usr/bin/env python3
"""Rev A schematic for the wrist-worn multi-sensor wearable.

This file IS the design: parts, values, footprints and every pin's net. Running
it writes the KiCad project under hardware/kicad/ (schematic sheets + project
symbol library). Edit here, re-run, then run ERC:

    python hardware/tools/gen_schematic.py
    kicad-cli sch erc hardware/kicad/wearable.kicad_sch

Pin assignments on the nRF52840 mirror the Adafruit Feather nRF52840 Express
wherever a function exists on both (QSPI flash, I2C, LEDs, button, crystal, USB),
so the Feather's Arduino variant and UF2 bootloader work unmodified at first
bring-up.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import customlib  # noqa: E402
from kicadgen import Design, Libraries, Part, generate  # noqa: E402

OUT = os.path.normpath(os.path.join(HERE, "..", "kicad"))
KICAD_SYMBOLS = os.environ.get(
    "KICAD_SYMBOL_DIR",
    r"C:\Users\nutty\AppData\Local\Programs\KiCad\10.0\share\kicad\symbols")

PWR = {"GND": "power:GND", "+1V8": "power:+1V8", "VBUS": "power:VBUS",
       "VSYS": "wearable:VSYS", "VBAT": "wearable:VBAT"}

d = Design("wearable", power_nets=PWR, power_symbols=None, sheets=[
    ("Power", "power.kicad_sch", "USB-C, charger, fuel gauge, 1.8 V buck"),
    ("MCU", "mcu.kicad_sch", "nRF52840 module, QSPI flash, crystal, SWD, buttons, RGB LED"),
    ("Sensors", "sensors.kicad_sch", "PPG (MAXM86161), IMU (BMI270), skin temperature (TMP117)"),
    ("EDA", "eda.kicad_sch", "Electrodermal activity front end: 0.5 V constant voltage + TIA"),
])

# --- common parts ---------------------------------------------------------- #
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
TP1MM = "TestPoint:TestPoint_Pad_D1.0mm"


def R(ref, value, a, b, sheet, group, **kw):
    return d.add(Part(ref, "Device:R", value, R0402, {"1": a, "2": b}, sheet=sheet, group=group, **kw))


def C(ref, value, a, b, sheet, group, fp=C0402, **kw):
    return d.add(Part(ref, "Device:C", value, fp, {"1": a, "2": b}, sheet=sheet, group=group, **kw))


def TP(ref, net, sheet, group, fp=TP1MM):
    return d.add(Part(ref, "Connector:TestPoint", net, fp, {"1": net}, sheet=sheet, group=group))


def FLAG(ref, net, sheet, group):
    return d.add(Part(ref, "power:PWR_FLAG", "PWR_FLAG", "", {"1": net}, sheet=sheet, group=group))


# =========================================================================== #
# Sheet: Power
# =========================================================================== #
S = "Power"
g = "USB-C input + ESD"
d.add(Part("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C",
           "Connector_USB:USB_C_Receptacle_HRO_TYPE-C-31-M-12",
           {"VBUS": "VBUS", "GND": "GND", "SHIELD": "GND", "CC1": "CC1", "CC2": "CC2",
            "A6": "USB_DP_C", "B6": "USB_DP_C", "A7": "USB_DM_C", "B7": "USB_DM_C"},
           nc=["SBU1", "SBU2"], sheet=S, group=g, mpn="TYPE-C-31-M-12", manufacturer="HRO"))
R("R1", "5.1k", "CC1", "GND", S, g, note="UFP Rd pull-down: 5 V default USB power")
R("R2", "5.1k", "CC2", "GND", S, g)
d.add(Part("U2", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6",
           {"1": "USB_DP_C", "6": "USB_DP_C", "3": "USB_DM_C", "4": "USB_DM_C", "2": "GND", "5": "VBUS"},
           sheet=S, group=g, mpn="USBLC6-2SC6", manufacturer="ST"))
R("R25", "0", "USB_DP_C", "USB_DP", S, g,
  note="Raytac MDBT50Q USB reference fits 27R here; Nordic's nRF52840 reference uses none. Start with 0R")
R("R26", "0", "USB_DM_C", "USB_DM", S, g, note="See R25")
C("C1", "4.7u 25V", "VBUS", "GND", S, g, fp=C0603,
  note="BQ25180 IN: 1-10 uF, 25 V rated. Total VBUS capacitance with C9 stays under the USB 10 uF limit")
FLAG("#FLG01", "VBUS", S, g)
FLAG("#FLG02", "GND", S, g)

g = "Charger (power path) + battery"
d.add(Part("U3", "wearable:BQ25180", "BQ25180", customlib.CUSTOM["BQ25180"]["footprint"],
           {"IN": "VBUS", "SYS": "VSYS", "BAT": "VBAT", "GND": "GND", "SDA": "I2C_SDA",
            "SCL": "I2C_SCL", "~{INT}": "CHG_INT", "TS/~{MR}": "CHG_TS"},
           sheet=S, group=g, mpn="BQ25180YBGR", manufacturer="TI",
           note="I2C 0x6A. Program ICHG for the cell (<=1C). Ship mode exits on USB plug-in or a TS/MR low pulse"))
d.add(Part("TH1", "Device:Thermistor_NTC", "10k B3435", R0402, {"1": "CHG_TS", "2": "GND"},
           sheet=S, group=g, mpn="NCP15XH103F03RC", manufacturer="Murata",
           note="TS is biased internally (38 uA). Place against the battery; Kelvin GND to U3 GND"))
C("C2", "10u 25V", "VSYS", "GND", S, g, fp=C0603, note="SYS: 10 uF nominal, >1 uF after DC-bias derating")
C("C3", "1u", "VBAT", "GND", S, g)
d.add(Part("J2", "Connector_Generic:Conn_01x02", "LiPo pads", "wearable:BatteryPads_1x02_P4.0mm",
           {"1": "VBAT", "2": "GND"}, sheet=S, group=g, dnp=True,
           note="Solder pads, no part fitted: pad 1 = battery +, pad 2 = battery -. Cell must have a "
                "protection circuit (PCM). A reversed battery destroys the charger: check before soldering"))
# VBAT and VSYS are driven by the BQ25180 power-output pins, so they need no PWR_FLAG

g = "Fuel gauge"
d.add(Part("U4", "wearable:MAX17048", "MAX17048", customlib.CUSTOM["MAX17048"]["footprint"],
           {"VDD": "VBAT", "CELL": "VBAT", "CTG": "GND", "QSTRT": "GND", "GND": "GND", "EP": "GND",
            "SDA": "I2C_SDA", "SCL": "I2C_SCL", "~{ALRT}": "GAUGE_ALRT"},
           sheet=S, group=g, mpn="MAX17048G+T10", manufacturer="Analog Devices", note="I2C 0x36"))
C("C4", "100n", "VBAT", "GND", S, g)

g = "1.8 V buck (60 nA Iq)"
d.add(Part("U5", "wearable:TPS62840", "TPS62840", customlib.CUSTOM["TPS62840"]["footprint"],
           {"VIN": "VSYS", "EN": "VSYS", "MODE": "GND", "STOP": "GND", "GND": "GND",
            "SW": "BUCK_SW", "VOS": "+1V8", "VSET": "BUCK_VSET"},
           sheet=S, group=g, mpn="TPS62840DLCR", manufacturer="TI",
           note="MODE=GND: auto power-save. STOP=GND: normal operation. EN/STOP have internal pull-downs"))
R("R3", "0", "BUCK_VSET", "GND", S, g,
  note="VSET=GND selects 1.8 V (datasheet Table 1). Fit an E96 resistor here to change VOUT. <100 pF on VSET")
d.add(Part("L1", "Device:L", "2.2u", "Inductor_SMD:L_Changjiang_FTC201612S", {"1": "BUCK_SW", "2": "+1V8"},
           sheet=S, group=g, mpn="DFE201612E-2R2M=P2", manufacturer="Murata",
           note="Datasheet reference part: 2.2 uH, 116 mOhm, 2016"))
C("C5", "4.7u", "VSYS", "GND", S, g, fp=C0603, note="CIN: 4.7 uF required at VIN")
C("C6", "10u", "+1V8", "GND", S, g, fp=C0603)
FLAG("#FLG05", "+1V8", S, g)

g = "Power test points"
for i, n in enumerate(["VBUS", "VBAT", "VSYS", "+1V8", "GND"], start=1):
    TP("TP%d" % i, n, S, g)

# =========================================================================== #
# Sheet: MCU
# =========================================================================== #
S = "MCU"
g = "nRF52840 module (Raytac MDBT50Q-1MV2)"
mcu_pins = {
    "VDD": "+1V8", "VDDH": "+1V8", "VBUS": "VBUS", "GND": "GND",
    "D+": "USB_DP", "D-": "USB_DM",
    "P0.00": "XL1", "P0.01": "XL2",
    # QSPI flash (Feather nRF52840 Express pins)
    "P0.19": "QSPI_SCK", "P0.20": "QSPI_CS", "P0.17": "QSPI_IO0", "P0.22": "QSPI_IO1",
    "P0.23": "QSPI_IO2", "P0.21": "QSPI_IO3",
    # I2C (Feather SDA/SCL)
    "P0.12": "I2C_SDA", "P0.11": "I2C_SCL",
    # debug / reset
    "SWDIO": "SWDIO", "SWDCLK": "SWDCLK", "P1.00": "SWO", "P0.18": "nRESET",
    # UI (Feather: button P1.02, red LED P1.15, blue LED P1.10, NeoPixel P0.16)
    "P1.02": "BTN_USER", "P1.15": "LED_R", "P0.16": "LED_G", "P1.10": "LED_B",
    # sensor interrupts
    "P0.07": "PPG_INT", "P0.13": "PPG_EN", "P0.26": "IMU_INT1", "P0.27": "IMU_INT2",
    "P0.06": "GAUGE_ALRT", "P0.08": "CHG_INT", "P1.09": "TEMP_ALERT",
    # EDA analog (AIN2, AIN3, AIN6) + range select
    "P0.04": "EDA_OUT", "P0.05": "EDA_VREF", "P0.30": "EDA_VEXC_SET", "P1.08": "EDA_RANGE",
}
d.add(Part("U1", "RF_Module:MDBT50Q-1MV2", "MDBT50Q-1MV2", "RF_Module:Raytac_MDBT50Q", mcu_pins,
           nc=["DCCH", "P0.02", "P0.03", "P0.09", "P0.10", "P0.14", "P0.15", "P0.24", "P0.25", "P0.28",
               "P0.29", "P0.31", "P1.01", "P1.03", "P1.04", "P1.05", "P1.06", "P1.07", "P1.11", "P1.12",
               "P1.13", "P1.14"],
           sheet=S, group=g, mpn="MDBT50Q-1MV2", manufacturer="Raytac",
           note="Normal-voltage mode: VDD=VDDH=1.8 V from the buck, DCCH unused. Antenna keep-out per Raytac datasheet"))
C("C7", "10u", "+1V8", "GND", S, g, fp=C0603)
C("C8", "100n", "+1V8", "GND", S, g)
C("C9", "4.7u", "VBUS", "GND", S, g, fp=C0603, note="nRF52840 VBUS decoupling")

g = "32.768 kHz crystal"
d.add(Part("Y1", "Device:Crystal", "32.768k 9pF", "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm",
           {"1": "XL1", "2": "XL2"}, sheet=S, group=g, mpn="FC-135 32.768kHz 9pF", manufacturer="Epson"))
C("C10", "12p", "XL1", "GND", S, g, note="C0G. C = 2*CL - Cpcb - Cpin")
C("C11", "12p", "XL2", "GND", S, g, note="C0G")

g = "QSPI flash 16 MB (1.8 V)"
d.add(Part("U6", "Memory_Flash:W25Q128JVS", "W25Q128JW", "Package_SON:WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4.3mm",
           {"1": "QSPI_CS", "2": "QSPI_IO1", "3": "QSPI_IO2", "4": "GND", "5": "QSPI_IO0",
            "6": "QSPI_SCK", "7": "QSPI_IO3", "8": "+1V8"},
           sheet=S, group=g, mpn="W25Q128JWPIQ", manufacturer="Winbond",
           note="1.8 V part (JW). Symbol is the pin-identical JV"))
R("R4", "100k", "QSPI_CS", "+1V8", S, g)
C("C12", "100n", "+1V8", "GND", S, g)

g = "I2C + interrupt pull-ups"
R("R5", "2.2k", "I2C_SDA", "+1V8", S, g)
R("R6", "2.2k", "I2C_SCL", "+1V8", S, g)
R("R7", "47k", "PPG_INT", "+1V8", S, g)
R("R8", "47k", "GAUGE_ALRT", "+1V8", S, g)
R("R9", "47k", "CHG_INT", "+1V8", S, g)
R("R10", "47k", "TEMP_ALERT", "+1V8", S, g)

g = "SWD debug + reset/user buttons"
d.add(Part("J3", "Connector_Generic:Conn_01x06", "SWD pads", "wearable:TestPads_1x06_P2.54mm",
           {"1": "GND", "2": "+1V8", "3": "SWDIO", "4": "SWDCLK", "5": "nRESET", "6": "SWO"},
           sheet=S, group=g, dnp=True,
           note="Bare pads on the skin side, 2.54 mm pitch: use a 6-pin pogo clip or solder wires. "
                "Probe must support 1.8 V targets (e.g. J-Link). Not a 3.3 V-only probe"))
d.add(Part("SW1", "Switch:SW_Push", "RESET", "Button_Switch_SMD:SW_SPST_B3U-1000P",
           {"1": "nRESET", "2": "GND"}, sheet=S, group=g, mpn="B3U-1000P", manufacturer="Omron",
           note="Under a pinhole in the lid. Double-tap enters the UF2 bootloader"))
d.add(Part("SW2", "Switch:SW_Push", "USER", "Button_Switch_SMD:SW_SPST_B3U-1000P",
           {"1": "BTN_USER", "2": "GND"}, sheet=S, group=g, mpn="B3U-1000P", manufacturer="Omron",
           note="Pressed by a post on a flexing tab in the lid"))

g = "RGB status LED (anode on VSYS, low-side FETs)"
d.add(Part("D1", "Device:LED_RABG", "RGB CA", "LED_SMD:LED_RGB_1210",
           {"A": "VSYS", "RK": "LED_RK", "GK": "LED_GK", "BK": "LED_BK"}, sheet=S, group=g,
           note="Common anode. Green/blue need more than 1.8 V, so the LED runs from VSYS"))
R("R11", "1.5k", "LED_RK", "LED_RD", S, g)
R("R12", "470", "LED_GK", "LED_GD", S, g)
R("R13", "470", "LED_BK", "LED_BD", S, g)
for i, (col, net) in enumerate((("R", "LED_RD"), ("G", "LED_GD"), ("B", "LED_BD"))):
    d.add(Part("Q%d" % (i + 1), "Transistor_FET:DMG1012T", "DMG1012T", "Package_TO_SOT_SMD:SOT-523",
               {"G": "LED_" + col, "S": "GND", "D": net}, sheet=S, group=g, mpn="DMG1012T-7",
               manufacturer="Diodes Inc", note="Vgs(th) <= 1.0 V, so 1.8 V GPIO drive is enough"))
    R("R%d" % (14 + i), "100k", "LED_" + col, "GND", S, g, note="Keeps the LED off during reset")

# =========================================================================== #
# Sheet: Sensors
# =========================================================================== #
S = "Sensors"
g = "PPG: MAXM86161 (skin side)"
d.add(Part("U7", "wearable:MAXM86161", "MAXM86161", customlib.CUSTOM["MAXM86161"]["footprint"],
           {"VLED": "VSYS", "LDO_EN": "PPG_EN", "SDA": "I2C_SDA", "SCL": "I2C_SCL", "INTB": "PPG_INT",
            "VLDO": "PPG_VLDO", "VREF": "PPG_VREF", "PGND": "GND", "GND_DIG": "GND", "GND_ANA": "GND"},
           nc=["GPIO", "NC_LED1", "NC_LED2", "NC_LED3"], sheet=S, group=g,
           mpn="MAXM86161EFD+", manufacturer="Analog Devices",
           note="I2C 0x62, VIH 1.4 V. Single supply VLED 3.0-5.5 V. Pins 6-8: solder, connect to nothing. "
                "MAXM86161AEFD+ is a drop-in alternative. Bottom side, under the case window"))
R("R24", "100k", "PPG_EN", "GND", S, g, note="Module stays in shutdown (LDO off) until firmware drives PPG_EN high")
C("C13", "1u", "PPG_VLDO", "GND", S, g, note="VLDO bypass, 1 uF to GND_ANA")
C("C24", "1u", "PPG_VREF", "GND", S, g, note="VREF bypass, 1 uF to GND_ANA")
C("C14", "10u", "VSYS", "GND", S, g, fp=C0603, note="VLED bypass: 10 uF to PGND, close to pin 5")
C("C15", "100n", "VSYS", "GND", S, g)

g = "IMU: BMI270 (I2C 0x68)"
d.add(Part("U8", "wearable:BMI270", "BMI270", customlib.CUSTOM["BMI270"]["footprint"],
           {"VDD": "+1V8", "VDDIO": "+1V8", "GND": "GND", "GNDIO": "GND", "CSB": "+1V8", "SDO": "GND",
            "SCx": "I2C_SCL", "SDx": "I2C_SDA", "INT1": "IMU_INT1", "INT2": "IMU_INT2"},
           nc=["ASDx", "ASCx", "OCSB", "OSDO"], sheet=S, group=g, mpn="BMI270", manufacturer="Bosch",
           note="CSB high = I2C. SDO low = address 0x68"))
C("C16", "100n", "+1V8", "GND", S, g, note="VDD")
C("C17", "100n", "+1V8", "GND", S, g, note="VDDIO")

g = "Skin temperature: TMP117 (I2C 0x48)"
d.add(Part("U9", "Sensor_Temperature:TMP117xxDRV", "TMP117", "Package_SON:WSON-6-1EP_2x2mm_P0.65mm_EP1x1.6mm",
           {"SCL": "I2C_SCL", "SDA": "I2C_SDA", "ALERT": "TEMP_ALERT", "ADD0": "GND", "V+": "+1V8", "GND": "GND"},
           sheet=S, group=g, mpn="TMP117AIDRVR", manufacturer="TI",
           note="On an isolated board tab with a thermal pad to a stainless contact disc"))
C("C18", "100n", "+1V8", "GND", S, g)

# =========================================================================== #
# Sheet: EDA
# =========================================================================== #
S = "EDA"
g = "Reference divider: 0.90 V (TIA) and 0.40 V (excitation)"
R("R17", "909k 0.1%", "+1V8", "EDA_VREF", S, g)
R("R18", "499k 0.1%", "EDA_VREF", "EDA_VEXC_SET", S, g)
R("R19", "402k 0.1%", "EDA_VEXC_SET", "GND", S, g, note="Skin sees 0.90 - 0.40 = 0.50 V")
C("C19", "100n", "EDA_VREF", "GND", S, g)
C("C20", "100n", "EDA_VEXC_SET", "GND", S, g)

g = "Excitation buffer + TIA (LPV812, 1.6-5.5 V, 425 nA)"
d.add(Part("U10", "Amplifier_Operational:LPV812DGK", "LPV812", "Package_SO:VSSOP-8_3x3mm_P0.65mm",
           {"3": "EDA_VEXC_SET", "2": "EDA_E1", "1": "EDA_E1_DRV",   # A: buffer, loop closed at the electrode
            "5": "EDA_VREF", "6": "EDA_TIA_IN", "7": "EDA_OUT",       # B: transimpedance amplifier
            "8": "+1V8", "4": "GND"},
           sheet=S, group=g, mpn="LPV812DGKR", manufacturer="TI"))
C("C21", "100n", "+1V8", "GND", S, g)
R("R20", "10k", "EDA_E1_DRV", "EDA_E1", S, g, note="Inside the buffer loop, so no voltage error")
R("R21", "1k", "EDA_E2", "EDA_TIA_IN", S, g, note="Series protection. Firmware corrects the I*R drop")
R("R22", "392k 0.1%", "EDA_TIA_IN", "EDA_OUT", S, g, note="High-sensitivity range: 0-2.2 uA (0-4.3 uS)")
C("C22", "10n C0G", "EDA_TIA_IN", "EDA_OUT", S, g, fp=C0603)
R("R23", "43.2k 0.1%", "EDA_TIA_IN", "EDA_RSW", S, g, note="Switched in parallel: 0-22 uA (0-44 uS)")
d.add(Part("U11", "Analog_Switch:TS5A3166DCKR", "TS5A3166", "Package_TO_SOT_SMD:SOT-353_SC-70-5",
           {"1": "EDA_RSW", "2": "EDA_OUT", "4": "EDA_RANGE", "5": "+1V8", "3": "GND"},
           sheet=S, group=g, mpn="TS5A3166DCKR", manufacturer="TI", note="EDA_RANGE high = low-gain range"))
C("C23", "100n", "+1V8", "GND", S, g)

g = "Electrodes: M2 screws through the case floor + external snap-lead jack"
for _ref, _net in (("E1", "EDA_E1"), ("E2", "EDA_E2")):
    d.add(Part(_ref, "Connector:TestPoint", _net, "MountingHole:MountingHole_2.2mm_M2_Pad", {"1": _net},
               sheet=S, group=g, dnp=True,
               note="Plated M2 hole. A stainless M2 screw from the skin side is the electrode; "
                    "its nut on the top pad makes the contact and clamps the board to the case"))
d.add(Part("J5", "Connector_Generic:Conn_01x02", "EDA ext", "Connector_JST:JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal",
           {"1": "EDA_E1", "2": "EDA_E2"}, sheet=S, group=g, mpn="SM02B-SRSS-TB", manufacturer="JST",
           note="Finger electrodes for stronger EDA than the wrist"))
d.add(Part("D2", "Power_Protection:TPD1E05U06DPY", "TPD1E05U06", "Package_SON:Texas_DPY0002A_0.6x1mm_P0.65mm",
           {"1": "EDA_E1", "2": "GND"}, sheet=S, group=g, mpn="TPD1E05U06DPYR", manufacturer="TI",
           note="Electrode ESD"))
d.add(Part("D3", "Power_Protection:TPD1E05U06DPY", "TPD1E05U06", "Package_SON:Texas_DPY0002A_0.6x1mm_P0.65mm",
           {"1": "EDA_E2", "2": "GND"}, sheet=S, group=g, mpn="TPD1E05U06DPYR", manufacturer="TI",
           note="Electrode ESD. Leakage adds to the measured current: check the datasheet at 0.9 V"))

# --------------------------------------------------------------------------- #
d.note("root", "Rev A - wearable-size board (36 x 42 mm). Generated from hardware/tools/gen_schematic.py.\n"
       "Rails: VBUS (USB 5 V) -> BQ25180 -> VSYS (3.0-4.5 V) -> TPS62840 -> +1V8 (all logic).\n"
       "VLED (PPG) and the RGB LED anode run from VSYS.\n"
       "I2C bus (400 kHz, 1.8 V): BQ25180 0x6A, MAX17048 0x36, MAXM86161 0x62, BMI270 0x68, TMP117 0x48.\n"
       "Custom symbol pinouts checked against vendor datasheets (see tools/customlib.py). "
       + ("UNVERIFIED: " + ", ".join(customlib.unverified()) if customlib.unverified() else "None unverified.")
       + "\nOPEN: LCSC part numbers; MAXM86161 optical-window position (outline 21-100309) for the case.")


def main():
    os.makedirs(OUT, exist_ok=True)
    libpath = os.path.join(OUT, "wearable.kicad_sym")
    customlib.write_library(libpath)
    libs = Libraries(KICAD_SYMBOLS, {"wearable": libpath})
    generate(d, libs, OUT)
    _project_files()
    print("wrote", OUT)


def _project_files():
    with open(os.path.join(OUT, "sym-lib-table"), "w", newline="\n") as f:
        f.write('(sym_lib_table\n\t(version 7)\n\t(lib (name "wearable")(type "KiCad")'
                '(uri "${KIPRJMOD}/wearable.kicad_sym")(options "")(descr "Project symbols"))\n)\n')
    with open(os.path.join(OUT, "fp-lib-table"), "w", newline="\n") as f:
        f.write('(fp_lib_table\n\t(version 7)\n\t(lib (name "wearable")(type "KiCad")'
                '(uri "${KIPRJMOD}/wearable.pretty")(options "")(descr "Project footprints"))\n)\n')
    os.makedirs(os.path.join(OUT, "wearable.pretty"), exist_ok=True)
    pro = os.path.join(OUT, "wearable.kicad_pro")
    if not os.path.exists(pro):
        with open(pro, "w", newline="\n") as f:
            f.write('{\n  "meta": {"filename": "wearable.kicad_pro", "version": 3},\n'
                    '  "schematic": {"legacy_lib_dir": "", "legacy_lib_list": []},\n'
                    '  "sheets": [],\n  "text_variables": {}\n}\n')


if __name__ == "__main__":
    main()

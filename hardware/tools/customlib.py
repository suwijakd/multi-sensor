"""Project symbol library (wearable.kicad_sym) for parts KiCad doesn't ship.

Each IC is described by pin tables; a rectangular symbol is drawn from them.
`verified` records whether the pin numbering has been checked against the
official datasheet. Unverified parts are listed in the design notes and must be
checked before layout.
"""
from sexpr import Q, dumps

PIN_LEN = 2.54
PITCH = 2.54

# side: list of (number, name, electrical_type); None = spacer
CUSTOM = {
    # Datasheet 19-100523 Rev 1, p.14. Single supply: VLED 3.0-5.5 V, internal 1.8 V LDO.
    # Pins 6-8 are the LED cathodes / driver nodes: solder down, connect to nothing.
    # MAXM86161A (19-102034) has the same pinout and the same land pattern (90-100106).
    "MAXM86161": dict(
        ref="U", description="Integrated PPG module: green/red/IR LEDs, photodiode, 19-bit AFE, I2C 0x62 (0xC4/0xC5). 14-pin OLGA 2.9x4.3x1.4 mm",
        datasheet="https://www.analog.com/media/en/technical-documentation/data-sheets/maxm86161.pdf",
        footprint="wearable:MAXM86161_OLGA-14_2.9x4.3mm",
        verified=True,
        left=[("5", "VLED", "power_in"), ("3", "LDO_EN", "input"), None,
              ("1", "SDA", "bidirectional"), ("2", "SCL", "input"), ("14", "INTB", "open_collector"),
              ("13", "GPIO", "bidirectional")],
        right=[("4", "VLDO", "power_out"), ("12", "VREF", "passive"), None,
               ("6", "NC_LED3", "no_connect"), ("7", "NC_LED2", "no_connect"), ("8", "NC_LED1", "no_connect")],
        bottom=[("9", "PGND", "power_in"), ("10", "GND_DIG", "power_in"), ("11", "GND_ANA", "power_in")],
    ),
    # Datasheet BST-BMI270-DS000, Table 22: identical to the BMI160 LGA-14 pinout.
    "BMI270": dict(
        ref="U", description="6-axis IMU (accel + gyro), 2 KB FIFO, I2C/SPI. LGA-14 2.5x3.0 mm, pin-compatible with BMI160",
        datasheet="https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bmi270-ds000.pdf",
        footprint="Package_LGA:Bosch_LGA-14_3x2.5mm_P0.5mm",
        verified=True,
        left=[("13", "SCx", "input"), ("14", "SDx", "bidirectional"), ("1", "SDO", "passive"),
              ("12", "CSB", "input"), None, ("4", "INT1", "bidirectional"), ("9", "INT2", "bidirectional")],
        right=[("2", "ASDx", "bidirectional"), ("3", "ASCx", "output"), ("10", "OCSB", "bidirectional"),
               ("11", "OSDO", "bidirectional")],
        top=[("8", "VDD", "power_in"), ("5", "VDDIO", "power_in")],
        bottom=[("7", "GND", "power_in"), ("6", "GNDIO", "power_in")],
    ),
    # Datasheet p.6 (TDFN column). Footprint drawn from Maxim outline 21-0168 (package T822).
    "MAX17048": dict(
        ref="U", description="1-cell Li-ion fuel gauge, ModelGauge, I2C (0x36). TDFN-8 2x2 mm",
        datasheet="https://www.analog.com/media/en/technical-documentation/data-sheets/MAX17048-MAX17049.pdf",
        footprint="Package_DFN_QFN:TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm",
        verified=True,
        left=[("3", "VDD", "power_in"), ("2", "CELL", "input"), ("1", "CTG", "input"), ("6", "QSTRT", "input")],
        right=[("8", "SDA", "bidirectional"), ("7", "SCL", "input"), ("5", "~{ALRT}", "open_collector")],
        bottom=[("4", "GND", "power_in"), ("9", "EP", "passive")],
    ),
    # Datasheet SLUSE99C Table 6-1. 4 x 2 ball grid (rows A-D, columns 1-2), body 1.6 x 1.1 mm.
    "BQ25180": dict(
        ref="U", description="1-cell linear charger, power path, I2C (0x6A), ship mode. DSBGA-8 (YBG) 1.6x1.1 mm",
        datasheet="https://www.ti.com/lit/ds/symlink/bq25180.pdf",
        footprint="wearable:TI_YBG0008_DSBGA-8_1.6x1.1mm",
        verified=True,
        left=[("A2", "IN", "power_in"), None, ("C1", "SDA", "bidirectional"), ("B1", "SCL", "input"),
              ("A1", "~{INT}", "open_collector")],
        right=[("B2", "SYS", "power_out"), ("C2", "BAT", "power_out"), None, ("D1", "TS/~{MR}", "input")],
        bottom=[("D2", "GND", "power_in")],
    ),
    # Datasheet SLVSEC6D Pin Functions, DLC column. VSET to GND = 1.8 V (Table 1, first row).
    "TPS62840": dict(
        ref="U", description="60 nA Iq 750 mA step-down converter, VSET-programmed output. VSON-8 1.5x2 mm (DLC)",
        datasheet="https://www.ti.com/lit/ds/symlink/tps62840.pdf",
        footprint="Package_SON:VSON-8_1.5x2mm_P0.5mm",
        verified=True,
        left=[("2", "VIN", "power_in"), ("4", "EN", "input"), ("3", "MODE", "input"), ("6", "STOP", "input")],
        right=[("7", "SW", "power_out"), ("8", "VOS", "input"), ("5", "VSET", "passive")],
        bottom=[("1", "GND", "power_in")],
    ),
}

# power symbols the KiCad "power" library lacks
CUSTOM_POWER = ["VSYS", "VBAT"]


def _pin(num, name, etype, x, y, angle):
    return ["pin", etype, "line", ["at", x, y, angle], ["length", PIN_LEN],
            ["name", Q(name), ["effects", ["font", ["size", 1.27, 1.27]]]],
            ["number", Q(num), ["effects", ["font", ["size", 1.27, 1.27]]]]]


def _prop(name, value, x, y, hide=False):
    p = ["property", Q(name), Q(value), ["at", x, y, 0]]
    if hide:
        p.append(["hide", "yes"])
    p.append(["effects", ["font", ["size", 1.27, 1.27]]])
    return p


def ic_symbol(name, d):
    left, right = d.get("left", []), d.get("right", [])
    top, bottom = d.get("top", []), d.get("bottom", [])
    rows = max(len(left), len(right), 1)
    cols = max(len(top), len(bottom), 1)
    longest = max([len(p[1]) for p in left + right + top + bottom if p] + [4])
    half_w = max(cols * PITCH / 2 + 2.54, longest * 1.27 + 2.54)
    half_w = round(half_w / 2.54 + 0.5) * 2.54
    half_h = round((rows * PITCH / 2 + 1.27) / 2.54 + 0.5) * 2.54
    pins = []
    y0 = (rows - 1) * PITCH / 2
    y0 = round(y0 / 2.54) * 2.54 if rows % 2 else round((y0 - 1.27) / 2.54) * 2.54 + 1.27
    for i, p in enumerate(left):
        if p:
            pins.append(_pin(p[0], p[1], p[2], -half_w - PIN_LEN, round(y0 - i * PITCH, 4), 0))
    for i, p in enumerate(right):
        if p:
            pins.append(_pin(p[0], p[1], p[2], half_w + PIN_LEN, round(y0 - i * PITCH, 4), 180))
    for side, ys, ang in ((top, half_h + PIN_LEN, 270), (bottom, -half_h - PIN_LEN, 90)):
        n = len(side)
        x0 = -(n - 1) * PITCH / 2
        x0 = round(x0 / 2.54) * 2.54 if n % 2 else round((x0 + 1.27) / 2.54) * 2.54 - 1.27
        for i, p in enumerate(side):
            if p:
                pins.append(_pin(p[0], p[1], p[2], round(x0 + i * PITCH, 4), ys, ang))
    body = ["symbol", Q(name + "_0_1"),
            ["rectangle", ["start", -half_w, half_h], ["end", half_w, -half_h],
             ["stroke", ["width", 0.254], ["type", "default"]], ["fill", ["type", "background"]]]]
    pinunit = ["symbol", Q(name + "_1_1")] + pins
    return ["symbol", Q(name), ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
            _prop("Reference", d["ref"], 0, half_h + 1.27),
            _prop("Value", name, 0, -half_h - 1.27),
            _prop("Footprint", d["footprint"], 0, 0, hide=True),
            _prop("Datasheet", d["datasheet"], 0, 0, hide=True),
            _prop("Description", d["description"], 0, 0, hide=True),
            body, pinunit, ["embedded_fonts", "no"]]


def power_symbol(name):
    return ["symbol", Q(name), ["power"], ["pin_numbers", ["hide", "yes"]],
            ["pin_names", ["offset", 0], ["hide", "yes"]],
            ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
            _prop("Reference", "#PWR", 0, -3.81, hide=True),
            _prop("Value", name, 0, 3.556),
            _prop("Footprint", "", 0, 0, hide=True),
            _prop("Datasheet", "", 0, 0, hide=True),
            _prop("Description", "Power symbol creates a global label with name \"%s\"" % name, 0, 0, hide=True),
            ["symbol", Q(name + "_0_1"),
             ["polyline", ["pts", ["xy", -0.762, 1.27], ["xy", 0, 2.54]],
              ["stroke", ["width", 0], ["type", "default"]], ["fill", ["type", "none"]]],
             ["polyline", ["pts", ["xy", 0, 0], ["xy", 0, 2.54]],
              ["stroke", ["width", 0], ["type", "default"]], ["fill", ["type", "none"]]],
             ["polyline", ["pts", ["xy", 0, 2.54], ["xy", 0.762, 1.27]],
              ["stroke", ["width", 0], ["type", "default"]], ["fill", ["type", "none"]]]],
            ["symbol", Q(name + "_1_1"),
             ["pin", "power_in", "line", ["at", 0, 0, 90], ["length", 0], ["hide", "yes"],
              ["name", Q(name), ["effects", ["font", ["size", 1.27, 1.27]]]],
              ["number", Q("1"), ["effects", ["font", ["size", 1.27, 1.27]]]]]],
            ["embedded_fonts", "no"]]


def write_library(path):
    lib = ["kicad_symbol_lib", ["version", "20250114"], ["generator", Q("gen_schematic")],
           ["generator_version", Q("10.0")]]
    for name, d in CUSTOM.items():
        lib.append(ic_symbol(name, d))
    for name in CUSTOM_POWER:
        lib.append(power_symbol(name))
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(lib) + "\n")


def unverified():
    return [n for n, d in CUSTOM.items() if not d["verified"]]

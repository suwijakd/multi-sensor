#!/usr/bin/env python3
"""Project footprints (hardware/kicad/wearable.pretty) for parts KiCad doesn't ship.

Each footprint cites the vendor drawing it was built from. Run:

    python hardware/tools/footprints.py
"""
import os
import uuid

from sexpr import Q, dumps

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.normpath(os.path.join(HERE, "..", "kicad", "wearable.pretty"))
NS = uuid.UUID("0b8f8a54-3c9e-4a8e-9d3b-2f9c6a1e7d55")


def _uid(*p):
    return Q(str(uuid.uuid5(NS, "/".join(map(str, p)))))


def _text(kind, value, x, y, layer, size=0.8, hide=False):
    node = ["property", Q(kind), Q(value), ["at", x, y, 0], ["layer", Q(layer)]]
    if hide:
        node.append(["hide", "yes"])
    node += [["uuid", _uid(kind, value, layer)],
             ["effects", ["font", ["size", size, size], ["thickness", round(size * 0.15, 3)]]]]
    return node


def _line(x1, y1, x2, y2, layer, w, name):
    return ["fp_line", ["start", x1, y1], ["end", x2, y2], ["stroke", ["width", w], ["type", "solid"]],
            ["layer", Q(layer)], ["uuid", _uid(name, layer, x1, y1, x2, y2)]]


def _rect(x1, y1, x2, y2, layer, w, name):
    return ["fp_rect", ["start", x1, y1], ["end", x2, y2], ["stroke", ["width", w], ["type", "solid"]],
            ["fill", "no"], ["layer", Q(layer)], ["uuid", _uid(name, layer, "rect")]]


def _circle(cx, cy, r, layer, w, name, fill=False):
    return ["fp_circle", ["center", cx, cy], ["end", cx + r, cy], ["stroke", ["width", w], ["type", "solid"]],
            ["fill", "yes" if fill else "no"], ["layer", Q(layer)], ["uuid", _uid(name, layer, "c", cx, cy)]]


def footprint(name, descr, tags, pads, body_w, body_h, courtyard=0.25, model=None, extra=()):
    hw, hh = body_w / 2, body_h / 2
    fp = ["footprint", Q(name), ["version", 20241229], ["generator", Q("wearable_footprints")],
          ["generator_version", Q("10.0")], ["layer", Q("F.Cu")],
          ["descr", Q(descr)], ["tags", Q(tags)],
          _text("Reference", "REF**", 0, -hh - 1.0, "F.SilkS"),
          _text("Value", name, 0, hh + 1.0, "F.Fab"),
          _text("Datasheet", "", 0, 0, "F.Fab", hide=True),
          _text("Description", descr, 0, 0, "F.Fab", hide=True),
          ["attr", "smd"]]
    # fab outline with pin-1 chamfer
    c = min(0.3, hw / 2)
    pts = [(-hw + c, -hh), (hw, -hh), (hw, hh), (-hw, hh), (-hw, -hh + c), (-hw + c, -hh)]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        fp.append(_line(x1, y1, x2, y2, "F.Fab", 0.1, name))
    # silk: corner marks outside the body, plus pin-1 dot
    s = 0.12
    sx, sy = hw + 0.11, hh + 0.11
    L = min(0.4, hw)
    for (x, y, dx, dy) in ((sx, -sy, -1, 1), (sx, sy, -1, -1), (-sx, sy, 1, -1)):
        fp.append(_line(x, y, x + dx * L, y, "F.SilkS", s, name))
        fp.append(_line(x, y, x, y + dy * L, "F.SilkS", s, name))
    fp.append(_circle(-sx - 0.25, -sy, 0.08, "F.SilkS", 0.16, name, fill=True))
    cx, cy = hw + courtyard, hh + courtyard
    fp.append(_rect(-cx, -cy, cx, cy, "F.CrtYd", 0.05, name))
    fp.append(["fp_text", "user", Q("${REFERENCE}"), ["at", 0, 0, 0], ["layer", Q("F.Fab")],
               ["uuid", _uid(name, "fabref")], ["effects", ["font", ["size", 0.4, 0.4], ["thickness", 0.06]]]])
    fp.extend(pads)
    fp.extend(extra)
    if model:
        fp.append(["model", Q(model), ["offset", ["xyz", 0, 0, 0]], ["scale", ["xyz", 1, 1, 1]],
                   ["rotate", ["xyz", 0, 0, 0]]])
    fp.append(["embedded_fonts", "no"])
    return fp


def smd_pad(num, x, y, w, h, shape="roundrect", mask_margin=None, name=""):
    p = ["pad", Q(num), "smd", shape, ["at", x, y], ["size", w, h],
         ["layers", Q("F.Cu"), Q("F.Mask"), Q("F.Paste")]]
    if shape == "roundrect":
        p.append(["roundrect_rratio", 0.25])
    if mask_margin is not None:
        p.append(["solder_mask_margin", mask_margin])
    p.append(["uuid", _uid(name, "pad", num, x, y)])
    return p


# --------------------------------------------------------------------------- #
def bq25180_ybg():
    """TI YBG0008-C01 (BQ25180 datasheet SLUSE99C p.52-54).

    2 columns x 4 rows, 0.4 mm pitch both ways, ball A1 top-left (top view).
    Body D = 1.57-1.61 mm (rows), E = 1.02-1.06 mm (columns).
    Land: 0.23 mm NSMD copper, mask opening up to +0.05 mm per side. Copper is
    drawn at 0.25 mm, JLCPCB's minimum BGA pad, which is within TI's note 3 tolerance.
    """
    name = "TI_YBG0008_DSBGA-8_1.6x1.1mm"
    pads = []
    for r, row in enumerate("ABCD"):
        for c in (1, 2):
            x = -0.2 if c == 1 else 0.2
            y = -0.6 + 0.4 * r
            pads.append(smd_pad(row + str(c), x, y, 0.25, 0.25, shape="circle", mask_margin=0.04, name=name))
    return footprint(name, "TI DSBGA-8 YBG0008, 2x4 balls, 0.4 mm pitch, body 1.6x1.04 mm (BQ25180). "
                           "https://www.ti.com/lit/ds/symlink/bq25180.pdf#page=52",
                     "DSBGA WCSP YBG BQ25180", pads, 1.06, 1.61)


def maxm86161_olga():
    """Analog Devices / Maxim F142A4 14-pin OLGA (MAXM86161, MAXM86161A).

    Land pattern 90-100106 rev A (IPC-7351A): two columns of 7 pads, 0.66 x 0.40 mm,
    0.6 mm pitch (3.6 mm first-to-last), 1.9 mm between column centres.
    Body 2.9 x 4.3 mm (datasheet ordering table). Numbering from the datasheet pin
    configuration (top view): 1-7 down the left column, 8-14 up the right column,
    so 1 faces 14 and 7 faces 8. This matches the datasheet's Figure 8 layout example.
    """
    name = "MAXM86161_OLGA-14_2.9x4.3mm"
    pads = []
    for n in range(1, 15):
        if n <= 7:
            x, y = -0.95, -1.8 + 0.6 * (n - 1)
        else:
            x, y = 0.95, 1.8 - 0.6 * (n - 8)
        pads.append(smd_pad(str(n), round(x, 3), round(y, 3), 0.66, 0.40, name=name))
    return footprint(name, "Maxim/ADI 14-pin OLGA F142A4, 2.9x4.3x1.4 mm (MAXM86161/MAXM86161A). "
                           "Land pattern 90-100106 rev A",
                     "OLGA MAXM86161 PPG optical", pads, 2.9, 4.3)


def write_all():
    os.makedirs(OUT, exist_ok=True)
    for fn in (bq25180_ybg, maxm86161_olga):
        fp = fn()
        path = os.path.join(OUT, str(fp[1]) + ".kicad_mod")
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(dumps(fp) + "\n")
        print("wrote", path)


if __name__ == "__main__":
    write_all()

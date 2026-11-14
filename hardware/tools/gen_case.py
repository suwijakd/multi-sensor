#!/usr/bin/env python3
"""Generate the two-part case (bottom shell + lid) for the rev A board.

    python hardware/tools/gen_case.py            # writes hardware/case/*.stl and a fit report

Needs `manifold3d`, `trimesh` and `numpy` (and `matplotlib` for the preview images).
The board numbers come from board_geometry.py and the placed parts from
hardware/kicad/board_parts.json (written by `gen_pcb.py dump`), so the case
follows the board when either changes.

Coordinates in this file: functions take BOARD coordinates (X right, Y down, seen
from the top side) and convert to a right-handed model with Z up from the skin.
"""
import json
import os
import sys

import numpy as np
from manifold3d import CrossSection, JoinType, Manifold

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import board_geometry as BG  # noqa: E402

OUT = os.path.normpath(os.path.join(HERE, "..", "case"))
PARTS_JSON = os.path.normpath(os.path.join(HERE, "..", "kicad", "board_parts.json"))

W, H = BG.PCB_W, BG.PCB_H

# ---- case parameters (mm) ----
CL = 0.3                 # gap between the board edge and the wall
WALL = 1.4
R_OUT = 3.0              # outer corner radius
CHAMFER = 0.8            # on the skin-side and top outer edges
FLOOR = BG.PPG_BODY[2] + 0.15          # board seat: the PPG face ends up 0.15 mm inside the floor
Z_PCB0 = FLOOR
Z_PCB1 = FLOOR + BG.PCB_T
Z_SPLIT = 6.2            # where the lid meets the bottom shell (just above the USB shell)
Z_BAT0 = Z_PCB1 + BG.BAT_GAP
Z_BAT1 = Z_BAT0 + BG.BAT_T
Z_CEIL = Z_BAT1 + 0.45   # room for tape and cell swelling
LID_T = 1.2
Z_TOP = Z_CEIL + LID_T

POST = BG.NOTCH - CL                    # corner posts fill the board notches
POST_C = (POST - CL) / 2                # post centre, measured from the board corner
SCREW_PILOT_R = 0.85                    # M2 self-tapping into plastic
SCREW_CLEAR_R = 1.2
SCREW_HEAD_R, SCREW_HEAD_DEPTH = 2.15, 1.8

XO0, YO0, XO1, YO1 = -CL - WALL, -CL - WALL, W + CL + WALL, H + CL + WALL

STRAP_W = 21.0           # slot for a 20 mm strap
STRAP_GAP = 2.8
STRAP_BAR_R = 1.5
STRAP_ARM = 3.0

BAT_X1 = BG.BAT_X0 + BG.BAT_W
BAT_Y1 = BG.BAT_Y0 + BG.BAT_L


# --------------------------------------------------------------------------- #
# geometry helpers (board coordinates in, model out)
# --------------------------------------------------------------------------- #
def box(x0, y0, x1, y1, z0, z1):
    return Manifold.cube([x1 - x0, y1 - y0, z1 - z0]).translate([x0, H - y1, z0])


def cyl(x, y, r, z0, z1, seg=48):
    return Manifold.cylinder(z1 - z0, r, r, seg).translate([x, H - y, z0])


def cyl_x(x0, x1, y, z, r, seg=40):
    return Manifold.cylinder(x1 - x0, r, r, seg).rotate([0, 90, 0]).translate([x0, H - y, z])


def rrect(x0, y0, x1, y1, r, z0, z1):
    cs = CrossSection.square([x1 - x0 - 2 * r, y1 - y0 - 2 * r]).translate((x0 + r, H - y1 + r))
    cs = cs.offset(r, JoinType.Round, 2.0, 48)
    return cs.extrude(z1 - z0).translate([0, 0, z0])


def union(items):
    return Manifold.batch_boolean(list(items), __import__("manifold3d").OpType.Add)


def corners():
    c = POST_C
    return [(c, c), (W - c, c), (c, H - c), (W - c, H - c)]


def corner_boxes(z0, z1):
    return [box(-CL, -CL, POST, POST, z0, z1), box(W - POST, -CL, W + CL, POST, z0, z1),
            box(-CL, H - POST, POST, H + CL, z0, z1), box(W - POST, H - POST, W + CL, H + CL, z0, z1)]


def load_parts():
    with open(PARTS_JSON) as f:
        return json.load(f)


# --------------------------------------------------------------------------- #
def bottom_shell(parts):
    i = CHAMFER
    outer = Manifold.batch_hull([
        rrect(XO0 + i, YO0 + i, XO1 - i, YO1 - i, R_OUT - i, 0, 0.02),
        rrect(XO0, YO0, XO1, YO1, R_OUT, i, Z_SPLIT)])
    cavity = rrect(-CL, -CL, W + CL, H + CL, 0.8, FLOOR, Z_SPLIT + 1)
    shell = outer - cavity
    shell += union(corner_boxes(FLOOR - 0.01, Z_SPLIT))

    # strap bars at both ends
    cx = W / 2
    for end in (-1, 1):
        wall_y = YO0 if end < 0 else YO1
        bar_y = wall_y + end * (STRAP_GAP + STRAP_BAR_R)
        xa, xb = cx - STRAP_W / 2 - STRAP_ARM, cx + STRAP_W / 2 + STRAP_ARM
        shell += cyl_x(xa, xb, bar_y, STRAP_BAR_R, STRAP_BAR_R)
        for x0 in (xa, xb - STRAP_ARM):
            ya, yb = sorted((wall_y - end * 1.2, wall_y - end * 0.6))
            at_wall = box(x0, ya, x0 + STRAP_ARM, yb, 0.9, 5.2)
            ya, yb = sorted((bar_y - end * 0.1, bar_y + end * 0.1))
            at_bar = box(x0, ya, x0 + STRAP_ARM, yb, 0.0, 2 * STRAP_BAR_R)
            shell += Manifold.batch_hull([at_wall, at_bar])

    cuts = []
    # screw pilot holes in the corner posts
    for x, y in corners():
        cuts.append(cyl(x, y, SCREW_PILOT_R, 1.2, Z_SPLIT + 1))
    # PPG window, right through the floor
    w, l, _ = BG.PPG_BODY
    cuts.append(box(BG.PPG_X - w / 2 - 0.15, BG.PPG_Y - l / 2 - 0.15,
                    BG.PPG_X + w / 2 + 0.15, BG.PPG_Y + l / 2 + 0.15, -1, FLOOR + 0.1))
    # TMP117: pocket for the sensor, and a 5 mm recess outside for a metal contact disc
    cuts.append(box(BG.TEMP_X - 1.4, BG.TEMP_Y - 1.4, BG.TEMP_X + 1.4, BG.TEMP_Y + 1.4, 0.5, FLOOR + 0.1))
    cuts.append(cyl(BG.TEMP_X, BG.TEMP_Y, 2.55, -1, 0.5))
    # electrode screws: clearance hole and a shallow seat for the pan head
    for x in (BG.E1_X, BG.E2_X):
        cuts.append(cyl(x, BG.E_Y, 1.15, -1, FLOOR + 1))
        cuts.append(cyl(x, BG.E_Y, 2.2, -1, 0.6))
    # relief under every through-hole lead (USB shell legs)
    for p in parts:
        if p["footprint"].startswith("MountingHole"):
            continue
        for x, y in p["tht"]:
            cuts.append(box(x - 1.0, y - 1.3, x + 1.0, y + 1.3, FLOOR - 0.9, FLOOR + 0.1))
    # USB-C: notch in the right wall, open to the split line so the board drops in
    hw = BG.USB_BODY_W / 2 + 0.35
    cuts.append(box(W + CL - 0.1, BG.USB_Y - hw, XO1 + 1, BG.USB_Y + hw, Z_PCB1 - 0.15, Z_SPLIT + 1))
    # external electrode jack: notch in the left wall
    cuts.append(box(XO0 - 1, BG.JACK_Y - 2.3, -CL + 0.1, BG.JACK_Y + 2.3, Z_PCB1 - 0.05, Z_SPLIT + 1))
    return shell - union(cuts)


def lid():
    i = CHAMFER
    outer = Manifold.batch_hull([
        rrect(XO0, YO0, XO1, YO1, R_OUT, Z_SPLIT, Z_TOP - i),
        rrect(XO0 + i, YO0 + i, XO1 - i, YO1 - i, R_OUT - i, Z_TOP - 0.02, Z_TOP)])
    cavity = rrect(-CL, -CL, W + CL, H + CL, 0.8, Z_SPLIT - 1, Z_CEIL)
    body = outer - cavity
    adds = corner_boxes(Z_SPLIT, Z_CEIL + 0.01)

    # ribs that hold the battery against the lid
    rz0 = Z_BAT0 + 2.0
    g, t = 0.3, 0.8
    adds.append(box(BG.BAT_X0 - g - t, BG.BAT_Y0 + 4, BG.BAT_X0 - g, BG.BAT_Y0 + 26, rz0, Z_CEIL + 0.01))
    adds.append(box(BAT_X1 + g, BG.BAT_Y0 + 2, BAT_X1 + g + t, BG.BAT_Y0 + 18, rz0, Z_CEIL + 0.01))
    adds.append(box(BG.BAT_X0 + 3, BG.BAT_Y0 - g - t, BAT_X1 - 3, BG.BAT_Y0 - g, rz0, Z_CEIL + 0.01))
    for x0 in (BG.BAT_X0 + 1, BAT_X1 - 5):
        adds.append(box(x0, BAT_Y1 + g, x0 + 4, BAT_Y1 + g + t, rz0, Z_CEIL + 0.01))
    # locating lips that drop inside the bottom shell on the two strap ends
    # (0.15 mm clear of the shell wall below the split, joined to the lid wall above it)
    for y0, yw in ((-CL + 0.15, -CL - 0.1), (H + CL - 0.95, H + CL + 0.1)):
        adds.append(box(9, y0, W - 9, y0 + 0.8, Z_SPLIT - 1.0, Z_SPLIT + 0.8))
        ya, yb = sorted((yw, y0 + 0.4))
        adds.append(box(9, ya, W - 9, yb, Z_SPLIT, Z_SPLIT + 0.8))
    # light tube over the status LED
    adds.append(cyl(BG.LED_X, BG.LED_Y, 1.6, Z_PCB1 + 1.6, Z_CEIL + 0.01))
    # post that presses the USER switch, and a bump to find it by touch
    sx, sy = BG.SW_X, BG.SW_USER_Y
    adds.append(cyl(sx, sy, 1.2, Z_PCB1 + BG.H_SW + 0.25, Z_CEIL + 0.01))
    adds.append(cyl(sx, sy, 1.5, Z_TOP - 0.01, Z_TOP + 0.4))
    body += union(adds)

    cuts = []
    for x, y in corners():
        cuts.append(cyl(x, y, SCREW_CLEAR_R, Z_SPLIT - 1, Z_TOP + 1))
        cuts.append(cyl(x, y, SCREW_HEAD_R, Z_TOP - SCREW_HEAD_DEPTH, Z_TOP + 1))
    cuts.append(cyl(BG.LED_X, BG.LED_Y, 0.8, Z_PCB1, Z_TOP + 1))
    # flexing tab around the USER post: a U-shaped slot through the lid plate
    tx0, tx1, ty0, ty1, s = sx - 1.8, sx + 1.8, sy - 1.8, BG.SW_RESET_Y + 2.8, 0.6
    cuts.append(box(tx0 - s, ty0 - s, tx0, ty1, Z_CEIL - 0.1, Z_TOP + 1))
    cuts.append(box(tx1, ty0 - s, tx1 + s, ty1, Z_CEIL - 0.1, Z_TOP + 1))
    cuts.append(box(tx0 - s, ty0 - s, tx1 + s, ty0, Z_CEIL - 0.1, Z_TOP + 1))
    # pinhole for the RESET switch
    cuts.append(cyl(BG.SW_X, BG.SW_RESET_Y, 0.75, Z_CEIL - 0.1, Z_TOP + 1))
    return body - union(cuts)


# --------------------------------------------------------------------------- #
def board_solids(parts):
    """Simplified board, parts and battery, for the interference check and the preview."""
    N = BG.NOTCH
    pts = [(N, 0), (W - N, 0), (W - N, N), (W, N), (W, H - N), (W - N, H - N), (W - N, H),
           (N, H), (N, H - N), (0, H - N), (0, N), (N, N)]
    cs = CrossSection([[(x, H - y) for x, y in reversed(pts)]])
    solids = {"PCB": cs.extrude(BG.PCB_T).translate([0, 0, Z_PCB0])}
    for p in parts:
        if p["height"] < 0.1:
            continue
        if p["side"] == "top":
            z0, z1 = Z_PCB1, Z_PCB1 + p["height"]
        else:
            z0, z1 = Z_PCB0 - p["height"], Z_PCB0
        solids[p["ref"]] = box(p["x0"], p["y0"], p["x1"], p["y1"], z0, z1)
    solids["BATTERY"] = box(BG.BAT_X0, BG.BAT_Y0, BAT_X1, BAT_Y1, Z_BAT0, Z_BAT1)
    return solids


def fit_report(shell, top, solids):
    """Interference volume and smallest gap between every part and each half of the case."""
    rows, bad = [], []
    for name, s in solids.items():
        for cname, c in (("bottom", shell), ("lid", top)):
            overlap = (s ^ c).volume()
            gap = s.min_gap(c, 1.5)
            if overlap > 1e-4:
                bad.append((name, cname, overlap))
            rows.append((name, cname, overlap, gap))
    return rows, bad


def save_stl(m, path):
    import trimesh
    mesh = m.to_mesh()
    tm = trimesh.Trimesh(vertices=np.asarray(mesh.vert_properties)[:, :3], faces=np.asarray(mesh.tri_verts),
                         process=False)
    tm.export(path)
    return tm


def main():
    os.makedirs(OUT, exist_ok=True)
    parts = load_parts()
    shell, top = bottom_shell(parts), lid()
    for name, m in (("bottom_shell", shell), ("lid", top)):
        tm = save_stl(m, os.path.join(OUT, name + ".stl"))
        bb = m.bounding_box()
        print("%-13s %6d triangles  watertight=%s  size %.1f x %.1f x %.1f mm  volume %.2f cm3  pieces=%d" % (
            name, len(tm.faces), tm.is_watertight, bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2],
            m.volume() / 1000, len(m.decompose())))

    solids = board_solids(parts)
    rows, bad = fit_report(shell, top, solids)
    tight = sorted((r for r in rows if r[2] <= 1e-4 and r[3] < 0.25), key=lambda r: r[3])
    print("\nheights (mm above skin): board %.2f-%.2f, split %.2f, battery %.2f-%.2f, ceiling %.2f, top %.2f" % (
        Z_PCB0, Z_PCB1, Z_SPLIT, Z_BAT0, Z_BAT1, Z_CEIL, Z_TOP))
    print("fit check: %d solids against 2 case halves" % len(solids))
    for name, cname, overlap, gap in tight:
        print("  close: %-8s to %-6s gap %.2f mm" % (name, cname, gap))
    for name, cname, overlap in bad:
        print("  INTERFERENCE: %-8s with %-6s  %.3f mm3" % (name, cname, overlap))
    print("fit: %s" % ("OK, no interference" if not bad else "%d interferences" % len(bad)))
    return shell, top, solids, bad


if __name__ == "__main__":
    sys.exit(1 if main()[3] else 0)

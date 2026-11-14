#!/usr/bin/env python3
"""Build the rev A PCB (hardware/kicad/wearable.kicad_pcb) from the schematic netlist.

Run with KiCad's own Python (it provides the `pcbnew` module):

    kicad-cli sch export netlist --format kicadsexpr -o hardware/kicad/wearable.net hardware/kicad/wearable.kicad_sch
    "<KiCad>/bin/python.exe" hardware/tools/gen_pcb.py place     # outline, placement, zones, rules, DSN export
    "<KiCad>/bin/python.exe" hardware/tools/gen_pcb.py route     # Freerouting, import, zone fill
    kicad-cli pcb drc --schematic-parity hardware/kicad/wearable.kicad_pcb

Board coordinates below are in mm from the board's top-left corner, X right and
Y down, as seen from the component (top) side. The same numbers drive the case
in gen_case.py through board_geometry.py.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pcbnew  # noqa: E402

import board_geometry as BG  # noqa: E402
from sexpr import find, find_all, parse  # noqa: E402

KICAD_DIR = os.path.normpath(os.path.join(HERE, "..", "kicad"))
PCB = os.path.join(KICAD_DIR, "wearable.kicad_pcb")
NETLIST = os.path.join(KICAD_DIR, "wearable.net")
DSN = os.path.join(KICAD_DIR, "wearable.dsn")
SES = os.path.join(KICAD_DIR, "wearable.ses")
KICAD_SHARE = os.environ.get("KICAD_SHARE", r"C:\Users\nutty\AppData\Local\Programs\KiCad\10.0\share\kicad")
FREEROUTING = os.environ.get("FREEROUTING_JAR", r"D:\Programs\freerouting\freerouting-1.9.0.jar")
JAVA = os.environ.get("JAVA_EXE", r"C:\Program Files\Android\openjdk\jdk-21.0.8\bin\java.exe")

# True lets the router put signals on In2 as well (the +1V8 pour then fills around them)
INNER2_ROUTABLE = os.environ.get("INNER2_ROUTABLE", "0") == "1"

OX, OY = 100.0, 80.0          # where the board's top-left corner sits on the KiCad page
mm = pcbnew.FromMM


def P(x, y):
    return pcbnew.VECTOR2I(mm(OX + x), mm(OY + y))


# --------------------------------------------------------------------------- #
# Placement: ref -> (x, y, rotation in degrees CCW, side)
# --------------------------------------------------------------------------- #
T, B = "top", "bottom"
PLACE = {
    # --- radio module, antenna at the top edge ---
    "U1": (BG.MODULE_X, BG.MODULE_Y, 0, T),
    # --- status LED, left of the module ---
    "D1": (BG.LED_X, BG.LED_Y, 0, T),
    "R11": (6.2, 9.4, 90, T), "R12": (8.2, 9.4, 90, T), "R13": (10.2, 9.4, 90, T),
    "Q1": (5.9, 11.95, 0, T), "Q2": (8.4, 11.95, 0, T), "Q3": (10.9, 11.95, 0, T),
    "R14": (5.9, 14.1, 0, T), "R15": (8.4, 14.1, 0, T), "R16": (10.9, 14.1, 0, T),
    # --- QSPI flash, right of the module ---
    "U6": (28.0, 8.0, 0, T), "R4": (26.0, 11.95, 0, T), "C12": (28.2, 11.95, 0, T),
    # --- power test points, top right ---
    "TP1": (33.6, 5.5, 0, T), "TP2": (33.6, 7.6, 0, T), "TP3": (33.6, 9.7, 0, T),
    "TP4": (33.6, 11.8, 0, T), "TP5": (33.6, 13.9, 0, T),
    # --- module support: decoupling, crystal, pull-ups ---
    "C10": (11.5, 17.6, 0, T), "Y1": (14.6, 17.6, 0, T), "C11": (17.7, 17.6, 0, T),
    "C8": (20.0, 16.6, 0, T), "C7": (20.25, 18.2, 0, T), "C9": (23.65, 17.0, 0, T),
    "R25": (25.25, 13.3, 0, T), "R26": (25.25, 14.4, 0, T),
    "R5": (15.2, 20.35, 90, T), "R6": (16.4, 20.35, 90, T), "R7": (17.6, 20.35, 90, T),
    "R8": (18.8, 20.35, 90, T), "R9": (20.0, 20.35, 90, T), "R10": (21.2, 20.35, 90, T),
    # --- USB-C on the right edge, ESD and CC resistors ---
    "J1": (BG.USB_X, BG.USB_Y, 90, T),
    "U2": (26.0, 21.0, 90, T), "R1": (25.9, 24.1, 0, T), "R2": (25.9, 25.3, 0, T),
    # --- charger, gauge, buck ---
    "C1": (25.8, 27.6, 0, T), "U3": (24.6, 30.4, 0, T), "C2": (27.2, 30.05, 90, T),
    "C3": (25.9, 32.45, 0, T), "TH1": (22.6, 31.6, 0, T),
    "J2": (BG.BATPAD_X, BG.BATPAD_Y, 0, T),
    "U4": (25.4, 35.25, 0, T), "C4": (25.7, 37.35, 0, T),
    "U5": (20.5, 35.0, 0, T), "C5": (18.3, 34.6, 90, T), "R3": (20.6, 37.2, 0, T),
    "L1": (23.0, 38.0, 0, T), "C6": (20.3, 39.95, 0, T),
    # --- PPG on the skin side, its capacitors directly above ---
    "U7": (BG.PPG_X, BG.PPG_Y, 0, B),
    "C14": (18.0, 23.0, 0, T), "R24": (21.0, 23.0, 0, T), "C15": (14.9, 24.5, 0, T),
    "C13": (15.5, 26.65, 90, T), "C24": (20.5, 26.65, 90, T),
    # --- IMU ---
    "U8": (12.2, 22.0, 0, T), "C16": (9.5, 20.6, 90, T), "C17": (9.5, 22.8, 90, T),
    # --- skin temperature on the skin side ---
    "U9": (BG.TEMP_X, BG.TEMP_Y, 0, B), "C18": (6.8, 39.4, 0, T),
    # --- EDA front end ---
    "R17": (8.9, 25.2, 0, T), "R18": (10.9, 25.2, 0, T), "R19": (12.9, 25.2, 0, T),
    "C19": (9.7, 26.5, 0, T), "C20": (11.7, 26.5, 0, T), "C21": (13.75, 27.55, 0, T),
    "U10": (11.6, 30.0, 0, T),
    "R20": (9.4, 32.6, 0, T), "R21": (11.4, 32.6, 0, T), "R22": (13.4, 32.6, 0, T),
    "R23": (9.6, 34.2, 0, T), "C22": (12.6, 34.2, 0, T),
    "U11": (10.2, 36.4, 0, T), "C23": (13.2, 36.2, 0, T),
    "E1": (BG.E1_X, BG.E_Y, 0, T), "E2": (BG.E2_X, BG.E_Y, 0, T),
    "J5": (BG.JACK_X, BG.JACK_Y, 270, T),
    "D2": (7.4, 22.3, 0, T), "D3": (7.4, 24.1, 0, T),
    # --- buttons on the left edge ---
    "SW2": (BG.SW_X, BG.SW_USER_Y, 90, T), "SW1": (BG.SW_X, BG.SW_RESET_Y, 90, T),
    # --- SWD pads on the skin side ---
    "J3": (BG.SWD_X, BG.SWD_Y, 0, B),
}

POWER_NETS = ["VBUS", "VSYS", "VBAT", "+1V8", "GND", "/Power/BUCK_SW", "/Sensors/PPG_VLDO"]


# --------------------------------------------------------------------------- #
def read_netlist(path):
    root = parse(open(path, encoding="utf-8").read())
    comps = {}
    for c in find_all(find(root, "components"), "comp"):
        ref = str(find(c, "ref")[1])
        sp = find(c, "sheetpath")
        props = {str(find(p, "name")[1]): (str(find(p, "value")[1]) if find(p, "value") else "")
                 for p in find_all(c, "property")}
        fields = {}
        f = find(c, "fields")
        if f:
            for fld in find_all(f, "field"):
                fields[str(find(fld, "name")[1])] = str(fld[-1]) if not isinstance(fld[-1], list) else ""
        comps[ref] = {
            "value": str(find(c, "value")[1]),
            "footprint": str(find(c, "footprint")[1]) if find(c, "footprint") else "",
            "sheet_names": str(find(sp, "names")[1]),
            "sheet_tstamps": str(find(sp, "tstamps")[1]),
            "tstamp": str(find(c, "tstamps")[1]),
            "description": str(find(c, "description")[1]) if find(c, "description") else "",
            "dnp": "dnp" in props,
            "fields": fields,
        }
    pins = {}
    for net in find_all(find(root, "nets"), "net"):
        name = str(find(net, "name")[1])
        for node in find_all(net, "node"):
            pins[(str(find(node, "ref")[1]), str(find(node, "pin")[1]))] = name
    return comps, pins


def footprint_path(fpid):
    lib, name = fpid.split(":", 1)
    if lib == "wearable":
        return os.path.join(KICAD_DIR, "wearable.pretty"), name
    return os.path.join(KICAD_SHARE, "footprints", lib + ".pretty"), name


def add_line(board, a, b, layer=pcbnew.Edge_Cuts, width=0.1):
    s = pcbnew.PCB_SHAPE(board)
    s.SetShape(pcbnew.SHAPE_T_SEGMENT)
    s.SetStart(P(*a))
    s.SetEnd(P(*b))
    s.SetLayer(layer)
    s.SetWidth(mm(width))
    board.Add(s)


def add_text(board, text, x, y, layer, size=0.8, angle=0, mirror=False):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetPosition(P(x, y))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(mm(size), mm(size)))
    t.SetTextThickness(mm(size * 0.15))
    t.SetTextAngleDegrees(angle)
    if mirror:
        t.SetMirrored(True)
    board.Add(t)


def add_zone(board, pts, layers, net=None, name="", keepout=None, clearance=0.2, priority=0, solid=False):
    z = pcbnew.ZONE(board)
    ls = pcbnew.LSET()
    for layer in layers:
        ls.AddLayer(layer)
    z.SetLayerSet(ls)
    ol = z.Outline()
    ol.NewOutline()
    for x, y in pts:
        ol.Append(mm(OX + x), mm(OY + y))
    z.SetZoneName(name)
    if keepout is not None:
        z.SetIsRuleArea(True)
        z.SetDoNotAllowZoneFills(keepout.get("fill", False))
        z.SetDoNotAllowTracks(keepout.get("tracks", False))
        z.SetDoNotAllowVias(keepout.get("vias", False))
        z.SetDoNotAllowPads(keepout.get("pads", False))
        z.SetDoNotAllowFootprints(keepout.get("footprints", False))
    else:
        z.SetNet(net)
        z.SetLocalClearance(mm(clearance))
        z.SetMinThickness(mm(0.2))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL if solid else pcbnew.ZONE_CONNECTION_THERMAL)
        z.SetThermalReliefGap(mm(0.2))
        z.SetThermalReliefSpokeWidth(mm(0.25))
        z.SetAssignedPriority(priority)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_ALWAYS)
    board.Add(z)
    return z


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


# --------------------------------------------------------------------------- #
def place():
    comps, pins = read_netlist(NETLIST)
    for stale in (PCB, PCB.replace(".kicad_pcb", ".kicad_prl")):
        if os.path.exists(stale) and stale.endswith(".kicad_pcb"):
            os.remove(stale)
    board = pcbnew.NewBoard(PCB)
    board.SetCopperLayerCount(4)
    board.SetLayerType(pcbnew.In1_Cu, pcbnew.LT_POWER)
    board.SetLayerType(pcbnew.In2_Cu, pcbnew.LT_SIGNAL if INNER2_ROUTABLE else pcbnew.LT_POWER)

    bds = board.GetDesignSettings()
    bds.SetBoardThickness(mm(BG.PCB_T))
    bds.m_MinClearance = mm(0.1)
    bds.m_TrackMinWidth = mm(0.127)
    bds.m_ViasMinSize = mm(0.4)
    bds.m_ViasMinAnnularWidth = mm(0.1)
    bds.m_MinThroughDrill = mm(0.2)
    bds.m_CopperEdgeClearance = mm(0.3)
    bds.m_HoleClearance = mm(0.2)
    bds.m_HoleToHoleMin = mm(0.25)
    bds.m_SolderMaskExpansion = mm(0.04)
    bds.m_SolderMaskMinWidth = mm(0.0)

    ns = bds.m_NetSettings
    default = ns.GetDefaultNetclass()
    default.SetClearance(mm(0.1))
    default.SetTrackWidth(mm(0.127))
    default.SetViaDiameter(mm(0.45))
    default.SetViaDrill(mm(0.2))
    power = pcbnew.NETCLASS("Power")
    power.SetClearance(mm(0.1))
    power.SetTrackWidth(mm(0.25))
    power.SetViaDiameter(mm(0.5))
    power.SetViaDrill(mm(0.25))
    ns.SetNetclass("Power", power)
    for n in POWER_NETS:
        ns.SetNetclassPatternAssignment(n, "Power")

    # ---- outline: rectangle with a square notch at each corner for the case posts ----
    W, H, N = BG.PCB_W, BG.PCB_H, BG.NOTCH
    outline = [(N, 0), (W - N, 0), (W - N, N), (W, N), (W, H - N), (W - N, H - N), (W - N, H),
               (N, H), (N, H - N), (0, H - N), (0, N), (N, N)]
    for a, b in zip(outline, outline[1:] + outline[:1]):
        add_line(board, a, b)

    # ---- nets ----
    nets = {}
    for name in sorted(set(pins.values())):
        ni = pcbnew.NETINFO_ITEM(board, name)
        board.Add(ni)
        nets[name] = ni

    # ---- footprints ----
    missing = [r for r in comps if comps[r]["footprint"] and r not in PLACE]
    if missing:
        raise SystemExit("no placement for: %s" % sorted(missing))
    for ref, c in sorted(comps.items()):
        if not c["footprint"]:
            continue
        x, y, rot, side = PLACE[ref]
        libpath, name = footprint_path(c["footprint"])
        fp = pcbnew.FootprintLoad(libpath, name)
        if fp is None:
            raise SystemExit("footprint not found: " + c["footprint"])
        lib = c["footprint"].split(":", 1)[0]
        fp.SetFPID(pcbnew.LIB_ID(lib, name))
        fp.SetReference(ref)
        fp.SetValue(c["value"])
        fp.SetPath(pcbnew.KIID_PATH(c["sheet_tstamps"] + c["tstamp"]))
        fp.SetSheetname(c["sheet_names"].strip("/").split("/")[-1])
        fp.SetSheetfile(c["sheet_names"].strip("/").split("/")[-1].lower() + ".kicad_sch")
        fp.SetExcludedFromBOM(False)        # the schematic decides what is in the BOM
        if c["dnp"]:
            fp.SetDNP(True)
            fp.SetExcludedFromPosFiles(True)
        fp.SetLibDescription(c["description"])
        for fname, fval in c["fields"].items():
            if fname in ("Footprint", "Reference", "Value"):
                continue
            fp.SetField(fname, fval)
            fld = fp.GetField(fname)
            fld.SetVisible(False)
            fld.SetLayer(pcbnew.B_Fab if side == B else pcbnew.F_Fab)
        board.Add(fp)
        fp.SetPosition(P(x, y))
        if side == B:
            fp.Flip(P(x, y), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)
        fp.SetOrientationDegrees(rot)
        # designators go to the fab layer: the board is too dense for silkscreen text
        fp.Reference().SetLayer(pcbnew.B_Fab if side == B else pcbnew.F_Fab)
        fp.Reference().SetTextSize(pcbnew.VECTOR2I(mm(0.5), mm(0.5)))
        fp.Reference().SetTextThickness(mm(0.08))
        fp.Reference().SetPosition(P(x, y))
        fp.Value().SetVisible(False)
        for pad in fp.Pads():
            net = pins.get((ref, pad.GetNumber()))
            if net:
                pad.SetNet(nets[net])

    # ---- keep-outs ----
    k = BG.ANT_KEEPOUT
    add_zone(board, rect(*k), [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], name="antenna keep-out",
             keepout={"fill": True, "tracks": True, "vias": True})
    # keep the router 0.35 mm away from the board edge, including the corner notches
    e, N2 = 0.35, BG.NOTCH + 0.35
    edge_bands = [rect(-1, -1, W + 1, e), rect(-1, H - e, W + 1, H + 1), rect(-1, -1, e, H + 1),
                  rect(W - e, -1, W + 1, H + 1), rect(-1, -1, N2, N2), rect(W - N2, -1, W + 1, N2),
                  rect(-1, H - N2, N2, H + 1), rect(W - N2, H - N2, W + 1, H + 1)]
    for band in edge_bands:
        add_zone(board, band, [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], name="edge clearance",
                 keepout={"tracks": True, "vias": True})
    pp = BG.PPG_VIA_KEEPOUT
    add_zone(board, rect(*pp), [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu], name="PPG body: no vias",
             keepout={"vias": True})

    # ---- copper pours ----
    full = rect(-1, -1, W + 1, H + 1)
    add_zone(board, full, [pcbnew.In1_Cu], nets["GND"], "GND plane")
    add_zone(board, full, [pcbnew.In2_Cu], nets["+1V8"], "+1V8 plane")
    # The outer-layer GND pours are added after routing (see import_ses): the router
    # would otherwise assume every GND pad inside them is already connected.

    # ---- silkscreen ----
    add_text(board, "multi-sensor wearable rev A", 18.0, 31.5, pcbnew.B_SilkS, 0.8, mirror=True)
    add_text(board, "BAT", BG.BATPAD_X - 1.6, BG.BATPAD_Y + 2.6, pcbnew.F_SilkS, 0.8)
    for i, label in enumerate(["GND", "1V8", "DIO", "CLK", "RST", "SWO"]):
        add_text(board, label, BG.SWD_X + 6.35 - 2.54 * i, BG.SWD_Y - 1.75, pcbnew.B_SilkS, 0.8, mirror=True)
    add_text(board, "E1", BG.E1_X - 3.3, BG.E_Y, pcbnew.F_SilkS, 0.8)
    add_text(board, "E2", BG.E2_X + 3.3, BG.E_Y, pcbnew.F_SilkS, 0.8)

    # Fan every GND / +1V8 pad out to its plane now, while there is room, and lock those
    # stubs so the router works around them instead of boxing the pads in.
    stitch(board, lock=True)
    pcbnew.SaveBoard(PCB, board)
    pcbnew.ExportSpecctraDSN(board, DSN)
    _project_rule_severities()
    print("placed %d footprints, %d nets -> %s" % (len(board.GetFootprints()), len(nets), PCB))


def _project_rule_severities():
    """The USB connector and the radio module overhang the board edge on purpose, so their
    silkscreen outlines cross it (the fab clips silkscreen at the edge). Don't report that."""
    pro = PCB.replace(".kicad_pcb", ".kicad_pro")
    with open(pro, encoding="utf-8") as f:
        d = json.load(f)
    d.setdefault("board", {}).setdefault("design_settings", {}).setdefault("rule_severities", {})[
        "silk_edge_clearance"] = "ignore"
    with open(pro, "w", encoding="utf-8", newline=chr(10)) as f:
        json.dump(d, f, indent=2)
        f.write(chr(10))


# --------------------------------------------------------------------------- #
def route(passes="40"):
    """Autoroute with Freerouting 1.9.0 (the 2.x releases stalled on this board), then import."""
    if os.path.exists(SES):
        os.remove(SES)
    cmd = [JAVA, "-jar", FREEROUTING, "-de", DSN, "-do", SES, "-mp", passes, "-mt", "1", "-da", "-dct", "0"]
    print(" ".join(cmd))
    subprocess.run(cmd, check=False, cwd=KICAD_DIR)
    if not os.path.exists(SES):
        raise SystemExit("Freerouting produced no session file")
    import_ses()


def import_ses():
    """Rebuild the placed board, then load the router's result onto it."""
    place()
    board = pcbnew.LoadBoard(PCB)
    if not pcbnew.ImportSpecctraSES(board, SES):
        raise SystemExit("SES import failed")
    # Added after routing so the router neither avoids nor relies on them.
    # (import_ses always starts from a freshly placed board, so they are not there yet.)
    add_zone(board, rect(*BG.TEMP_KEEPOUT), [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu],
             name="TMP117 thermal isolation", keepout={"fill": True})
    full = rect(-1, -1, BG.PCB_W + 1, BG.PCB_H + 1)
    gnd = board.FindNet("GND")
    add_zone(board, full, [pcbnew.F_Cu], gnd, "GND top", solid=True)
    add_zone(board, full, [pcbnew.B_Cu], gnd, "GND bottom", solid=True)
    # Every GND / +1V8 pad already has its own locked via to the plane, so whatever the
    # router added on those nets is redundant (and often ends mid-way along a stub).
    for t in list(board.GetTracks()):
        if t.GetNetname() in PLANE_NETS and not t.IsLocked():
            board.Remove(t)
        elif t.GetClass() != "PCB_VIA" and t.GetLength() < mm(0.01):
            board.Remove(t)                 # zero-length leftovers
    tracks = [t for t in board.GetTracks()]
    vias = sum(1 for t in tracks if t.GetClass() == "PCB_VIA")
    print("imported %d track segments, %d vias" % (len(tracks) - vias, vias))
    stitch(board)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)


# --------------------------------------------------------------------------- #
# Plane stitching: the autorouter leaves many GND / +1V8 pads without a via to
# their inner plane. Give every such pad group a short stub and a via.
# --------------------------------------------------------------------------- #
PLANE_NETS = ("GND", "+1V8")
VIA_D, VIA_DRILL, STUB_W, CLR = 0.45, 0.2, 0.2, 0.11
MAZE_W = 0.15            # width of the bent stubs found by the maze search


def _xy(v):
    return (pcbnew.ToMM(v.x) - OX, pcbnew.ToMM(v.y) - OY)


def _rect_dist(p, r):
    dx = max(r[0] - p[0], 0, p[0] - r[2])
    dy = max(r[1] - p[1], 0, p[1] - r[3])
    return (dx * dx + dy * dy) ** 0.5


def _seg_dist(p, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    u = 0 if L2 == 0 else max(0, min(1, ((p[0] - ax) * vx + (p[1] - ay) * vy) / L2))
    cx, cy = ax + u * vx, ay + u * vy
    return ((p[0] - cx) ** 2 + (p[1] - cy) ** 2) ** 0.5


def _inside_board(p, margin):
    W, H, N = BG.PCB_W, BG.PCB_H, BG.NOTCH
    x, y = p
    if not (margin <= x <= W - margin and margin <= y <= H - margin):
        return False
    nx, ny = min(x, W - x), min(y, H - y)
    return not (nx < N + margin and ny < N + margin)


def _touches(a, b):
    import math
    (ka, A), (kb, B) = a, b
    if ka == "trk" and kb == "trk":
        if A["layer"] != B["layer"]:
            return False
        tol = (A["w"] + B["w"]) / 2 - 0.01
        return any(_seg_dist(e, B["a"], B["b"]) < tol for e in (A["a"], A["b"])) or any(
            _seg_dist(e, A["a"], A["b"]) < tol for e in (B["a"], B["b"]))
    if ka == "trk" and kb == "pad":
        return (B["layer"] is None or B["layer"] == A["layer"]) and any(
            _rect_dist(e, B["rect"]) < 0.01 for e in (A["a"], A["b"]))
    if ka == "trk" and kb == "via":
        return any(math.dist(e, B["c"]) < B["r"] for e in (A["a"], A["b"]))
    if kb == "trk":
        return _touches(b, a)
    if ka == "pad" and kb == "via":
        return _rect_dist(B["c"], A["rect"]) < 0.01
    if ka == "via" and kb == "pad":
        return _touches(b, a)
    return False


def stitch(board, lock=False):
    import math
    pads, tracks, vias = [], [], []
    for fp in board.GetFootprints():
        for pad in fp.Pads():
            through = pad.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)
            if not through and not (pad.IsOnLayer(pcbnew.F_Cu) or pad.IsOnLayer(pcbnew.B_Cu)):
                continue                    # paste-only helper pads carry no copper
            bb = pad.GetBoundingBox()
            x0, y0 = _xy(pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()))
            x1, y1 = _xy(pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()))
            pads.append({"ref": fp.GetReference(), "num": pad.GetNumber(), "net": pad.GetNetname(),
                         "rect": (x0, y0, x1, y1), "c": _xy(pad.GetPosition()),
                         "layer": None if through else (pcbnew.B_Cu if pad.IsOnLayer(pcbnew.B_Cu) else pcbnew.F_Cu)})
    # every rule area that forbids vias (board-level ones and those inside footprints)
    no_via = []
    zones = list(board.Zones()) + [z for fp in board.GetFootprints() for z in fp.Zones()]
    for z in zones:
        if z.GetIsRuleArea() and z.GetDoNotAllowVias():
            bb = z.GetBoundingBox()
            x0, y0 = _xy(pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()))
            x1, y1 = _xy(pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()))
            no_via.append((x0, y0, x1, y1))
    no_via.append(BG.TEMP_KEEPOUT)
    for t in board.GetTracks():
        if t.GetClass() == "PCB_VIA":
            vias.append({"net": t.GetNetname(), "c": _xy(t.GetPosition()),
                         "r": pcbnew.ToMM(t.GetWidth(pcbnew.F_Cu)) / 2})
        else:
            tracks.append({"net": t.GetNetname(), "a": _xy(t.GetStart()), "b": _xy(t.GetEnd()),
                           "w": pcbnew.ToMM(t.GetWidth()), "layer": t.GetLayer()})

    def via_ok(c, net, own=None):
        r = VIA_D / 2
        if not _inside_board(c, r + 0.32):
            return False
        for k in no_via:
            if _rect_dist(c, k) < r + 0.03:
                return False
        for p in pads:                      # a via is copper on every layer, so every pad counts
            if p is own:
                continue
            if _rect_dist(c, p["rect"]) < r + (CLR if p["net"] != net else 0.05):
                return False
        for t in tracks:
            if t["net"] != net and _seg_dist(c, t["a"], t["b"]) < r + t["w"] / 2 + CLR:
                return False
        for v in vias:
            if math.dist(c, v["c"]) < r + v["r"] + (CLR if v["net"] != net else 0.15):
                return False
        return True

    def stub_ok(a, b, layer, net, own):
        n = max(2, int(math.dist(a, b) / 0.04))
        for i in range(n + 1):
            q = (a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n)
            for p in pads:
                if p is own or p["net"] == net or (p["layer"] is not None and p["layer"] != layer):
                    continue
                if _rect_dist(q, p["rect"]) < STUB_W / 2 + CLR:
                    return False
            for t in tracks:
                if t["net"] != net and t["layer"] == layer and \
                        _seg_dist(q, t["a"], t["b"]) < STUB_W / 2 + t["w"] / 2 + CLR:
                    return False
            for v in vias:
                if v["net"] != net and math.dist(q, v["c"]) < STUB_W / 2 + v["r"] + CLR:
                    return False
        return True

    def add_track(a, b, layer, net, ni):
        trk = pcbnew.PCB_TRACK(board)
        trk.SetStart(P(*a))
        trk.SetEnd(P(*b))
        trk.SetWidth(mm(STUB_W))
        trk.SetLayer(layer)
        trk.SetNet(ni)
        trk.SetLocked(lock)
        board.Add(trk)
        tracks.append({"net": net, "a": a, "b": b, "w": STUB_W, "layer": layer})

    def build_groups(net):
        nodes = [("pad", p) for p in pads if p["net"] == net] + [("trk", t) for t in tracks if t["net"] == net] + [
            ("via", v) for v in vias if v["net"] == net]
        parent = list(range(len(nodes)))

        def find_(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                if _touches(nodes[i], nodes[j]):
                    parent[find_(i)] = find_(j)
        groups = {}
        for i, nd in enumerate(nodes):
            groups.setdefault(find_(i), []).append(nd)
        on_plane = [g for g in groups.values() if any(k == "via" or (k == "pad" and o["layer"] is None) for k, o in g)]
        loose = [g for g in groups.values() if g not in on_plane and any(k == "pad" for k, o in g)]
        return on_plane, loose

    def try_via(group, net, ni):
        best = None
        for k, p in group:
            if k != "pad":
                continue
            half = max(p["rect"][2] - p["rect"][0], p["rect"][3] - p["rect"][1]) / 2
            for step in range(0, 45):
                dist = half + VIA_D / 2 + 0.06 + 0.08 * step
                if best is not None and dist >= best[0]:
                    break
                for ang in range(0, 360, 15):
                    c = (p["c"][0] + dist * math.cos(math.radians(ang)), p["c"][1] + dist * math.sin(math.radians(ang)))
                    if via_ok(c, net) and stub_ok(p["c"], c, p["layer"], net, p):
                        best = (dist, p, c)
                        break
                if best is not None and best[1] is p:
                    break
        if best is None:
            # exposed pads: a via in the middle of the pad itself
            for k, p in group:
                if k == "pad" and min(p["rect"][2] - p["rect"][0], p["rect"][3] - p["rect"][1]) >= VIA_D + 0.3                         and via_ok(p["c"], net, own=p):
                    best = (0, p, p["c"])
                    break
        if best is None:
            return False
        _, p, c = best
        via = pcbnew.PCB_VIA(board)
        via.SetPosition(P(*c))
        via.SetWidth(pcbnew.F_Cu, mm(VIA_D))
        via.SetDrill(mm(VIA_DRILL))
        via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        via.SetNet(ni)
        via.SetLocked(lock)
        board.Add(via)
        vias.append({"net": net, "c": c, "r": VIA_D / 2})
        if c != p["c"]:
            add_track(p["c"], c, p["layer"], net, ni)
        return True

    # rule areas that forbid tracks (antenna keep-out, edge bands, the module's own keep-outs)
    no_track = []
    for z in zones:
        if z.GetIsRuleArea() and z.GetDoNotAllowTracks():
            bb = z.GetBoundingBox()
            x0, y0 = _xy(pcbnew.VECTOR2I(bb.GetLeft(), bb.GetTop()))
            x1, y1 = _xy(pcbnew.VECTOR2I(bb.GetRight(), bb.GetBottom()))
            no_track.append((x0, y0, x1, y1))

    def try_link(group, on_plane, net, ni):
        """No room for a straight stub: search a bent path on the pad's own layer, either to a
        spot where a via fits or to copper of the same net that already reaches the plane."""
        import heapq
        G, R, W2, C2 = 0.05, 5.0, MAZE_W / 2, 0.13
        for k, p in group:
            if k != "pad":
                continue
            layer, c0 = p["layer"], p["c"]
            box = (c0[0] - R, c0[1] - R, c0[0] + R, c0[1] + R)
            near_pads = [q for q in pads if q is not p and q["net"] != net and (q["layer"] in (None, layer))
                         and _rect_dist(c0, q["rect"]) < R * 1.5]
            near_trk = [q for q in tracks if q["net"] != net and q["layer"] == layer
                        and _seg_dist(c0, q["a"], q["b"]) < R * 1.5]
            near_via = [q for q in vias if q["net"] != net and math.dist(c0, q["c"]) < R * 1.5]
            goal_pads = [o for g in on_plane for kk, o in g if kk == "pad" and o["layer"] in (None, layer)]
            goal_vias = [o for g in on_plane for kk, o in g if kk == "via"]
            goal_trk = [o for g in on_plane for kk, o in g if kk == "trk" and o["layer"] == layer]
            cache = {}

            def free(ij):
                if ij in cache:
                    return cache[ij]
                q = (c0[0] + ij[0] * G, c0[1] + ij[1] * G)
                ok = True
                if _rect_dist(q, p["rect"]) > 0:
                    if not _inside_board(q, W2 + 0.31) or any(_rect_dist(q, kz) < W2 + 0.02 for kz in no_track):
                        ok = False
                    elif any(_rect_dist(q, o["rect"]) < W2 + C2 for o in near_pads):
                        ok = False
                    elif any(_seg_dist(q, o["a"], o["b"]) < W2 + o["w"] / 2 + C2 for o in near_trk):
                        ok = False
                    elif any(math.dist(q, o["c"]) < W2 + o["r"] + C2 for o in near_via):
                        ok = False
                cache[ij] = ok
                return ok

            def goal(ij):
                q = (c0[0] + ij[0] * G, c0[1] + ij[1] * G)
                if any(_rect_dist(q, o["rect"]) == 0 for o in goal_pads):
                    return "link"
                if any(math.dist(q, o["c"]) < o["r"] * 0.6 for o in goal_vias):
                    return "link"
                if any(_seg_dist(q, o["a"], o["b"]) < 0.03 for o in goal_trk):
                    return "link"
                if _rect_dist(q, p["rect"]) > VIA_D / 2 + 0.05 and via_ok(q, net):
                    return "via"
                return None

            n = int(R / G)
            dist, prev, heap, found = {(0, 0): 0.0}, {}, [(0.0, (0, 0))], None
            while heap:
                d, ij = heapq.heappop(heap)
                if d > dist.get(ij, 1e9):
                    continue
                kind = goal(ij)
                if kind:
                    found = (ij, kind)
                    break
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nb = (ij[0] + di, ij[1] + dj)
                    if abs(nb[0]) > n or abs(nb[1]) > n or not free(nb):
                        continue
                    if di and dj and not (free((ij[0] + di, ij[1])) and free((ij[0], ij[1] + dj))):
                        continue
                    nd = d + (1.4142 if di and dj else 1.0)
                    if nd < dist.get(nb, 1e9):
                        dist[nb], prev[nb] = nd, ij
                        heapq.heappush(heap, (nd, nb))
            if not found:
                continue
            path, ij = [found[0]], found[0]
            while ij in prev:
                ij = prev[ij]
                path.append(ij)
            path.reverse()
            pts = [path[0]]
            for i in range(1, len(path) - 1):          # keep only the corners
                d1 = (path[i][0] - path[i - 1][0], path[i][1] - path[i - 1][1])
                d2 = (path[i + 1][0] - path[i][0], path[i + 1][1] - path[i][1])
                if d1 != d2:
                    pts.append(path[i])
            pts.append(path[-1])
            xy = [(round(c0[0] + i * G, 4), round(c0[1] + j * G, 4)) for i, j in pts]
            for s, e in zip(xy, xy[1:]):
                trk = pcbnew.PCB_TRACK(board)
                trk.SetStart(P(*s))
                trk.SetEnd(P(*e))
                trk.SetWidth(mm(MAZE_W))
                trk.SetLayer(layer)
                trk.SetNet(ni)
                board.Add(trk)
                tracks.append({"net": net, "a": s, "b": e, "w": MAZE_W, "layer": layer})
            if found[1] == "via":
                via = pcbnew.PCB_VIA(board)
                via.SetPosition(P(*xy[-1]))
                via.SetWidth(pcbnew.F_Cu, mm(VIA_D))
                via.SetDrill(mm(VIA_DRILL))
                via.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
                via.SetNet(ni)
                board.Add(via)
                vias.append({"net": net, "c": xy[-1], "r": VIA_D / 2})
            return True
        return False

    added_vias, added_links, failed = 0, 0, []
    for net in PLANE_NETS:
        ni = board.FindNet(net)
        progress = True
        while progress:
            progress = False
            on_plane, loose = build_groups(net)
            for group in loose:
                if try_via(group, net, ni):
                    added_vias += 1
                    progress = True
            if not progress:
                for group in loose:
                    if try_link(group, on_plane, net, ni):
                        added_links += 1
                        progress = True
                        break
        _, loose = build_groups(net)
        for group in loose:
            failed.append(net + ": " + ", ".join("%s.%s" % (o["ref"], o["num"]) for k, o in group if k == "pad"))
    print("stitching: added %d plane vias and %d link tracks" % (added_vias, added_links))
    for f in failed:
        print("  NOT CONNECTED to its plane: " + f)


def fill():
    board = pcbnew.LoadBoard(PCB)
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)


# Height of each part above its side of the board, in mm (datasheet maximums, rounded up).
HEIGHTS = {
    "R_0402_1005Metric": 0.4, "C_0402_1005Metric": 0.6, "C_0603_1608Metric": 0.95,
    "SOT-23-6": 1.45, "SOT-523": 0.8, "SOT-353_SC-70-5": 1.1, "VSSOP-8_3x3mm_P0.65mm": 1.1,
    "TI_YBG0008_DSBGA-8_1.6x1.1mm": 0.5, "TDFN-8-1EP_2x2mm_P0.5mm_EP0.8x1.2mm": 0.8,
    "VSON-8_1.5x2mm_P0.5mm": 1.0, "L_Changjiang_FTC201612S": 1.2,
    "WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4.3mm": 0.8, "WSON-6-1EP_2x2mm_P0.65mm_EP1x1.6mm": 0.8,
    "Bosch_LGA-14_3x2.5mm_P0.5mm": 0.85, "MAXM86161_OLGA-14_2.9x4.3mm": 1.4,
    "Crystal_SMD_3215-2Pin_3.2x1.5mm": 0.9, "LED_RGB_1210": 1.0, "Texas_DPY0002A_0.6x1mm_P0.65mm": 0.4,
    "Raytac_MDBT50Q": BG.H_MODULE, "USB_C_Receptacle_HRO_TYPE-C-31-M-12": BG.H_USB,
    "JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal": 2.95, "SW_SPST_B3U-1000P": BG.H_SW,
    "TestPoint_Pad_D1.0mm": 0.05, "TestPads_1x06_P2.54mm": 0.05,
    "BatteryPads_1x02_P4.0mm": 1.8,          # solder blob and wire
    "MountingHole_2.2mm_M2_Pad": 3.0,        # M2 nut plus the end of the electrode screw
}


def dump():
    """Write the placed parts (body box in board coordinates plus height) for the case fit check."""
    board = pcbnew.LoadBoard(PCB)
    to_mm = pcbnew.ToMM
    parts = []
    for fp in board.GetFootprints():
        name = str(fp.GetFPID().GetLibItemName())
        bottom = fp.GetLayer() == pcbnew.B_Cu
        fab = pcbnew.B_Fab if bottom else pcbnew.F_Fab
        xs, ys = [], []
        for g in fp.GraphicalItems():
            if g.GetClass() == "PCB_SHAPE" and g.GetLayer() == fab:
                bb = g.GetBoundingBox()
                xs += [bb.GetLeft(), bb.GetRight()]
                ys += [bb.GetTop(), bb.GetBottom()]
        for pad in fp.Pads():
            bb = pad.GetBoundingBox()
            xs += [bb.GetLeft(), bb.GetRight()]
            ys += [bb.GetTop(), bb.GetBottom()]
        parts.append({
            "ref": fp.GetReference(), "footprint": name, "side": "bottom" if bottom else "top",
            "x0": round(to_mm(min(xs)) - OX, 3), "y0": round(to_mm(min(ys)) - OY, 3),
            "x1": round(to_mm(max(xs)) - OX, 3), "y1": round(to_mm(max(ys)) - OY, 3),
            "height": HEIGHTS[name],
            "tht": [[round(to_mm(p.GetPosition().x) - OX, 3), round(to_mm(p.GetPosition().y) - OY, 3)]
                    for p in fp.Pads() if p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH)],
        })
    out = os.path.join(KICAD_DIR, "board_parts.json")
    with open(out, "w", newline="\n") as f:
        json.dump(sorted(parts, key=lambda p: p["ref"]), f, indent=1)
    print("wrote", out, len(parts), "parts")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "place"
    {"place": place, "route": lambda: route(*sys.argv[2:3]), "import": import_ses, "fill": fill, "dump": dump}[cmd]()

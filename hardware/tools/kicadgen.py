"""Generate a hierarchical KiCad 10 schematic from a Python netlist description.

Every part pin gets a short wire stub ending in a net label (local label for nets
that stay on one sheet, global label for nets that cross sheets) or a power
symbol for power nets. Pins listed as NC get a no-connect flag. Symbols are
copied (flattened) from the KiCad libraries and from the project library so the
schematic is self-contained.
"""
import copy
import os
import re
import uuid

from sexpr import Q, dumps, find, find_all, parse

GRID = 1.27
STUB = 2.54
NS = uuid.UUID("6f1d3c2a-9a51-4d0e-8f43-0b7e2d6c1a11")


def uid(*parts):
    return Q(str(uuid.uuid5(NS, "/".join(str(p) for p in parts))))


def snap(v):
    return round(round(v / GRID) * GRID, 4)


# --------------------------------------------------------------------------- #
# Symbol libraries
# --------------------------------------------------------------------------- #
class Libraries:
    def __init__(self, kicad_symbol_dir, project_libs=None):
        self.dir = kicad_symbol_dir
        self.project_libs = project_libs or {}
        self._cache = {}

    def _load(self, lib):
        if lib not in self._cache:
            path = self.project_libs.get(lib) or os.path.join(self.dir, lib + ".kicad_sym")
            with open(path, encoding="utf-8") as f:
                root = parse(f.read())
            self._cache[lib] = {s[1]: s for s in find_all(root, "symbol")}
        return self._cache[lib]

    def symbol(self, lib_id):
        """Return a flattened copy of the symbol named `lib:name`, renamed to lib_id."""
        lib, name = lib_id.split(":", 1)
        node = self._flatten(lib, name)
        node[1] = Q(lib_id)
        return node

    def _flatten(self, lib, name):
        syms = self._load(lib)
        if name not in syms:
            raise KeyError("symbol %s not in library %s" % (name, lib))
        node = copy.deepcopy(syms[name])
        ext = find(node, "extends")
        if ext is None:
            return node
        parent = self._flatten(lib, ext[1])
        pname = str(parent[1])
        # child properties override the parent's
        child_props = {p[1]: p for p in find_all(node, "property")}
        out = [x for x in parent]
        out[1] = Q(name)
        for i, x in enumerate(out):
            if isinstance(x, list) and x and x[0] == "property" and x[1] in child_props:
                out[i] = child_props.pop(x[1])
            elif isinstance(x, list) and x and x[0] == "symbol":
                sub = copy.deepcopy(x)
                sub[1] = Q(str(sub[1]).replace(pname + "_", name + "_", 1))
                out[i] = sub
        # properties only the child has
        insert_at = max(i for i, x in enumerate(out) if isinstance(x, list) and x[0] == "property") + 1
        for p in child_props.values():
            out.insert(insert_at, p)
            insert_at += 1
        return out


def symbol_units(sym):
    """Map unit number -> list of pin dicts (unit 0 pins are shared by all units)."""
    name = str(sym[1]).split(":", 1)[-1]
    units = {}
    for sub in find_all(sym, "symbol"):
        m = re.match(re.escape(name) + r"_(\d+)_(\d+)$", str(sub[1]))
        if not m:
            continue
        unit, style = int(m.group(1)), int(m.group(2))
        if style not in (0, 1):
            continue
        pins = units.setdefault(unit, {"pins": [], "boxes": []})
        for p in find_all(sub, "pin"):
            at = find(p, "at")
            nm = find(p, "name")
            num = find(p, "number")
            hidden = any(isinstance(x, list) and x[0] == "hide" and x[1] == "yes" for x in p) or "hide" in p
            pins["pins"].append({
                "type": p[1], "x": float(at[1]), "y": float(at[2]), "angle": int(float(at[3])),
                "length": float(find(p, "length")[1]),
                "name": str(nm[1]), "number": str(num[1]), "hidden": hidden,
            })
        for g in sub:
            if not isinstance(g, list):
                continue
            pts = []
            if g[0] in ("rectangle",):
                pts = [find(g, "start"), find(g, "end")]
            elif g[0] in ("polyline",):
                pts = find(find(g, "pts") or [], "xy") and find_all(find(g, "pts"), "xy")
            elif g[0] == "circle":
                c = find(g, "center")
                r = float(find(g, "radius")[1])
                pts = [["xy", float(c[1]) - r, float(c[2]) - r], ["xy", float(c[1]) + r, float(c[2]) + r]]
            for q in pts or []:
                pins["boxes"].append((float(q[1]), float(q[2])))
    shared = units.pop(0, {"pins": [], "boxes": []})
    if not units:
        units[1] = {"pins": [], "boxes": []}
    for u in units.values():
        u["pins"] = shared["pins"] + u["pins"]
        u["boxes"] = shared["boxes"] + u["boxes"]
    return units


def is_power_symbol(sym):
    return find(sym, "power") is not None


# --------------------------------------------------------------------------- #
# Design description
# --------------------------------------------------------------------------- #
class Part:
    def __init__(self, ref, lib_id, value, footprint="", pins=None, nc=(), sheet=None,
                 group=None, lcsc="", mpn="", manufacturer="", dnp=False, note=""):
        self.ref = ref
        self.lib_id = lib_id
        self.value = value
        self.footprint = footprint
        self.pins = dict(pins or {})   # pin number or pin name -> net
        self.nc = set(nc)              # pin numbers or names explicitly unconnected
        self.sheet = sheet
        self.group = group or ref
        self.lcsc = lcsc
        self.mpn = mpn
        self.manufacturer = manufacturer
        self.dnp = dnp
        self.note = note


class Design:
    def __init__(self, project, power_nets, power_symbols, sheets):
        self.project = project
        self.power_nets = power_nets        # net name -> lib_id of the power symbol
        self.power_symbols = power_symbols  # unused, kept for clarity
        self.sheets = sheets                # list of (sheet_name, filename, title)
        self.parts = []
        self.texts = {}                     # sheet -> list of (x, y, text)

    def add(self, part):
        if any(p.ref == part.ref for p in self.parts):
            raise ValueError("duplicate ref " + part.ref)
        self.parts.append(part)
        return part

    def note(self, sheet, text):
        self.texts.setdefault(sheet, []).append(text)


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def _prop(name, value, x, y, hide=False, angle=0, size=1.27, justify=None):
    eff = ["effects", ["font", ["size", size, size]]]
    if justify:
        eff.append(["justify"] + justify)
    p = ["property", Q(name), Q(value), ["at", x, y, angle]]
    if hide:
        p.append(["hide", "yes"])
    p.append(eff)
    return p


OUT_DIR = {0: (-1, 0), 180: (1, 0), 90: (0, 1), 270: (0, -1)}  # schematic coords, y down


def resolve_pins(part, unit_pins):
    """Return {pin_number: net or None} for every pin of the part, plus NC set."""
    by_name = {}
    for u, info in unit_pins.items():
        for p in info["pins"]:
            by_name.setdefault(p["name"], set()).add(p["number"])
    numbers = {p["number"] for info in unit_pins.values() for p in info["pins"]}
    nets = {}
    for key, net in part.pins.items():
        nums = {key} if key in numbers else by_name.get(key)
        if not nums:
            raise KeyError("%s: no pin %r in %s" % (part.ref, key, part.lib_id))
        for n in nums:
            if n in nets and nets[n] != net:
                raise ValueError("%s pin %s assigned to %s and %s" % (part.ref, n, nets[n], net))
            nets[n] = net
    nc = set()
    for key in part.nc:
        nums = {key} if key in numbers else by_name.get(key)
        if not nums:
            raise KeyError("%s: no NC pin %r" % (part.ref, key))
        nc |= nums
    missing = numbers - set(nets) - nc
    if missing:
        raise ValueError("%s (%s): pins not assigned: %s" % (part.ref, part.lib_id, sorted(missing, key=_natkey)))
    both = set(nets) & nc
    if both:
        raise ValueError("%s: pins both connected and NC: %s" % (part.ref, both))
    return nets, nc


def _natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", s)]


def generate(design, libs, outdir, paper="A3"):
    os.makedirs(outdir, exist_ok=True)
    root_uuid = uid(design.project, "root")
    sheet_uuid = {s[0]: uid(design.project, "sheet", s[0]) for s in design.sheets}

    # which sheets each signal net appears on
    sym_cache = {}

    def sym(lib_id):
        if lib_id not in sym_cache:
            sym_cache[lib_id] = libs.symbol(lib_id)
        return sym_cache[lib_id]

    resolved = {}
    net_sheets = {}
    for part in design.parts:
        units = symbol_units(sym(part.lib_id))
        nets, nc = resolve_pins(part, units)
        resolved[part.ref] = (units, nets, nc)
        for n in nets.values():
            net_sheets.setdefault(n, set()).add(part.sheet)

    # every signal net needs >= 2 pins in total
    pin_count = {}
    for ref, (units, nets, nc) in resolved.items():
        for n in nets.values():
            pin_count[n] = pin_count.get(n, 0) + 1
    single = sorted(n for n, c in pin_count.items() if c < 2 and n not in design.power_nets)
    if single:
        raise ValueError("nets with a single pin: %s" % single)

    pages = {}
    for page_no, (sname, fname, title) in enumerate(design.sheets, start=2):
        parts = [p for p in design.parts if p.sheet == sname]
        pages[sname] = _sheet(design, libs, sym, parts, resolved, net_sheets, sname, fname,
                              title, root_uuid, sheet_uuid[sname], page_no, paper)
        with open(os.path.join(outdir, fname), "w", encoding="utf-8", newline="\n") as f:
            f.write(dumps(pages[sname]) + "\n")

    root = _root(design, root_uuid, sheet_uuid, paper)
    with open(os.path.join(outdir, design.project + ".kicad_sch"), "w", encoding="utf-8", newline="\n") as f:
        f.write(dumps(root) + "\n")
    return resolved


def _header(uuid_, paper, title, page_comment=""):
    return [
        "kicad_sch", ["version", "20250610"], ["generator", Q("eeschema")],
        ["generator_version", Q("10.0")], ["uuid", uuid_], ["paper", Q(paper)],
        ["title_block", ["title", Q(title)], ["date", Q("2026-11-06")], ["rev", Q("A")],
         ["company", Q("multi-sensor wearable")],
         ["comment", 1, Q("Generated by hardware/tools/gen_schematic.py - edit the design, not this file")],
         ["comment", 2, Q(page_comment)]],
    ]


def _root(design, root_uuid, sheet_uuid, paper):
    sch = _header(root_uuid, paper, "Wearable multi-sensor - rev A", "Root sheet")
    sch.append(["lib_symbols"])
    x, y = 30.48, 40.64
    for i, (sname, fname, title) in enumerate(design.sheets):
        sx = x + (i % 3) * 120.65
        sy = y + (i // 3) * 76.2
        sch.append([
            "sheet", ["at", sx, sy], ["size", 101.6, 50.8], ["exclude_from_sim", "no"],
            ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"],
            ["fields_autoplaced", "yes"],
            ["stroke", ["width", 0.1524], ["type", "solid"]], ["fill", ["color", 0, 0, 0, 0.0]],
            ["uuid", sheet_uuid[sname]],
            _prop("Sheetname", sname, sx, sy - 0.7, justify=["left", "bottom"]),
            _prop("Sheetfile", fname, sx, sy + 51.4, justify=["left", "top"]),
            ["instances", ["project", Q(design.project), ["path", Q("/" + root_uuid), ["page", Q(str(i + 2))]]]],
        ])
        sch.append(["text", Q(title), ["exclude_from_sim", "no"], ["at", sx + 2.54, sy + 10.16, 0],
                    ["effects", ["font", ["size", 1.8, 1.8]], ["justify", "left", "top"]],
                    ["uuid", uid(design.project, "roottext", sname)]])
    for j, t in enumerate(design.texts.get("root", [])):
        sch.append(["text", Q(t), ["exclude_from_sim", "no"], ["at", 30.48, 205.74 + j * 0.0, 0],
                    ["effects", ["font", ["size", 1.5, 1.5]], ["justify", "left", "top"]],
                    ["uuid", uid(design.project, "rootnote", j)]])
    sch.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]])
    sch.append(["embedded_fonts", "no"])
    return sch


def _unit_extent(info):
    xs = [p["x"] for p in info["pins"]] + [b[0] for b in info["boxes"]]
    ys = [p["y"] for p in info["pins"]] + [b[1] for b in info["boxes"]]
    if not xs:
        return 0, 0, 0, 0
    return min(xs), max(xs), min(ys), max(ys)


def _sheet(design, libs, sym, parts, resolved, net_sheets, sname, fname, title,
           root_uuid, suuid, page_no, paper):
    proj = design.project
    sch = _header(suuid, paper, title, sname)
    lib_symbols = ["lib_symbols"]
    sch.append(lib_symbols)
    used_libs = []
    path = "/%s/%s" % (root_uuid, suuid)
    W, H = {"A3": (420.0, 297.0), "A2": (594.0, 420.0), "A1": (841.0, 594.0)}[paper]

    def use(lib_id):
        if lib_id not in used_libs:
            used_libs.append(lib_id)
            lib_symbols.append(sym(lib_id))

    # ---- layout: groups in reading order, parts of a group side by side ----
    groups = []
    for p in parts:
        for g in groups:
            if g[0] == p.group:
                g[1].append(p)
                break
        else:
            groups.append((p.group, [p]))

    items = []  # (part, unit, info, w, h, ox, oy) relative to group origin
    cursor_x, cursor_y, row_h = 15.24, 30.48, 0.0
    placements = []
    for gname, gparts in groups:
        boxes = []
        gx = 0.0
        gh = 0.0
        for p in gparts:
            units, nets, nc = resolved[p.ref]
            for u in sorted(units):
                info = units[u]
                if not info["pins"] and not info["boxes"]:
                    continue
                x0, x1, y0, y1 = _unit_extent(info)
                lab_l = lab_r = lab_v = 0.0
                for pin in info["pins"]:
                    n = nets.get(pin["number"])
                    ln = (len(n) * 1.05 + 4.5) if n else 2.0
                    if pin["angle"] == 0:
                        lab_l = max(lab_l, ln)
                    elif pin["angle"] == 180:
                        lab_r = max(lab_r, ln)
                    else:
                        lab_v = max(lab_v, 7.0 if n in design.power_nets else ln)
                w = (x1 - x0) + lab_l + lab_r + 5.08
                h = (y1 - y0) + 2 * max(lab_v, 3.0) + 7.62
                boxes.append((p, u, info, gx + lab_l - x0 + 2.54, max(lab_v, 3.0) + y1 + 3.81, w, h))
                gx += w
                gh = max(gh, h)
        gw = gx
        if cursor_x + gw > W - 15.24 and cursor_x > 15.24:
            cursor_x = 15.24
            cursor_y += row_h + 7.62
            row_h = 0.0
        for (p, u, info, ox, oy, w, h) in boxes:
            placements.append((p, u, info, snap(cursor_x + ox), snap(cursor_y + 6.35 + oy)))
        sch.append(["text", Q(gname), ["exclude_from_sim", "no"], ["at", snap(cursor_x), snap(cursor_y + 2.54), 0],
                    ["effects", ["font", ["size", 2.0, 2.0], ["bold", "yes"]], ["justify", "left", "bottom"]],
                    ["uuid", uid(proj, sname, "grouptitle", gname)]])
        sch.append(["rectangle", ["start", snap(cursor_x - 2.54), snap(cursor_y - 1.27)],
                    ["end", snap(cursor_x + gw), snap(cursor_y + gh + 6.35)],
                    ["stroke", ["width", 0.1], ["type", "dash"]], ["fill", ["type", "none"]],
                    ["uuid", uid(proj, sname, "groupbox", gname)]])
        cursor_x += gw + 7.62
        row_h = max(row_h, gh + 6.35)
    if cursor_y + row_h > H - 10:
        raise ValueError("sheet %s overflows %s paper (needs %.0f mm)" % (sname, paper, cursor_y + row_h))

    # notes at the bottom right
    for j, t in enumerate(design.texts.get(sname, [])):
        sch.append(["text", Q(t), ["exclude_from_sim", "no"], ["at", snap(cursor_x if False else 15.24), snap(cursor_y + row_h + 10.16 + j * 0), 0],
                    ["effects", ["font", ["size", 1.5, 1.5]], ["justify", "left", "top"]],
                    ["uuid", uid(proj, sname, "note", j)]])

    pwr_count = [0]

    def power_symbol(net, x, y, direction):
        lib_id = design.power_nets[net]
        use(lib_id)
        pwr_count[0] += 1
        ref = "#PWR0%s%02d" % (page_no, pwr_count[0])
        is_gnd = net.upper().startswith("GND")
        # rotate so the symbol body points away from the pin
        if is_gnd:
            rot = {(0, 1): 0, (0, -1): 180, (-1, 0): 270, (1, 0): 90}[direction]
        else:
            rot = {(0, -1): 0, (0, 1): 180, (-1, 0): 90, (1, 0): 270}[direction]
        psym = sym(lib_id)
        val = net
        return [
            "symbol", ["lib_id", Q(lib_id)], ["at", x, y, rot], ["unit", 1],
            ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"], ["dnp", "no"],
            ["uuid", uid(proj, sname, "pwr", ref)],
            _prop("Reference", ref, x, y, hide=True),
            _prop("Value", val, x, y + (3.81 if is_gnd else -3.81)),
            _prop("Footprint", "", x, y, hide=True),
            _prop("Datasheet", "", x, y, hide=True),
            _prop("Description", "", x, y, hide=True),
            ["pin", Q(symbol_units(psym)[1]["pins"][0]["number"]), ["uuid", uid(proj, sname, "pwrpin", ref)]],
            ["instances", ["project", Q(proj), ["path", Q(path), ["reference", Q(ref)], ["unit", 1]]]],
        ]

    for (p, u, info, X, Y) in placements:
        units, nets, nc = resolved[p.ref]
        use(p.lib_id)
        s = sym(p.lib_id)
        x0, x1, y0, y1 = _unit_extent(info)
        node = [
            "symbol", ["lib_id", Q(p.lib_id)], ["at", X, Y, 0], ["unit", u],
            ["exclude_from_sim", "no"], ["in_bom", "yes"], ["on_board", "yes"],
            ["dnp", "yes" if p.dnp else "no"], ["uuid", uid(proj, "sym", p.ref, u)],
            _prop("Reference", p.ref, snap(X + x1 + 1.27), snap(Y - y1 - 1.27), justify=["left"]),
            _prop("Value", p.value, snap(X + x1 + 1.27), snap(Y - y1 + 1.27), justify=["left"]),
            _prop("Footprint", p.footprint, X, Y, hide=True),
            _prop("Datasheet", _get_prop(s, "Datasheet"), X, Y, hide=True),
            _prop("Description", _get_prop(s, "Description"), X, Y, hide=True),
        ]
        for k, v in (("LCSC", p.lcsc), ("MPN", p.mpn), ("Manufacturer", p.manufacturer), ("Note", p.note)):
            if v:
                node.append(_prop(k, v, X, Y, hide=True))
        for pin in sorted({pp["number"] for i2 in units.values() for pp in i2["pins"]}, key=_natkey):
            node.append(["pin", Q(pin), ["uuid", uid(proj, "pin", p.ref, pin)]])
        node.append(["instances", ["project", Q(proj), ["path", Q(path), ["reference", Q(p.ref)], ["unit", u]]]])
        sch.append(node)

        done_points = {}
        for pin in info["pins"]:
            px, py = snap(X + pin["x"]), snap(Y - pin["y"])
            key = (px, py)
            num = pin["number"]
            if num in nc:
                if key not in done_points:
                    sch.append(["no_connect", ["at", px, py], ["uuid", uid(proj, "nc", p.ref, num)]])
                    done_points[key] = None
                continue
            net = nets.get(num)
            if net is None:
                continue  # pin belongs to another unit's assignment check
            if key in done_points:
                if done_points[key] != net:
                    raise ValueError("%s: stacked pins at same point on different nets" % p.ref)
                continue
            done_points[key] = net
            dx, dy = OUT_DIR[pin["angle"]]
            ex, ey = snap(px + dx * STUB), snap(py + dy * STUB)
            sch.append(["wire", ["pts", ["xy", px, py], ["xy", ex, ey]],
                        ["stroke", ["width", 0], ["type", "default"]], ["uuid", uid(proj, "w", p.ref, num)]])
            if net in design.power_nets:
                sch.append(power_symbol(net, ex, ey, (dx, dy)))
                continue
            angle = {(-1, 0): 180, (1, 0): 0, (0, -1): 90, (0, 1): 270}[(dx, dy)]
            just = ["left"] if angle in (0, 90) else ["right"]
            if len(net_sheets[net]) > 1:
                sch.append(["global_label", Q(net), ["shape", "passive"], ["at", ex, ey, angle],
                            ["fields_autoplaced", "yes"],
                            ["effects", ["font", ["size", 1.27, 1.27]], ["justify"] + just],
                            ["uuid", uid(proj, "gl", p.ref, num)],
                            ["property", Q("Intersheetrefs"), Q("${INTERSHEET_REFS}"), ["at", ex, ey, 0],
                             ["hide", "yes"], ["effects", ["font", ["size", 1.27, 1.27]]]]])
            else:
                sch.append(["label", Q(net), ["at", ex, ey, angle],
                            ["effects", ["font", ["size", 1.27, 1.27]], ["justify"] + just + ["bottom"]],
                            ["uuid", uid(proj, "l", p.ref, num)]])
    sch.append(["sheet_instances", ["path", Q("/"), ["page", Q("1")]]]) if False else None
    sch.append(["embedded_fonts", "no"])
    return sch


def _get_prop(sym, name):
    for p in find_all(sym, "property"):
        if p[1] == name:
            return str(p[2])
    return ""

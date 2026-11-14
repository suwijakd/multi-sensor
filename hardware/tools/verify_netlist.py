#!/usr/bin/env python3
"""Cross-check a KiCad-exported netlist against the design in gen_schematic.py.

    kicad-cli sch export netlist --format kicadsexpr -o wearable.net hardware/kicad/wearable.kicad_sch
    python hardware/tools/verify_netlist.py wearable.net

Fails if any pin lands on a different net than the design says, if a designed
connection is missing, or if KiCad merged two designed nets.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import gen_schematic as G  # noqa: E402
from kicadgen import Libraries, resolve_pins, symbol_units  # noqa: E402
from sexpr import find, find_all, parse  # noqa: E402


def main(netfile):
    root = parse(open(netfile, encoding="utf-8").read())
    actual = {}  # (ref, pin) -> net name
    for net in find_all(find(root, "nets"), "net"):
        name = str(find(net, "name")[1]).lstrip("/").split("/")[-1]
        for node in find_all(net, "node"):
            ref = str(find(node, "ref")[1])
            pin = str(find(node, "pin")[1])
            actual[(ref, pin)] = name

    libs = Libraries(G.KICAD_SYMBOLS, {"wearable": os.path.join(G.OUT, "wearable.kicad_sym")})
    errors = []
    designed_nets = {}
    for part in G.d.parts:
        if part.ref.startswith("#"):
            continue
        nets, nc = resolve_pins(part, symbol_units(libs.symbol(part.lib_id)))
        for pin, net in nets.items():
            designed_nets.setdefault(net, set()).add((part.ref, pin))
            got = actual.get((part.ref, pin))
            if got is None:
                errors.append("%s.%s: designed on %s but missing from netlist" % (part.ref, pin, net))
            elif got != net:
                errors.append("%s.%s: designed %s, netlist has %s" % (part.ref, pin, net, got))
        for pin in nc:
            got = actual.get((part.ref, pin))
            if got and not got.startswith("unconnected-"):
                errors.append("%s.%s: designed NC, netlist has %s" % (part.ref, pin, got))

    # each actual net must correspond to exactly one designed net
    by_actual = {}
    for (ref, pin), name in actual.items():
        by_actual.setdefault(name, set()).add((ref, pin))
    for name, members in by_actual.items():
        if name.startswith("unconnected-"):
            continue
        want = designed_nets.get(name, set())
        extra = {m for m in members if m not in want and not m[0].startswith("#")}
        if extra:
            errors.append("net %s has unexpected pins %s" % (name, sorted(extra)))

    print("designed nets: %d, netlist nets: %d, pins checked: %d"
          % (len(designed_nets), len([n for n in by_actual if not n.startswith("unconnected-")]),
             sum(len(v) for v in designed_nets.values())))
    for e in errors:
        print("ERROR", e)
    print("OK" if not errors else "%d errors" % len(errors))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))

#!/usr/bin/env python3
"""Export manufacturing files for the rev A board into hardware/fab/.

    python hardware/tools/export_fab.py

Runs KiCad's DRC first and refuses to export if it reports any violation or
unconnected net. Writes Gerbers + drill (zipped for upload), a component
placement file and a BOM in the column layout JLCPCB's assembly service reads,
board renders, a STEP model and the schematic PDF.
"""
import csv
import json
import os
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
HW = os.path.normpath(os.path.join(HERE, ".."))
KICAD = os.path.join(HW, "kicad")
PCB = os.path.join(KICAD, "wearable.kicad_pcb")
SCH = os.path.join(KICAD, "wearable.kicad_sch")
FAB = os.path.join(HW, "fab")
CLI = os.environ.get("KICAD_CLI", r"C:\Users\nutty\AppData\Local\Programs\KiCad\10.0\bin\kicad-cli.exe")
LAYERS = "F.Cu,In1.Cu,In2.Cu,B.Cu,F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts"


def run(*args):
    r = subprocess.run([CLI] + list(args), capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:], r.stderr[-2000:])
        raise SystemExit("kicad-cli failed: " + " ".join(args[:3]))
    return r.stdout


def main():
    os.makedirs(FAB, exist_ok=True)
    drc = os.path.join(FAB, "drc.json")
    run("pcb", "drc", "--format", "json", "--severity-all", "--schematic-parity", "-o", drc, PCB)
    with open(drc) as f:
        rep = json.load(f)
    counts = (len(rep.get("violations", [])), len(rep.get("unconnected_items", [])), len(rep.get("schematic_parity", [])))
    print("DRC: %d violations, %d unconnected, %d schematic parity issues" % counts)
    if any(counts):
        raise SystemExit("DRC is not clean; not exporting")

    gerb = os.path.join(FAB, "gerbers")
    shutil.rmtree(gerb, ignore_errors=True)
    os.makedirs(gerb)
    run("pcb", "export", "gerbers", "--layers", LAYERS, "--subtract-soldermask", "--no-protel-ext", "-o", gerb, PCB)
    run("pcb", "export", "drill", "--format", "excellon", "--excellon-units", "mm", "--excellon-zeros-format",
        "decimal", "--excellon-separate-th", "--generate-map", "--map-format", "pdf", "-o", gerb + os.sep, PCB)
    zpath = os.path.join(FAB, "wearable_revA_gerbers.zip")
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for name in sorted(os.listdir(gerb)):
            if not name.endswith(".pdf"):
                z.write(os.path.join(gerb, name), name)
    print("gerbers:", len(os.listdir(gerb)), "files ->", os.path.basename(zpath))

    # placement file, converted to JLCPCB's column names
    raw = os.path.join(FAB, "pos_raw.csv")
    run("pcb", "export", "pos", "--format", "csv", "--units", "mm", "--side", "both", "--exclude-dnp", "-o", raw, PCB)
    with open(raw, newline="") as f:
        rows = list(csv.DictReader(f))
    os.remove(raw)
    with open(os.path.join(FAB, "wearable_revA_cpl.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["Designator", "Val", "Package", "Mid X", "Mid Y", "Rotation", "Layer"])
        for r in rows:
            w.writerow([r["Ref"], r["Val"], r["Package"], r["PosX"], r["PosY"], r["Rot"], r["Side"]])
    print("placement: %d parts (%d top, %d bottom)" % (
        len(rows), sum(r["Side"] == "top" for r in rows), sum(r["Side"] == "bottom" for r in rows)))

    bom = os.path.join(FAB, "wearable_revA_bom.csv")
    run("sch", "export", "bom", "--fields", "Value,Reference,Footprint,LCSC,MPN,Manufacturer,${QUANTITY}",
        "--labels", "Comment,Designator,Footprint,LCSC Part #,MPN,Manufacturer,Qty",
        "--group-by", "Value,Footprint,MPN", "--ref-range-delimiter", "", "--exclude-dnp", "-o", bom, SCH)
    with open(bom, newline="") as f:
        lines = list(csv.DictReader(f))
    missing = sum(1 for line in lines if not line["LCSC Part #"])
    print("BOM: %d lines, %d still without an LCSC part number" % (len(lines), missing))

    run("sch", "export", "pdf", "-o", os.path.join(FAB, "wearable_revA_schematic.pdf"), SCH)
    for side in ("top", "bottom"):
        run("pcb", "render", "--side", side, "--width", "1400", "--height", "1500", "--quality", "basic",
            "-o", os.path.join(FAB, "board_%s.png" % side), PCB)
    try:
        run("pcb", "export", "step", "--subst-models", "--force", "-o", os.path.join(FAB, "wearable_revA_board.step"), PCB)
    except SystemExit as e:
        print("STEP export skipped:", e)
    print("wrote", FAB)


if __name__ == "__main__":
    sys.exit(main())

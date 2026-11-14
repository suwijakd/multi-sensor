#!/usr/bin/env python3
"""Render preview images of the case and the board stack (hardware/case/case_preview.png).

    python hardware/tools/preview_case.py

Uses a small z-buffer rasteriser so hidden surfaces are handled correctly.
"""
import os
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gen_case as C  # noqa: E402

CASE, LID = "#3f73ad", "#6a9bd0"


def tris(m, dz=0.0):
    mesh = m.to_mesh()
    v = np.asarray(mesh.vert_properties)[:, :3].astype(float).copy()
    v[:, 2] += dz
    return v[np.asarray(mesh.tri_verts)]


def part_color(ref):
    if ref == "PCB":
        return "#2e7d4f"
    if ref == "BATTERY":
        return "#c2c6cc"
    if ref[0] == "U":
        return "#2b2e33"
    if ref[0] in "JE":
        return "#d8dade"
    if ref.startswith("SW"):
        return "#b0b4ba"
    return "#9a7a45"


def render(items, elev, azim, size=640):
    """items: list of (triangles[n,3,3], colour). Orthographic view, z-buffered."""
    a, e = np.radians(azim), np.radians(elev)
    rz = np.array([[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]])
    t = np.radians(90 - elev)
    rx = np.array([[1, 0, 0], [0, np.cos(t), -np.sin(t)], [0, np.sin(t), np.cos(t)]])
    rot = rx.T @ rz.T                     # world -> view; the camera looks along -z of the view frame
    light = np.array([-0.35, 0.45, 0.82])
    light /= np.linalg.norm(light)
    allv = np.vstack([(t3.reshape(-1, 3) @ rot.T) for t3, _ in items])
    lo, hi = allv.min(0), allv.max(0)
    span = max(hi[0] - lo[0], hi[1] - lo[1]) * 1.06
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    scale = size / span
    img = np.ones((size, size, 3))
    zbuf = np.full((size, size), -1e9)
    for t3, color in items:
        rgb = np.array(matplotlib.colors.to_rgb(color))
        v = t3 @ rot.T
        px = (v[:, :, 0] - cx) * scale + size / 2
        py = size / 2 - (v[:, :, 1] - cy) * scale
        pz = v[:, :, 2]
        n = np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])
        ln = np.linalg.norm(n, axis=1)
        ln[ln == 0] = 1
        shade = 0.38 + 0.62 * np.abs((n / ln[:, None]) @ light)
        for i in range(len(v)):
            x0, x1 = int(max(np.floor(px[i].min()), 0)), int(min(np.ceil(px[i].max()), size - 1))
            y0, y1 = int(max(np.floor(py[i].min()), 0)), int(min(np.ceil(py[i].max()), size - 1))
            if x1 < x0 or y1 < y0:
                continue
            xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            ax_, ay_, bx_, by_, cx_, cy_ = px[i, 0], py[i, 0], px[i, 1], py[i, 1], px[i, 2], py[i, 2]
            den = (by_ - cy_) * (ax_ - cx_) + (cx_ - bx_) * (ay_ - cy_)
            if abs(den) < 1e-9:
                continue
            w0 = ((by_ - cy_) * (xs - cx_) + (cx_ - bx_) * (ys - cy_)) / den
            w1 = ((cy_ - ay_) * (xs - cx_) + (ax_ - cx_) * (ys - cy_)) / den
            w2 = 1 - w0 - w1
            inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
            if not inside.any():
                continue
            z = w0 * pz[i, 0] + w1 * pz[i, 1] + w2 * pz[i, 2]
            sub = zbuf[y0:y1 + 1, x0:x1 + 1]
            hit = inside & (z > sub)
            sub[hit] = z[hit]
            img[y0:y1 + 1, x0:x1 + 1][hit] = rgb * shade[i]
    return img


def main():
    shell, top, solids, bad = C.main()
    board = [(tris(s), part_color(r)) for r, s in solids.items() if r != "BATTERY"]
    views = [
        ("Board in the bottom shell", [(tris(shell), CASE)] + board, 50, -60),
        ("Exploded: shell and board, battery, lid",
         [(tris(shell), CASE)] + board + [(tris(solids["BATTERY"], 9), part_color("BATTERY")), (tris(top, 20), LID)],
         22, -60),
        ("Closed case, top", [(tris(shell), CASE), (tris(top), LID)], 35, -60),
        ("Closed case, skin side", [(tris(shell), CASE), (tris(top), LID)] +
         [(tris(solids[r]), part_color(r)) for r in ("U7", "U9")], -50, -60),
        ("Lid from below", [(tris(top), LID)], -45, -60),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(15, 10.4), dpi=100)
    for ax, (title, items, elev, azim) in zip(axes.flat, views):
        ax.imshow(render(items, elev, azim))
        ax.set_title(title, fontsize=12)
        ax.set_axis_off()

    # cross-section through the PPG sensor, looking along the strap
    ax = axes.flat[5]
    y3 = C.H - C.BG.PPG_Y
    layers = [(shell, CASE), (top, LID)] + [(s, part_color(r)) for r, s in solids.items()]
    for m, color in layers:
        sec = m.rotate([90, 0, 0]).slice(y3)       # the rotation maps (x, y, z) to (x, -z, y)
        for poly in sec.to_polygons():
            p = np.asarray(poly)
            ax.fill(p[:, 0], -p[:, 1], color=color, linewidth=0)
    ax.set_aspect("equal")
    ax.set_title("Section through the PPG sensor (mm)", fontsize=12)
    ax.set_xlabel("across the board")
    ax.set_ylabel("height above skin")
    ax.grid(True, linewidth=0.3)
    fig.tight_layout()
    out = os.path.join(C.OUT, "case_preview.png")
    fig.savefig(out)
    print("wrote", out)


if __name__ == "__main__":
    main()

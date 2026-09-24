#!/usr/bin/env python
"""Build the energy-source icon sprite atlas for the viz map (dev-time only).

Draws one flat glyph per canonical energy_source (``viz.palette.ENERGY_COLORS``
keys, plus the cogeneration ``diesel`` slot) into a single sprite sheet used by
deck.gl's ``IconLayer``, and also writes each icon as its own PNG.

The glyphs are drawn **white on a transparent background** with near-black
inner details, so the atlas works with ``IconLayer(mask=True)``: deck.gl tints
the texture per point via ``get_color``, so one atlas serves every source in
the palette's colour.  The committed PNGs live under ``viz/icons/``; this
script is only needed when the artwork changes — the stack never runs it and
Pillow is *not* a runtime dependency.

Outputs (cell size ``--cell``, single row, ``SOURCE_LAYER_ORDER`` + diesel):
    viz/icons/source_icons.png     sprite atlas (N x 1 cells)
    viz/icons/<source>.png         per-icon PNGs
    viz/icons/manifest.json        source -> cell + file manifest

Needs Pillow (dev venv only):  .venv/bin/python scripts/build_icon_atlas.py
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from PIL import Image, ImageDraw

WHITE = (255, 255, 255, 255)
DARK = (32, 32, 32, 255)

# KEEP IN SYNC: viz.palette.SOURCE_LAYER_ORDER + the cogeneration diesel slot.
SOURCE_ICONS = ("storage", "wind", "solar", "hydro", "gas", "bio", "diesel")


def P(cell: int, x: float, y: float) -> tuple[int, int]:
    """Normalised (0..1) coordinates → integer pixel coordinates."""
    return round(x * cell), round(y * cell)


def _rot(cx: float, cy: float, px: float, py: float, deg: float) -> tuple[float, float]:
    """Rotate (px, py) around (cx, cy) by deg degrees."""
    rad = math.radians(deg)
    s, c = math.sin(rad), math.cos(rad)
    dx, dy = px - cx, py - cy
    return cx + dx * c - dy * s, cy + dx * s + dy * c


def _teardrop(d: ImageDraw.ImageDraw, cell: int, cx: float, cy: float, r: float, top: float) -> None:
    """Solid teardrop: apex (cx, top) flaring into a circle (cx, cy, r).

    Screen coordinates (y grows downward): the arc sweeps from the left-hand
    tangent point, over the circle's bottom (cy + r), to the right-hand one,
    keeping the widest part at the circle's lower edge.
    """
    phi = math.degrees(math.asin(max(-1.0, min(1.0, r / max(cy - top, 1e-9)))))
    pts = [P(cell, cx, top)]
    n = 16
    for i in range(n + 1):
        a = math.radians(90 + phi + (360 - 2 * phi) * i / n)
        pts.append(P(cell, cx + r * math.cos(a), cy - r * math.sin(a)))
    d.polygon(pts, fill=WHITE)


def _wind(d: ImageDraw.ImageDraw, cell: int) -> None:
    hub = (0.5, 0.40)
    d.line((P(cell, 0.5, 0.96), P(cell, hub[0], hub[1])), fill=WHITE, width=max(2, round(0.05 * cell)))
    for deg in (0, 120, 240):
        blade = [_rot(hub[0], hub[1], x, y, deg) for x, y in ((0.40, 0.36), (0.60, 0.36), (0.5, 0.05))]
        d.polygon([P(cell, x, y) for x, y in blade], fill=WHITE)
    d.rounded_rectangle(
        (P(cell, 0.40, 0.34), P(cell, 0.60, 0.46)),
        radius=round(0.02 * cell), outline=WHITE, width=max(2, round(0.035 * cell)),
    )
    r = round(0.05 * cell)
    d.ellipse((P(cell, hub[0] - 0.05, hub[1] - 0.05), P(cell, hub[0] + 0.05, hub[1] + 0.05)), fill=None)
    d.ellipse((round(hub[0] * cell) - r, round(hub[1] * cell) - r, round(hub[0] * cell) + r, round(hub[1] * cell) + r), fill=WHITE)


def _solar(d: ImageDraw.ImageDraw, cell: int) -> None:
    d.rounded_rectangle(
        (P(cell, 0.10, 0.38), P(cell, 0.90, 0.98)),
        radius=round(0.03 * cell), outline=WHITE, width=max(2, round(0.04 * cell)),
    )
    lw = max(2, round(0.03 * cell))
    for gy in (0.55, 0.72):
        d.line((P(cell, 0.14, gy), P(cell, 0.86, gy)), fill=WHITE, width=lw)
    d.line((P(cell, 0.5, 0.43), P(cell, 0.5, 0.93)), fill=WHITE, width=lw)
    # Small sun above-left of the panel.
    r = 0.05
    d.ellipse((P(cell, 0.84 - r, 0.16 - r), P(cell, 0.84 + r, 0.16 + r)), fill=WHITE)
    for i in range(8):
        a = math.radians(i * 45)
        x1, y1 = 0.84 + r * 1.15 * math.sin(a), 0.16 - r * 1.15 * math.cos(a)
        x2, y2 = 0.84 + r * 1.65 * math.sin(a), 0.16 - r * 1.65 * math.cos(a)
        d.line((P(cell, x1, y1), P(cell, x2, y2)), fill=WHITE, width=max(2, round(0.02 * cell)))


def _hydro(d: ImageDraw.ImageDraw, cell: int) -> None:
    _teardrop(d, cell, 0.5, 0.62, 0.30, 0.08)
    r = round(0.13 * cell)
    d.ellipse((round(0.5 * cell) - r, round(0.70 * cell) - r, round(0.5 * cell) + r, round(0.70 * cell) + r), fill=DARK)


def _bio(d: ImageDraw.ImageDraw, cell: int) -> None:
    d.line((P(cell, 0.5, 0.30), P(cell, 0.5, 0.95)), fill=WHITE, width=max(2, round(0.05 * cell)))
    # Rotated leaf ellipse with a dark centre vein along its long axis.
    pts = [_rot(0.5, 0.42, x, y, -45) for x, y in (
        (0.5 + 0.42 * math.cos(math.radians(t)), 0.42 + 0.20 * math.sin(math.radians(t)))
        for t in range(0, 360, 6)
    )]
    d.polygon([P(cell, x, y) for x, y in pts], fill=WHITE)
    v1 = _rot(0.5, 0.42, 0.5 + 0.34, 0.42, -45)
    v2 = _rot(0.5, 0.42, 0.5 - 0.34, 0.42, -45)
    d.line((P(cell, v1[0], v1[1]), P(cell, v2[0], v2[1])), fill=DARK, width=max(2, round(0.03 * cell)))


def _flame(d: ImageDraw.ImageDraw, cell: int) -> None:
    _teardrop(d, cell, 0.5, 0.62, 0.30, 0.10)
    _teardrop(d, cell, 0.5, 0.56, 0.12, 0.30)


def _diesel(d: ImageDraw.ImageDraw, cell: int) -> None:
    d.rounded_rectangle(
        (P(cell, 0.24, 0.20), P(cell, 0.76, 0.92)),
        radius=round(0.06 * cell), fill=WHITE,
    )
    lw = max(2, round(0.04 * cell))
    for gy in (0.38, 0.72):
        d.line((P(cell, 0.24, gy), P(cell, 0.76, gy)), fill=DARK, width=lw)
    r = round(0.07 * cell)
    d.ellipse((round(0.5 * cell) - r, round(0.55 * cell) - r, round(0.5 * cell) + r, round(0.55 * cell) + r), fill=DARK)


def _storage(d: ImageDraw.ImageDraw, cell: int) -> None:
    d.rounded_rectangle(
        (P(cell, 0.18, 0.32), P(cell, 0.82, 0.94)),
        radius=round(0.05 * cell), fill=WHITE,
    )
    d.rectangle((P(cell, 0.44, 0.20), P(cell, 0.56, 0.32)), fill=WHITE)
    bolt = [(0.56, 0.40), (0.43, 0.63), (0.51, 0.63), (0.44, 0.86), (0.59, 0.57), (0.50, 0.57)]
    d.polygon([P(cell, x, y) for x, y in bolt], fill=DARK)


DRAWERS = {
    "wind": _wind,
    "solar": _solar,
    "hydro": _hydro,
    "bio": _bio,
    "gas": _flame,
    "diesel": _diesel,
    "storage": _storage,
}


def draw_icon(source: str, cell: int) -> Image.Image:
    """One white-on-transparent cell for ``source`` at ``cell`` px."""
    img = Image.new("RGBA", (cell, cell), (0, 0, 0, 0))
    DRAWERS[source](ImageDraw.Draw(img), cell)
    return img


def build_atlas(sources: tuple[str, ...], cell: int) -> Image.Image:
    """Concatenate every source cell into a single-row sprite atlas."""
    cols = len(sources)
    atlas = Image.new("RGBA", (cols * cell, cell), (0, 0, 0, 0))
    for i, source in enumerate(sources):
        atlas.paste(draw_icon(source, cell), (i * cell, 0))
    return atlas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cell", type=int, default=256, help="icon cell size in px")
    parser.add_argument("--out", type=Path, default=Path("viz/icons"), help="output directory")
    args = parser.parse_args()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)

    atlas = build_atlas(SOURCE_ICONS, args.cell)
    atlas.save(out / "source_icons.png")

    manifest = {"cell": args.cell, "icons": {}}
    for i, source in enumerate(SOURCE_ICONS):
        draw_icon(source, args.cell).save(out / f"{source}.png")
        manifest["icons"][source] = {"col": i, "row": 0, "file": f"{source}.png"}

    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(SOURCE_ICONS)} icons to {out} (cell {args.cell}px):")
    for i, source in enumerate(SOURCE_ICONS):
        print(f"  [{i}] {source}")


if __name__ == "__main__":
    main()
#!/usr/bin/env python
"""Build the energy-source icon sprite atlas for the viz map (dev-time only).

Draws one flat glyph per canonical energy_source (``viz.palette.ENERGY_COLORS``
keys, plus the cogeneration ``diesel`` slot) into a single sprite sheet used by
deck.gl's ``IconLayer``, and also writes each icon as its own PNG.  The glyphs
are deliberately simple geometric shapes — square (bio), triangle (gas),
droplet (hydro), dot / scatter bullet (solar), 3-blade propeller (wind), diamond
(storage) — so they stay legible at map pixel-sizes.

The glyphs are drawn **white on a transparent background** (hydro keeps its
near-black water drop, the historic diesel logo keeps its details), so the
atlas works with ``IconLayer(mask=True)``: deck.gl tints the texture per point
via ``get_color``, so one atlas serves every source in the palette's colour.
The committed PNGs live under ``viz/icons/``; this script is only needed when
the artwork changes — the stack never runs it and Pillow is *not* a runtime
dependency.

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


def _wind_propeller(d: ImageDraw.ImageDraw, cell: int) -> None:
    # A 3-blade propeller: three swept blades 120° apart around a hub circle.
    # Each blade is a tapered quad leaning ~12° off its radial line, so the
    # rotor reads as spinning rather than as a static Y.
    step = 2 * math.pi / 3
    sweep = 0.22
    r0, r1 = 0.06, 0.40
    hw0, hw1 = 0.045, 0.085

    def pt(r: float, a: float, hw: float) -> tuple[int, int]:
        ox, oy = -math.sin(a) * hw, math.cos(a) * hw
        return P(cell, 0.5 + r * math.cos(a) + ox, 0.5 + r * math.sin(a) + oy)

    for i in range(3):
        a0 = -math.pi / 2 + i * step
        d.polygon(
            [pt(r0, a0, hw0), pt(r0, a0, -hw0), pt(r1, a0 + sweep, -hw1), pt(r1, a0 + sweep, hw1)],
            fill=WHITE,
        )
    r = round(0.10 * cell)
    d.ellipse((round(0.5 * cell) - r, round(0.5 * cell) - r, round(0.5 * cell) + r, round(0.5 * cell) + r), fill=WHITE)


def _solar_bullet(d: ImageDraw.ImageDraw, cell: int) -> None:
    r = 0.312
    d.ellipse((P(cell, 0.5 - r, 0.5 - r), P(cell, 0.5 + r, 0.5 + r)), fill=WHITE)


def _hydro(d: ImageDraw.ImageDraw, cell: int) -> None:
    _teardrop(d, cell, 0.5, 0.62, 0.30, 0.08)
    r = round(0.13 * cell)
    d.ellipse((round(0.5 * cell) - r, round(0.70 * cell) - r, round(0.5 * cell) + r, round(0.70 * cell) + r), fill=DARK)


def _bio_square(d: ImageDraw.ImageDraw, cell: int) -> None:
    d.rectangle((P(cell, 0.24, 0.24), P(cell, 0.76, 0.76)), fill=WHITE)


def _gas_triangle(d: ImageDraw.ImageDraw, cell: int) -> None:
    d.polygon([P(cell, x, y) for x, y in ((0.5, 0.22), (0.20, 0.78), (0.80, 0.78))], fill=WHITE)


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


def _storage_diamond(d: ImageDraw.ImageDraw, cell: int) -> None:
    h = 0.36
    d.polygon([P(cell, x, y) for x, y in ((0.5, 0.5 - h), (0.5 + h, 0.5), (0.5, 0.5 + h), (0.5 - h, 0.5))], fill=WHITE)


DRAWERS = {
    "wind": _wind_propeller,
    "solar": _solar_bullet,
    "hydro": _hydro,
    "bio": _bio_square,
    "gas": _gas_triangle,
    "diesel": _diesel,
    "storage": _storage_diamond,
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
"""Colorbar overlay for the choropleth map (issue #26).
Pure HTML/CSS seam: `colorbar_html` turns the area-capacity ramp's top value
into a self-contained overlay div — a vertical gradient bar painted with the
same `RAMP_LOW` → `RAMP_HIGH` colors the area fills use, with scale ticks
marked along it at rounded capacity levels and a bare "MW" caption above.  The
ramp interpolates capacity linearly (t = capacity / max), so a tick sits at
the height its level occupies on the ramp, and the levels split the range into
five bins: four equal bins of a step ``s`` (``max / BIN_COUNT`` truncated to
two significant digits, so ``s`` lands near a fifth of the max) plus a top bin
(max − 4s) never smaller than one step — usually the biggest.  Tick labels are
rounded to one decimal digit, the top one the max itself.  The label unit
tracks the range: under a gigawatt, plain MW (e.g. "500.0" with a "Capacity
(MW)" caption); at a gigawatt and above, GW — so 62,490.1 MW reads as 62.5
GW.  The overlay is positioned `fixed` over
the map's right edge with a high
`z-index`, floats above the deck rather than pushing the layout, and
`pointer-events: none` keeps the map interactive underneath.  No database
access, so the seam is unit-testable on a plain number.
"""

from __future__ import annotations

import math

from viz.choropleth import RAMP_HIGH, RAMP_LOW
from viz.config import MAP_HEIGHT

# Vertical bar height: the map window is MAP_HEIGHT px tall, minus the header
# strip and top/bottom labels.  Approximate is fine — the bar just floats over
# the map's right edge.
BAR_HEIGHT_PX = 520

# The five-bin split: four equal bins of a nice step size plus a top bin.
# The step fits a fifth of the max, so 4 equal bins leave the top bin
# (max − 4s) at least one step wide — the top bin is never the smallest.
BIN_COUNT = 5

# The vertical extent of everything above the map (Streamlit's page-top
# padding + the header strip), so the bar's center tracks the map window's
# center as the window grows.
HEADER_STRIP_PX = 64

# The overlay's position: its vertical center sits on the map window's center
# (header strip + half the map height), then half the bar height moves it up;
# horizontally it is tucked in from the right edge of the wide-layout column
# the map fills.
TOP_PX = int(HEADER_STRIP_PX + MAP_HEIGHT / 2 - BAR_HEIGHT_PX / 2)
RIGHT_PX = 16


def _rgba(color: tuple[int, int, int, int]) -> str:
    """rgba CSS string for a palette color tuple."""
    r, g, b, a = color
    return f"rgba({r}, {g}, {b}, {a / 255:.2f})"


def _nice_step(upper: float) -> float:
    """Largest ≤ ``upper`` value with at most two significant digits.

    Truncating to two significant digits (12,400 → 12,000; 45,972 → 45,000)
    keeps the equal step near ``max / BIN_COUNT``, so the marks land at
    roughly even percentages (~20/40/60/80/100 of the max) instead of
    bunching up at the low end.
    """
    if upper <= 0:
        return 1.0
    base = 10.0 ** (math.floor(math.log10(upper)) - 1)
    return math.floor(upper / base) * base


def capacity_ticks(capacity_max_mw: float) -> tuple[tuple[float, float], ...]:
    """(fraction, capacity) scale marks splitting ``capacity_max_mw`` in five.

    The equal step ``s`` is ``max / BIN_COUNT`` truncated to two significant
    digits, so the first four bins are exactly ``s`` wide and the top bin
    (``4s``…``max``) is not smaller than ``s`` — usually wider.  Fractions are
    the levels' positions on the linear ramp.
    """
    step = _nice_step(capacity_max_mw / BIN_COUNT)
    levels = (0.0, step, 2 * step, 3 * step, 4 * step, capacity_max_mw)
    return tuple((level / capacity_max_mw, level) for level in levels)


def colorbar_html(capacity_max_mw: float) -> str:
    """Overlay div tinted with the area-capacity ramp, scale-marked in four.

    ``capacity_max_mw`` is the largest area fill across the displayed scope
    (the ramp's high end); the gradient runs `RAMP_LOW` (bottom, small
    capacity) → `RAMP_HIGH` (top, ``capacity_max_mw``), matching the
    interpolation `viz.choropleth.fill_color` applies.  Each `capacity_ticks`
    level gets a tick label rounded to one decimal digit at its position on
    the bar — the top one the max itself.  The label unit follows the range:
    under a gigawatt (``capacity_max_mw < 1000``) the marks are plain MW and
    the caption is "Capacity (MW)"; at or above it they are GW (MW ÷ 1000)
    and the caption is "Capacity (GW)".
    """
    low = _rgba(RAMP_LOW)
    high = _rgba(RAMP_HIGH)
    # Marks 1000 MW and up are labeled in GW (MW ÷ 1000), one decimal digit,
    # so state-sized capacities read as compact values — e.g. 62,490.1 MW →
    # 62.5 — instead of long thousand-separated strings; sub-GW ranges keep
    # plain MW labels.
    scale = 1000.0 if capacity_max_mw >= 1000.0 else 1.0
    unit = "GW" if scale == 1000.0 else "MW"
    ticks = "".join(
        f"<span class='viz-colorbar-tick' style='bottom:{fraction * 100:.0f}%'>"
        f"<span class='viz-tick-label'>{level / scale:,.1f}</span></span>"
        for fraction, level in capacity_ticks(capacity_max_mw)
    )
    return (
        "<div class='viz-colorbar'>"
        f"<span class='viz-colorbar-caption'>Capacity ({unit})</span>"
        "<div class='viz-colorbar-bar-wrap'>"
        "<span class='viz-colorbar-track'></span>"
        f"{ticks}"
        "</div>"
        "</div>"
        "<style>"
        ".viz-colorbar{position:fixed;right:" + str(RIGHT_PX) + "px;top:"
        + str(TOP_PX) + "px;z-index:999;display:flex;flex-direction:column;"
        "align-items:center;gap:4px;pointer-events:none;font:600 0.72rem "
        "ui-sans-serif,system-ui,sans-serif;color:#37474f;background:"
        "rgba(255,255,255,0.85);padding:6px 7px;border-radius:6px;box-shadow:"
        "0 1px 4px rgba(0,0,0,.18)}"
        ".viz-colorbar-caption{color:#5f6368;font-weight:500}"
        ".viz-colorbar-bar-wrap{position:relative}"
        f".viz-colorbar-track{{display:block;width:0.8rem;height:{BAR_HEIGHT_PX}px;"
        "border-radius:3px;border:1px solid rgba(90,100,112,.35);"
        f"background:linear-gradient(to top,{low},{high})}}"
        ".viz-colorbar-tick{position:absolute;left:0;right:0;border-top:"
        "1px solid rgba(38,50,56,.35)}"
        ".viz-tick-label{position:absolute;left:0;top:50%;transform:"
        "translate(-100%,-50%) translateX(-7px);white-space:nowrap;"
        "color:#37474f}"
        "</style>"
    )
"""Live header aggregate formatting for the Streamlit viz app (issue #25).

Pure formatting seams for the header above the map: the scope title (level +
displayed-area count, or the single area's name, e.g. "Region Berlin") and
the three figures — installed capacity (MW), active-unit count and area
(km²).  No database access, so the module is unit-testable on plain numbers,
mirroring the `viz.tooltip` seam split: values come from `viz.data`, the
rendered strings from here.
"""

from __future__ import annotations

# Singular display prefix per chooser level, for the single-area header:
# level "Regions" + area "Berlin" → "Region Berlin".  The country level (0)
# sits outside this map: its single displayed area is the country itself, so
# its name ("Germany") is used bare.
SINGULAR_LEVEL_PREFIX = {
    "Regions": "Region",
    "Districts": "District",
    "Municipalities": "Municipality",
}


def format_mw(capacity_mw: float) -> str:
    """MW total as an integer thousands-separated string, e.g. 12345.6 → "12,346"."""
    return f"{capacity_mw:,.0f}"


def format_unit_count(unit_count: int) -> str:
    """Active-unit count thousands-separated, e.g. 543210 → "543,210"."""
    return f"{unit_count:,}"


def format_area_km2(area_km2: float) -> str:
    """Area total as integer km² thousands-separated, e.g. 357588.4 → "357,588"."""
    return f"{area_km2:,.0f}"


def single_area_title(level_label: str, area_name: str) -> str:
    """Scope title when exactly one area is displayed.

    e.g. ``"Region Berlin"`` at level "Regions"; the country level's single
    area is the country itself, so the bare name (``"Germany"``) is returned.
    """
    prefix = SINGULAR_LEVEL_PREFIX.get(level_label)
    return f"{prefix} {area_name}" if prefix else area_name


def scope_title(
    level_label: str, area_count: int, area_name: str | None = None
) -> str:
    """Scope line of the header: the single area's name, else ``level · N areas``."""
    if area_count == 1 and area_name:
        return single_area_title(level_label, area_name)
    return f"{level_label} · {area_count:,} areas"

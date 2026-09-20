"""Live header aggregate formatting for the Streamlit viz app (issue #25).

Pure formatting seams for the header above the map: the scope title (level +
displayed-area count, or the single area's name, e.g. "Region Berlin") and
the three figures — installed capacity (MW), active-unit count and area
(km²).  No database access, so the module is unit-testable on plain numbers,
mirroring the `viz.tooltip` seam split: values come from `viz.data` (the unit
frame and boundary rows), the derived scope figures from `areas_summary`,
the rendered strings from here.
"""

from __future__ import annotations

from typing import Any, Mapping

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


def areas_summary(
    boundary_rows: list[Mapping[str, Any]], names: tuple[str, ...] | None = None
) -> dict[str, Any]:
    """Header scope figures over boundary rows: count, km² sum, single name.

    ``boundary_rows`` are the render-opt `optimized_boundaries` rows
    (``{name, area, geojson}``).  ``names`` narrows the displayed areas
    (issue #26); None means every area at the level.  The name is attached
    only when exactly one area is displayed, so multi-area levels never fetch
    extra rows — the header scope and the choropleth share the same frame.
    """
    if names is None:
        rows = boundary_rows
    else:
        name_set = frozenset(names)
        rows = [row for row in boundary_rows if row["name"] in name_set]
    summary: dict[str, Any] = {
        "area_count": len(rows),
        "total_area_km2": sum(r["area"] for r in rows),
    }
    if summary["area_count"] == 1:
        summary["area_name"] = rows[0]["name"]
    return summary
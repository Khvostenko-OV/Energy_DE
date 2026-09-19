"""Choropleth seam for the Streamlit viz app (issue #26).

Pure building blocks for the area fill layer: `fill_color` maps an area's
live capacity to the rgba fill of its polygon (a pale-blue → vivid-blue ramp,
zero capacity → a translucent neutral), and `areas_feature_collection` turns
the boundary rows (name + ``ST_AsGeoJSON`` text) and fill rows (per-area
capacity/unit count) the app fetched into the GeoJSON FeatureCollection the
GeoJsonLayer renders, joined by area name.  No database access, so the module
is unit-testable on synthetic rows.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from viz.tooltip import area_card

# Fill for a displayed area with no live capacity: a faint neutral, so the
# polygon stays visible (outlined) but clearly uncolored.
ZERO_FILL = (241, 243, 246, 150)

# Ramp bounds, low end (pale, translucent) → high end (vivid, opaque).  The
# max-capacity area across the current selection paints the high end; every
# other area interpolates linearly toward it.
RAMP_LOW = (207, 216, 230, 160)
RAMP_HIGH = (33, 150, 243, 255)


def _mix(low: tuple[int, int, int, int], high: tuple[int, int, int, int], t: float):
    return tuple(round(lo + (hi - lo) * t) for lo, hi in zip(low, high))


def fill_color(capacity_mw: float, capacity_max: float) -> tuple[int, int, int, int]:
    """rgba fill for one area's live capacity (MW).

    ``capacity_max`` is the max across the displayed areas; the biggest area
    paints the ramp's high end, smaller ones interpolate down, zero capacity
    (or a degenerate/absent ``capacity_max``) paints `ZERO_FILL`.
    """
    if capacity_max is None or capacity_max <= 0 or capacity_mw <= 0:
        return ZERO_FILL
    t = min(capacity_mw / capacity_max, 1.0)
    return _mix(RAMP_LOW, RAMP_HIGH, t)


def areas_feature_collection(
    boundary_rows: list[Mapping[str, Any]],
    fill_rows: list[Mapping[str, Any]],
) -> dict[str, Any]:
    """GeoJSON FeatureCollection for the choropleth, joined by area name.

    ``boundary_rows`` are ``{name, geojson}`` (``geojson`` = ``ST_AsGeoJSON``
    text) and ``fill_rows`` ``{name, capacity_mw, unit_count}`` — the two
    query seams of `viz.data`.  Every feature carries the area name, the
    capacity/unit-count values, the capacity-based rgba fill, and the two
    prebuilt hover-card fields (`source_header`/`unit_body`, via
    `area_card`) so the single deck tooltip serves units and areas.

    An area with no fill row — no active unit falls inside it at the active
    level — renders the zero fill; a fill row with no matching boundary (the
    selection caught a stale name) is dropped; feature order follows the
    boundary rows.
    """
    capacity_max = max((row["capacity_mw"] for row in fill_rows), default=0.0)
    fill_by_name = {row["name"]: row for row in fill_rows}
    features: list[dict[str, Any]] = []
    for row in boundary_rows:
        fill = fill_by_name.get(row["name"], {"capacity_mw": 0.0, "unit_count": 0})
        capacity_mw = fill["capacity_mw"]
        properties: dict[str, Any] = {
            "name": row["name"],
            "capacity_mw": capacity_mw,
            "unit_count": fill["unit_count"],
            "fill_color": fill_color(capacity_mw, capacity_max),
        }
        properties.update(area_card(row["name"], capacity_mw, fill["unit_count"]))
        features.append(
            {
                "type": "Feature",
                "geometry": json.loads(row["geojson"]),
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}

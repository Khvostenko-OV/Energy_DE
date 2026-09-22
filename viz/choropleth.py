"""Choropleth seam for the Streamlit viz app (issue #26, render-opt).

Pure building blocks for the area fill layer: `fill_color` maps an area's
live capacity to the rgba fill of its polygon (a pale-blue → vivid-blue ramp,
zero capacity → a translucent neutral), and `areas_feature_collection` turns
the boundary rows (name + km² area + ``ST_AsGeoJSON`` text) and fill rows
(per-area capacity/unit count) the app fetched into the GeoJSON
FeatureCollection the GeoJsonLayer renders, joined by area name.

`area_fills` is the render-opt replacement for the retired spatial-join fill
query (`ST_Intersects` in `viz.data`): it aggregates the unit frame by the
``name`` column (`area_column AS name` from the fetch) into per-area capacity
(MW) and unit count — a pandas groupby instead of a PostGIS spatial join, so
no geometry is ever compared.  No database access anywhere, so the module is
unit-testable on synthetic rows.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

import pandas as pd

from viz.tooltip import area_card

# Fill for a displayed area with no live capacity: a faint neutral, so the
# polygon stays visible (outlined) but clearly uncolored.
ZERO_FILL = (241, 243, 246, 150)

# Fill for an area outside the displayed selection: fully transparent, so the
# outline-only "context" polygons (the whole level) contribute nothing to the
# choropleth while their borders stay visible (render-opt).
TRANSPARENT_FILL = (0, 0, 0, 0)

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


def area_fills(units: pd.DataFrame) -> list[dict[str, Any]]:
    """Per-area capacity (MW) and unit count from the active-unit frame.

    The render-opt choropleth feed: `fetch_units` broadcasts each unit's
    active-level area attribute as ``name``, so this groups by that name and
    aggregates installed capacity ÷ 1000 → MW and the row count.  No spatial
    join — the frame IS the predicate-filtered active set, and the groupby
    drops units without an area attribute (offshore / no polygon at the
    level), so the fills reconcile with the header and scatter by construction.

    A frame without a ``name`` column (country level, render-opt) — or an
    empty frame — yields no fill rows.
    """
    if "name" not in units.columns or units.empty:
        return []
    grouped = units.groupby("name")["installed_capacity"].agg(["sum", "count"])
    return [
        {
            "name": name,
            "capacity_mw": float(row["sum"]) / 1000.0,
            "unit_count": int(row["count"]),
        }
        for name, row in grouped.iterrows()
    ]


def areas_feature_collection(
    boundary_rows: list[Mapping[str, Any]],
    fill_rows: list[Mapping[str, Any]],
    *,
    selected_names: tuple[str, ...] | None = None,
    pre_parsed_geometry: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """GeoJSON FeatureCollection for the choropleth, joined by area name.

    ``boundary_rows`` are ``{name, area, geojson}`` (``geojson`` =
    pre-simplified ``ST_AsGeoJSON`` text from `service.boundaries`) and
    ``fill_rows`` ``{name, capacity_mw, unit_count}`` — the `area_fills`
    output.  Every feature carries the area name, the capacity/unit-count
    values, the capacity-based rgba fill, and the two prebuilt hover-card
    fields (`source_header`/`unit_body`, via `area_card`) so the single deck
    tooltip serves units and areas.

    ``pre_parsed_geometry`` maps area name → parsed geometry dict; a row whose
    entry is present skips the per-row ``json.loads`` (issue #31: the app
    caches the parsed geometries per level).  A row without an entry falls
    back to parsing its ``geojson`` text (the seam's default).

    The layer outlines **every** boundary at the level and fills only the
    ``selected_names`` display scope (render-opt): unselected areas paint the
    transparent fill and a name-only hover card, selected ones the capacity
    ramp and capacity/count card.  ``selected_names``=None means the whole
    level is the display selection (all filled).

    An area with no fill row — no active unit names it at the active level —
    renders the zero fill; a fill row with no matching boundary (a stale
    name) is dropped; feature order follows the boundary rows.
    """
    capacity_max = max((row["capacity_mw"] for row in fill_rows), default=0.0)
    fill_by_name = {row["name"]: row for row in fill_rows}
    selected = (
        None
        if selected_names is None
        else frozenset(selected_names)  # type: ignore[arg-type]
    )
    features: list[dict[str, Any]] = []
    for row in boundary_rows:
        name = row["name"]
        is_selected = selected is None or name in selected
        fill = fill_by_name.get(name, {"capacity_mw": 0.0, "unit_count": 0})
        capacity_mw = fill["capacity_mw"]
        if is_selected:
            fill_rgba = fill_color(capacity_mw, capacity_max)
        else:
            fill_rgba = TRANSPARENT_FILL
        properties: dict[str, Any] = {
            "name": name,
            "capacity_mw": capacity_mw,
            "unit_count": fill["unit_count"],
            "fill_color": fill_rgba,
        }
        properties.update(
            area_card(name, capacity_mw, fill["unit_count"], selected=is_selected)
        )
        if pre_parsed_geometry and name in pre_parsed_geometry:
            geometry: dict[str, Any] = pre_parsed_geometry[name]
        else:
            geometry = json.loads(row["geojson"])
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": properties,
            }
        )
    return {"type": "FeatureCollection", "features": features}
"""Viewport/camera seams for the Streamlit viz app (issue #26).

Pure math around the map camera: `geometry_points` flattens a GeoJSON
Polygon/MultiPolygon geometry into (lon, lat) pairs, `fit_viewstate` reduces a
point cloud (the selected areas' boundaries) to the (lon, lat, zoom) view that
shows their whole bounding box, and `should_refit` decides when that fitted
view must replace the stored camera — level or area selection changed, or
nothing stored yet — versus when the stored camera must be preserved across
reruns (source/timescope changes), so the user's own framing survives.  No
database and no deck involved; the app composes these with the choropleth
features for the session-state camera.
"""

from __future__ import annotations

import math

from viz.config import GERMANY_CENTER, INITIAL_ZOOM, MAP_HEIGHT

# Viewport-fit tuning: a nominal map-window size, the padding fraction around
# the selected areas' bounding box, and the zoom clamp around the fit.
FIT_WIDTH_PX = 1000.0
FIT_HEIGHT_PX = float(MAP_HEIGHT)
FIT_PADDING = 0.12
MIN_FIT_ZOOM = 3.0
MAX_FIT_ZOOM = 13.0

_TILE_SIZE = 256.0
_WORLD_LON_SPAN = 360.0
_WORLD_MERCATOR_SPAN = 2.0 * math.pi
_MERCATOR_LAT_LIMIT = 85.0511


def geometry_points(geometry: dict) -> list[tuple[float, float]]:
    """(lon, lat) pairs of a GeoJSON Polygon/MultiPolygon geometry.

    Every ring flattens into its raw points (elevation coordinates drop the
    altitude); anything that is not a Polygon/MultiPolygon yields nothing, so
    an unexpected geometry type is silently ignored rather than crashing the
    fit.
    """
    coords = geometry.get("coordinates", [])
    if geometry.get("type") == "Polygon":
        rings = coords
    elif geometry.get("type") == "MultiPolygon":
        rings = (ring for polygon in coords for ring in polygon)
    else:
        return []
    return [(lon, lat) for ring in rings for lon, lat, *_ in ring]


def _mercator_y(lat_deg: float) -> float:
    """Web-Mercator Y (in radians, ≈ [-π, π]) for a latitude in degrees."""
    lat_deg = max(min(lat_deg, _MERCATOR_LAT_LIMIT), -_MERCATOR_LAT_LIMIT)
    return math.log(math.tan(math.pi / 4 + math.radians(lat_deg) / 2))


def fit_viewstate(
    points: list[tuple[float, float]],
    *,
    width: float = FIT_WIDTH_PX,
    height: float = FIT_HEIGHT_PX,
    padding: float = FIT_PADDING,
) -> dict[str, float]:
    """(``lon``, ``lat``, ``zoom``) showing every ``points``' bounding box.

    Empty input falls back to the Germany overview; a single point keeps its
    center and zooms to `MAX_FIT_ZOOM`.  The zoom fits both spans: it takes the
    smaller of the lat/lon-fitted zoom candidates (so neither axis clips),
    clamped to ``[MIN_FIT_ZOOM, MAX_FIT_ZOOM]``.  A zero-span strip (a row or
    column of points sharing a latitude or longitude) lets the other axis
    decide instead of dividing by zero.
    """
    if not points:
        return {
            "lon": GERMANY_CENTER["lon"],
            "lat": GERMANY_CENTER["lat"],
            "zoom": INITIAL_ZOOM,
        }
    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    lon = (min(lons) + max(lons)) / 2.0
    lat = (min(lats) + max(lats)) / 2.0
    lon_span = (max(lons) - min(lons)) * (1 + padding)
    mercator_span = (_mercator_y(max(lats)) - _mercator_y(min(lats))) * (1 + padding)
    if lon_span <= 1e-9 and mercator_span <= 1e-9:
        return {"lon": lon, "lat": lat, "zoom": MAX_FIT_ZOOM}
    zoom_candidates = []
    if lon_span > 1e-9:
        zoom_candidates.append(
            math.log2(width * _WORLD_LON_SPAN / (lon_span * _TILE_SIZE))
        )
    if mercator_span > 1e-9:
        zoom_candidates.append(
            math.log2(height * _WORLD_MERCATOR_SPAN / (mercator_span * _TILE_SIZE))
        )
    zoom = min(zoom_candidates)
    zoom = min(max(zoom, MIN_FIT_ZOOM), MAX_FIT_ZOOM)
    return {"lon": lon, "lat": lat, "zoom": round(zoom, 1)}


def should_refit(
    stored_view: dict | None,
    stored_scope: tuple | None,
    *,
    level_label: str,
    area_names: tuple[str, ...] | list[str],
) -> bool:
    """Whether the stored camera must be replaced before this rerun.

    True when no camera is stored yet or the scope — (level, sorted area
    names) — differs from the one the stored camera was fitted to; False
    otherwise, so a source/timescope rerun over the same scope preserves the
    user's camera.
    """
    if not stored_view:
        return True
    scope = (level_label, tuple(sorted(area_names)))
    return scope != stored_scope

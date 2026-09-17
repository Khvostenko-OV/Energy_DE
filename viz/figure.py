"""Figure builder for the Dash scatter map (issue #18).

Turns the data layer's query results (pandas DataFrames for generators and
storages) into a `plotly.graph_objects.Figure` carrying one `scattermap`
trace per energy source with WebGL point clustering, the open-street-map
(MapLibre) basemap, and the shared curated palette — colors from
`viz.palette.ENERGY_COLORS`.  All traces render as circle markers (the only
symbol MapLibre's scattermap tint with `marker.color`); storages are
distinguished by their dark-brown palette color.  This module is pure: no
database access, so the builder is unit-testable on synthetic frames.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from viz.drill import drill_value
from viz.palette import (
    CHOROPLETH_COLORSCALE,
    DEFAULT_COLOR,
    ENERGY_COLORS,
    MARKER_SYMBOL,
    SOURCE_LAYER_ORDER,
)

# Initial camera: center on Germany, zoomed to the country overview.
GERMANY_CENTER = {"lat": 51.16, "lon": 10.45}
INITIAL_ZOOM = 5.5

# Camera zoom per drill level: the deeper the level, the tighter the framing
# so a drilled-to region/district fills the viewport.  Level 1 keeps the
# country overview.
DRILL_ZOOMS = {1: INITIAL_ZOOM, 2: 6.5, 3: 8.5}

# WebGL clustering threshold in pixels: units closer than this cluster into a
# single marker and un-cluster on zoom, keeping the ~82k-strong unit layer
# responsive.
CLUSTER_STEP = 50


def _hover_lines(df: pd.DataFrame) -> list[str]:
    """One HTML hovercard per unit: source, capacity, dates, and region keys.

    Generators carry installed_capacity (kW); storages carry storage_capacity
    (kWh) as their primary capacity with the installed capacity (kW) shown
    alongside.  Missing values render as an em dash (a missing
    decommissioning_date reads "active").
    """
    is_storage = "storage_capacity" in df.columns

    source = df["energy_source"].astype(str).str.title().fillna("—")

    def fmt_capacity(series: pd.Series) -> pd.Series:
        return series.map(
            lambda v: "—" if pd.isna(v) else f"{v:,.1f}".replace(",", " ")
        )

    if is_storage:
        capacity_lines = (
            "Storage capacity: " + fmt_capacity(df["storage_capacity"]) + " kWh<br>"
            + "Installed capacity: " + fmt_capacity(df["installed_capacity"]) + " kW<br>"
        )
    else:
        capacity_lines = (
            "Installed capacity: " + fmt_capacity(df["installed_capacity"]) + " kW<br>"
        )

    commissioned = (
        pd.to_datetime(df["commissioning_date"], errors="coerce")
        .dt.strftime("%Y-%m-%d")
        .fillna("—")
    )
    decommissioned = (
        pd.to_datetime(df["decommissioning_date"], errors="coerce")
        .dt.strftime("%Y-%m-%d")
        .fillna("active")
    )
    region = df["region"].fillna("—")
    district = df["district"].fillna("—")
    municipality = df["municipality"].fillna("—")

    lines = (
        "<b>" + source + "</b><br>"
        + capacity_lines
        + "Commissioned: " + commissioned + "<br>"
        + "Decommissioned: " + decommissioned + "<br>"
        + region + " · " + district + " · " + municipality
    )
    return lines.to_list()


def _scattermap_trace(
    df: pd.DataFrame,
    source: str,
) -> go.Scattermap:
    """One marker trace for a single energy source.

    Color comes from the shared palette (Circle symbols so marker.color is
    honored by MapLibre's scattermap); WebGL clustering is always on so the
    full unit layer stays interactive.
    """
    return go.Scattermap(
        lon=df["longitude"],
        lat=df["latitude"],
        mode="markers",
        name=source.capitalize(),
        marker=dict(
            color=ENERGY_COLORS.get(source, DEFAULT_COLOR),
            symbol=MARKER_SYMBOL,
        ),
        cluster=dict(enabled=True, step=CLUSTER_STEP),
        hovertext=_hover_lines(df),
        hoverinfo="text",
    )


def _feature_centroid(coordinates) -> tuple[float, float] | None:
    """Bounding-box centre of a GeoJSON geometry (Polygon/LineString nesting).

    Returns ``(lon, lat)`` by averaging the geometry's vertex extremes, so a
    drill click can re-center the map on the clicked area's children without a
    geographic library.
    """
    points: list[tuple[float, float]] = []

    def walk(ring) -> None:
        if ring and isinstance(ring[0], (int, float)):
            points.append((ring[0], ring[1]))
            return
        for part in ring:
            walk(part)

    walk(coordinates)
    if not points:
        return None
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lons) + max(lons)) / 2, (min(lats) + max(lats)) / 2


def centroids_by_name(level_geojson: dict) -> dict[str, tuple[float, float]]:
    """Bounding-box centres for every named feature in the level GeoJSON.

    Keyed by ``properties.name`` (the same key the choropleth fills match),
    so the drill callback can recenter the map on the clicked area's children.
    """
    centres: dict[str, tuple[float, float]] = {}
    for feature in level_geojson.get("features", []):
        name = feature.get("properties", {}).get("name")
        centre = _feature_centroid(feature.get("geometry", {}).get("coordinates"))
        if name and centre:
            centres[name] = centre
    return centres


def add_choropleth_fill(fig: go.Figure, level_geojson: dict, fills: pd.DataFrame, metric: str) -> None:
    """Insert the active drill level's choropleth fill beneath the scatter.

    ``level_geojson`` is the boundary GeoJSON for the active level;
    ``fills`` carries one ``name`` row per area with its live ``value`` (the
    metric-aware value comes pre-aggregated from the data seam — this builder
    is metric-aware only in the hover unit, via ``drill_value``).  The trace is
    inserted at index 0 so the scatter markers always render on top.
    """
    value = drill_value(metric)
    layer = go.Choroplethmap(
        geojson=level_geojson,
        locations=fills["name"] if not fills.empty else [],
        featureidkey="properties.name",
        z=fills["value"] if not fills.empty else [],
        colorscale=CHOROPLETH_COLORSCALE,
        zmin=0,
        hovertemplate=(
            "<b>%{location}</b><br>%{z:,.1f} " + value.unit + "<extra></extra>"
        ),
        name=metric.replace("_", " "),
        showlegend=False,
        colorbar=dict(
            title=value.unit,
            x=0,
            xanchor="left",
            lenmode="fraction",
            len=0.5,
        ),
    )
    fig.add_trace(layer)
    fig.data = fig.data[-1:] + fig.data[:-1]


def _add_source_traces(fig: go.Figure, df: pd.DataFrame) -> None:
    """Append one clustered, palette-colored scattermap trace per energy source.

    Sources follow the shared ``SOURCE_LAYER_ORDER`` (bottom → top paint
    stack) so the layer and sidebar order stay canonical; a source outside
    that list is appended last so it still paints above everything.  Empty
    frames contribute no traces.
    """
    if df.empty or "energy_source" not in df.columns:
        return
    present = df["energy_source"].unique()
    ordered = [s for s in SOURCE_LAYER_ORDER if s in present]
    ordered += sorted(set(present) - set(SOURCE_LAYER_ORDER))
    for source in ordered:
        subset = df[df["energy_source"] == source]
        fig.add_trace(_scattermap_trace(subset, source))


def build_units_map(
    generators: pd.DataFrame, storages: pd.DataFrame
) -> go.Figure:
    """Build the full unit-layer scatter map figure.

    Sources paint in shared canonical order (``SOURCE_LAYER_ORDER``), bottom →
    top: storage, wind, solar, hydro, gas, bio — bio on the very top.  The map
    legend flips that order, so the sidebar reads bio down to storage.  The
    resulting figure carries an open-street-map (MapLibre) basemap, WebGL
    clustering, and the shared curated color palette.  Empty frames simply
    contribute no traces; the figure is still valid.
    """
    fig = go.Figure()
    _add_source_traces(fig, storages)
    _add_source_traces(fig, generators)
    fig.update_layout(legend=dict(traceorder="reversed"))
    fig.update_maps(
        style="open-street-map",
        center=GERMANY_CENTER,
        zoom=INITIAL_ZOOM,
    )
    return fig
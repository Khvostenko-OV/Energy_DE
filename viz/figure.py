"""Figure builder for the Dash scatter map (issue #18).

Turns the data layer's query results (pandas DataFrames for generators and
storages) into a `plotly.graph_objects.Figure` carrying one `scattermap`
trace per energy source with WebGL point clustering, the open-street-map
(MapLibre) basemap, and the shared curated palette — colors from
`viz.palette.ENERGY_COLORS`, storages rendered as diamonds via
`viz.palette.MARKER_SYMBOLS`.  This module is pure: no database access, so the
builder is unit-testable on synthetic frames.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from viz.palette import (
    DEFAULT_COLOR,
    ENERGY_COLORS,
    GENERATOR_MARKER_SYMBOL,
    STORAGE_MARKER_SYMBOL,
)

# Initial camera: center on Germany, zoomed to the country overview.
GERMANY_CENTER = {"lat": 51.16, "lon": 10.45}
INITIAL_ZOOM = 5.5

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
    symbol: str,
) -> go.Scattermap:
    """One marker trace for a single energy source.

    Color and marker shape come from the shared palette; WebGL clustering is
    always on so the full unit layer stays interactive.
    """
    return go.Scattermap(
        lon=df["longitude"],
        lat=df["latitude"],
        mode="markers",
        name=source.capitalize(),
        marker=dict(
            color=ENERGY_COLORS.get(source, DEFAULT_COLOR),
            symbol=symbol,
        ),
        cluster=dict(enabled=True, step=CLUSTER_STEP),
        hovertext=_hover_lines(df),
        hoverinfo="text",
    )


def _add_source_traces(fig: go.Figure, df: pd.DataFrame, symbol: str) -> None:
    """Append one clustered, palette-colored scattermap trace per energy source.

    Each distinct energy_source gets its own trace so the legend and the
    shared palette map cleanly; empty frames contribute no traces.
    """
    sources = (
        sorted(df["energy_source"].unique())
        if not df.empty and "energy_source" in df.columns
        else []
    )
    for source in sources:
        subset = df[df["energy_source"] == source]
        fig.add_trace(_scattermap_trace(subset, source, symbol))


def build_units_map(
    generators: pd.DataFrame, storages: pd.DataFrame
) -> go.Figure:
    """Build the full unit-layer scatter map figure.

    Generators produce one trace per distinct energy_source; storages likewise,
    but with the storage marker shape.  The resulting figure carries an
    open-street-map (MapLibre) basemap, WebGL clustering, and the shared
    curated color palette.  Empty frames simply contribute no traces; the
    figure is still valid.
    """
    fig = go.Figure()
    _add_source_traces(fig, generators, GENERATOR_MARKER_SYMBOL)
    _add_source_traces(fig, storages, STORAGE_MARKER_SYMBOL)
    fig.update_maps(
        style="open-street-map",
        center=GERMANY_CENTER,
        zoom=INITIAL_ZOOM,
    )
    return fig
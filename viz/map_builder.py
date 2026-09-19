"""PyDeck map builder for the Streamlit viz app (issues #23, #24, #26).

Builds the app's pydeck.Deck objects.  This module is pure: no database
access, so the builder is unit-testable on synthetic layers.  The T1 tracer
only needs the Germany overview on the CARTO Light basemap and the empty
standby deck for the missing-tables case — a deck without layers, which is
exactly what ``build_deck()`` produces by default.  T2 (#24) adds one
pickable scatter layer per energy source, in the palette's color and paint
order.  T4 (#26) adds `build_choropleth_layer`, a pickable GeoJsonLayer
coloring every displayed area by the capacity fill injected into its
properties.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

import pydeck as pdk

from viz.config import GERMANY_CENTER, INITIAL_ZOOM, LIGHT_MAP_STYLE
from viz.palette import SOURCE_LAYER_ORDER, source_color

# Fixed scatter radius (metres) for every unit layer.  Points are sized purely
# for visibility at the country overview; sizing by capacity is not in scope.
UNIT_RADIUS_M = 1500


def build_deck(
    layers: Iterable | None = None,
    *,
    map_style: str = LIGHT_MAP_STYLE,
    lon: float = GERMANY_CENTER["lon"],
    lat: float = GERMANY_CENTER["lat"],
    zoom: float = INITIAL_ZOOM,
    tooltip: Mapping | None = None,
) -> pdk.Deck:
    """Build a deck on the Light basemap, defaulting to the Germany overview.

    ``layers`` pass through untouched, so an empty iterable produces the empty
    (basemap-only) deck used in standby.  ``tooltip`` is handed to pydeck so
    every hoverable layer shares the same card template.
    """
    return pdk.Deck(
        layers=list(layers or []),
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
        map_style=map_style,
        tooltip=tooltip,
    )


def hex_to_rgba(hex_color: str, alpha: int = 255) -> tuple[int, int, int, int]:
    """Palette hex (``#rrggbb``) → rgba tuple for deck.gl fill colors."""
    hex_color = hex_color.strip("#")
    return (
        int(hex_color[0:2], 16),
        int(hex_color[2:4], 16),
        int(hex_color[4:6], 16),
        alpha,
    )


def build_source_layers(units_by_source: Mapping[str, list[Mapping[str, Any]]]) -> list[pdk.Layer]:
    """One pickable scatter layer per present source, in palette paint order.

    Painted bottom-to-top in ``SOURCE_LAYER_ORDER``; sources outside that
    list (an unexpected energy_source) are appended last so they stay visible
    above every known one.
    """
    sources = [
        source for source in SOURCE_LAYER_ORDER if source in units_by_source
    ] + [source for source in units_by_source if source not in SOURCE_LAYER_ORDER]
    return [
        pdk.Layer(
            "ScatterplotLayer",
            id=f"{source}-units",
            data=list(units_by_source[source]),
            get_position="[longitude, latitude]",
            get_fill_color=hex_to_rgba(source_color(source)),
            get_radius=UNIT_RADIUS_M,
            pickable=True,
        )
        for source in sources
    ]


# Accessor for the per-feature rgba fill injected by `viz.choropleth`.
AREA_FILL_COLOR_ACCESSOR = "properties.fill_color"

# Outline of every choropleth polygon: a muted neutral so area borders stay
# readable over both the base map and the capacity fill.
AREA_LINE_COLOR: tuple[int, int, int, int] = (90, 100, 112, 200)

# Minimum on-screen outline width, so district/municipality borders don't
# vanish into the antialiasing at overview zooms.
AREA_LINE_WIDTH_MIN_PX = 1


def build_choropleth_layer(features: Mapping[str, Any]) -> pdk.Layer:
    """One pickable GeoJsonLayer coloring each area's polygon by its fill.

    ``features`` is the FeatureCollection from `viz.choropleth` (properties
    carry ``fill_color`` plus the hover fields), and the layer reads the
    injected fills through `AREA_FILL_COLOR_ACCESSOR`, so the color logic
    stays a pure seam rather than a JS accessor here.
    """
    return pdk.Layer(
        "GeoJsonLayer",
        id="areas-fill",
        data=features,
        get_fill_color=AREA_FILL_COLOR_ACCESSOR,
        get_line_color=AREA_LINE_COLOR,
        line_width_min_pixels=AREA_LINE_WIDTH_MIN_PX,
        stroked=True,
        filled=True,
        pickable=True,
    )

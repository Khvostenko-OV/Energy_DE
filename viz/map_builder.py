"""PyDeck map builder for the Streamlit viz app (issue #23).

Builds the app's pydeck.Deck objects.  This module is pure: no database
access, so the builder is unit-testable on synthetic layers.  The T1 tracer
only needs the Germany overview on the CARTO Light basemap and the empty
standby deck for the missing-tables case — a deck without layers, which is
exactly what ``build_deck()`` produces by default.
"""

from __future__ import annotations

from typing import Iterable

import pydeck as pdk

from viz.config import GERMANY_CENTER, INITIAL_ZOOM, LIGHT_MAP_STYLE


def build_deck(
    layers: Iterable | None = None,
    *,
    map_style: str = LIGHT_MAP_STYLE,
    lon: float = GERMANY_CENTER["lon"],
    lat: float = GERMANY_CENTER["lat"],
    zoom: float = INITIAL_ZOOM,
) -> pdk.Deck:
    """Build a deck on the Light basemap, defaulting to the Germany overview.

    ``layers`` pass through untouched, so an empty iterable produces the empty
    (basemap-only) deck used in standby.
    """
    return pdk.Deck(
        layers=list(layers or []),
        initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
        map_style=map_style,
    )

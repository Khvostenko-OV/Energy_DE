"""Unit tests for the viz map-builder seam (issue #23).

`build_deck` is a pure sandwich: given layers and a view it returns a
pydeck.Deck on the CARTO Light basemap, defaulting the view to the Germany
overview.  The empty-deck case (no layers) is the deck the app shows in
standby, when nothing is rendered but the basemap.
"""

from viz.config import GERMANY_CENTER, INITIAL_ZOOM, LIGHT_MAP_STYLE, MAP_STYLES
from viz.map_builder import build_deck


class TestEmptyDeck:
    def test_standby_deck_has_no_layers(self):
        assert build_deck().layers == []

    def test_deck_is_centered_on_germany(self):
        deck = build_deck()
        assert deck.initial_view_state.latitude == GERMANY_CENTER["lat"]
        assert deck.initial_view_state.longitude == GERMANY_CENTER["lon"]

    def test_deck_uses_the_overview_zoom(self):
        assert build_deck().initial_view_state.zoom == INITIAL_ZOOM

    def test_deck_uses_the_light_basemap(self):
        assert build_deck().map_style == LIGHT_MAP_STYLE == MAP_STYLES["Light"]


class TestDeckOverrides:
    def test_view_state_can_be_overridden(self):
        deck = build_deck(lon=13.4, lat=52.5, zoom=8.0)
        view = deck.initial_view_state
        assert (view.longitude, view.latitude, view.zoom) == (13.4, 52.5, 8.0)

    def test_layers_pass_through(self):
        layer = object()
        assert build_deck(layers=[layer]).layers == [layer]

    def test_map_style_can_be_overridden(self):
        assert (
            build_deck(map_style="https://example.com/style.json").map_style
            == "https://example.com/style.json"
        )

"""Unit tests for the viz map-builder seam (issues #23, #24).

`build_deck` is a pure sandwich: given layers and a view it returns a
pydeck.Deck on the CARTO Light basemap, defaulting the view to the Germany
overview.  The empty-deck case (no layers) is the deck the app shows in
standby, when nothing is rendered but the basemap.

`build_source_layers` (issue #24) turns per-source unit rows into one scatter
layer per source — in the palette's canonical paint order, in the palette's
color, pickable (so hovering works).
"""

from viz.config import GERMANY_CENTER, INITIAL_ZOOM, LIGHT_MAP_STYLE, MAP_STYLES
from viz.map_builder import (
    build_choropleth_layer,
    build_deck,
    build_source_layers,
    hex_to_rgba,
)


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

    def test_tooltip_passes_through(self):
        tooltip = {"html": "{tooltip}"}
        assert build_deck(tooltip=tooltip)._tooltip == tooltip


def unit_row(source="solar"):
    return {
        "unit_id": 1,
        "energy_source": source,
        "installed_capacity": 120.0,
        "commissioning_date": "2015-03-01",
        "decommissioning_date": None,
        "longitude": 10.5,
        "latitude": 50.5,
        "region": "Bavaria",
        "district": None,
        "municipality": None,
    }


class TestHexToRgba:
    def test_palette_hex_becomes_an_rgba_tuple(self):
        assert hex_to_rgba("#fdd835") == (253, 216, 53, 255)

    def test_alpha_can_be_set(self):
        assert hex_to_rgba("#fdd835", alpha=180) == (253, 216, 53, 180)


class TestSourceLayers:
    def test_no_sources_builds_no_layers(self):
        assert build_source_layers({}) == []

    def test_one_scatter_layer_per_source(self):
        layers = build_source_layers({"solar": [unit_row("solar")], "wind": [unit_row("wind")]})
        assert [layer.id for layer in layers] == ["wind-units", "solar-units"]

    def test_layers_paint_in_canonical_bottom_to_top_order(self):
        layers = build_source_layers({key: [unit_row(key)] for key in ("bio", "storage", "wind")})
        assert [layer.id for layer in layers] == [
            "storage-units",
            "wind-units",
            "bio-units",
        ]

    def test_layer_geometry_reads_lon_lat(self):
        layer = build_source_layers({"solar": [unit_row("solar")]})[0]
        assert "[longitude, latitude]" in str(layer.get_position)

    def test_layer_uses_the_sources_palette_color(self):
        layer = build_source_layers({"hydro": [unit_row("hydro")]})[0]
        assert layer.get_fill_color == (30, 136, 229, 255)

    def test_layer_is_pickable_for_hovering(self):
        layer = build_source_layers({"solar": [unit_row("solar")]})[0]
        assert layer.type == "ScatterplotLayer"
        assert layer.pickable is True

    def test_unknown_sources_paint_above_known_ones(self):
        layers = build_source_layers(
            {"bio": [unit_row("bio")], "mystery": [unit_row("mystery")]}
        )
        assert [layer.id for layer in layers] == ["bio-units", "mystery-units"]


class TestChoroplethLayer:
    def feature_collection(self):
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": []},
                    "properties": {
                        "name": "Berlin",
                        "fill_color": [33, 150, 243, 255],
                    },
                }
            ],
        }

    def test_is_a_pickable_geojson_layer(self):
        layer = build_choropleth_layer(self.feature_collection())
        assert layer.type == "GeoJsonLayer"
        assert layer.pickable is True

    def test_features_pass_through_as_layer_data(self):
        features = self.feature_collection()
        layer = build_choropleth_layer(features)
        assert layer.data == features

    def test_fill_color_reads_the_injected_property(self):
        layer = build_choropleth_layer(self.feature_collection())
        assert "properties.fill_color" in layer.get_fill_color

    def test_polygons_are_filled_and_stroked(self):
        layer = build_choropleth_layer(self.feature_collection())
        assert layer.filled is True
        assert layer.stroked is True
        assert layer.line_width_min_pixels >= 1

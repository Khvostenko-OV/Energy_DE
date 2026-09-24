"""Unit tests for the viz map-builder seam (issues #23, #24).

`build_deck` is a pure sandwich: given layers and a view it returns a
pydeck.Deck on the CARTO Light basemap, defaulting the view to the Germany
overview.  The empty-deck case (no layers) is the deck the app shows in
standby, when nothing is rendered but the basemap.

`build_source_layers` (issue #24) turns per-source unit rows into one
IconLayer per source — in the palette's canonical paint order, tinted with
the palette's color from its per-source sprite atlas, pickable (so hovering
works).
"""

import json

import pydeck as pdk

from viz.config import GERMANY_CENTER, INITIAL_ZOOM, LIGHT_MAP_STYLE, MAP_STYLES
from viz.icon_atlas import icon_size_px
from viz.map_builder import (
    build_boundary_layer,
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
        "state": "Bavaria",
        "region": None,
        "district": None,
    }


class TestHexToRgba:
    def test_palette_hex_becomes_an_rgba_tuple(self):
        assert hex_to_rgba("#fdd835") == (253, 216, 53, 255)

    def test_alpha_can_be_set(self):
        assert hex_to_rgba("#fdd835", alpha=180) == (253, 216, 53, 180)


class TestSourceLayers:
    def test_no_sources_builds_no_layers(self):
        assert build_source_layers({}) == []

    def test_one_icon_layer_per_source(self):
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
        assert layer.get_color == (30, 136, 229, 255)

    def test_layer_is_pickable_for_hovering(self):
        layer = build_source_layers({"solar": [unit_row("solar")]})[0]
        assert layer.type == "IconLayer"
        assert layer.pickable is True

    def test_layer_icon_anchors_on_its_inlined_sprite(self):
        layer = build_source_layers({"wind": [unit_row("wind")]})[0]
        assert layer.get_icon == "@@=icon"  # per-row id, resolved into a real accessor
        assert layer.icon_atlas.startswith("data:image/png;base64,")
        assert layer.data[0]["icon"] == "icon"  # tiny per-row payload, not the sprite
        mapping_cell = layer.icon_mapping["icon"]
        assert (mapping_cell["x"], mapping_cell["y"]) == (0, 0)
        assert mapping_cell["width"] == mapping_cell["height"] == icon_size_px("wind")
        assert mapping_cell["mask"] is True  # white glyph tinted by get_color

    def test_serialized_spec_prepacks_one_sprite_frame(self):
        layer = build_source_layers({"wind": [unit_row("wind")]})[0]
        serialized = json.loads(pdk.Deck(layers=[layer]).to_json())["layers"]
        assert len(serialized) == 1
        assert serialized[0]["getIcon"] == "@@=icon"  # a function accessor, not a constant
        assert serialized[0]["iconAtlas"].startswith("data:image/png;base64,")
        cell = serialized[0]["iconMapping"]["icon"]
        assert cell == {"x": 0, "y": 0, "width": cell["width"], "height": cell["width"],
                        "mask": True}
        assert serialized[0]["data"][0]["icon"] == "icon"

    def test_layer_sizes_icons_in_pixels(self):
        layer = build_source_layers({"bio": [unit_row("bio")]})[0]
        assert layer.get_size > 0
        assert layer.get_color[-1] == 255  # fully opaque tint

    def test_layer_keeps_unit_rows_light(self):
        # The sprite must be a per-layer prop (icon_atlas), never embedded per
        # row: at ~100k units a copied base64 image would balloon the payload.
        layer = build_source_layers({"solar": [unit_row("solar")] * 10})[0]
        assert len(layer.data) == 10
        assert all(row["icon"] == "icon" for row in layer.data)
        assert len(layer.icon_atlas) > len(layer.data[0]["icon"])
        # Nothing else per-row references the sprite either.
        assert all(len(row["icon"]) == len("icon") for row in layer.data)

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


class TestBoundaryLayer:
    def feature_collection(self):
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Polygon", "coordinates": []},
                    "properties": {
                        "name": "Germany",
                        "fill_color": [241, 243, 246, 150],
                    },
                }
            ],
        }

    def test_is_a_pickable_geojson_layer(self):
        layer = build_boundary_layer(self.feature_collection())
        assert layer.type == "GeoJsonLayer"
        assert layer.pickable is True

    def test_features_pass_through_as_layer_data(self):
        features = self.feature_collection()
        layer = build_boundary_layer(features)
        assert layer.data == features

    def test_outline_is_stroked_but_never_filled(self):
        layer = build_boundary_layer(self.feature_collection())
        assert layer.filled is False
        assert layer.stroked is True
        assert layer.line_width_min_pixels >= 1

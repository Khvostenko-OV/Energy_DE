"""Unit tests for the viz palette lookup (issue #24).

The palette maps each canonical energy_source to a fixed hex color and a
canonical paint order.  These tests read as the contract the scatter layers
and sidebar consume: `source_color` gives every loaded source its palette
color, unknown sources fall back, and `SOURCE_LAYER_ORDER` fixes the
bottom-to-top paint order.
"""

from viz.palette import DEFAULT_COLOR, SOURCE_LAYER_ORDER, source_color


class TestSourceColor:
    def test_loaded_sources_get_their_palette_hex(self):
        assert source_color("hydro") == "#1e88e5"
        assert source_color("storage") == "#4e342e"
        assert source_color("wind") == "#9c27b0"

    def test_unknown_source_falls_back_to_default_color(self):
        assert source_color("nuclear") == DEFAULT_COLOR


class TestLayerOrder:
    def test_sources_paint_bottom_to_top_in_canonical_order(self):
        assert SOURCE_LAYER_ORDER == (
            "storage",
            "wind",
            "solar",
            "hydro",
            "gas",
            "bio",
        )

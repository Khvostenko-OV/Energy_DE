"""Unit tests for the choropleth colorbar seam (issue #26).

`colorbar_html` turns the displayed scope's max area capacity into a
self-contained overlay div: a vertical bar painted with the same `RAMP_LOW` →
`RAMP_HIGH` gradient the area fills use, with scale ticks at rounded capacity
levels — four equal bins of a two-significant-digit step (max/5 truncated to
two digits) plus a top bin to the max — floating `fixed` over the map with a
high `z-index` and
`pointer-events: none` so it never blocks the map underneath.  Pure string
seam, no database.
"""

from viz.choropleth import RAMP_HIGH, RAMP_LOW
from viz.colorbar import (
    BAR_HEIGHT_PX,
    HEADER_STRIP_PX,
    MAP_HEIGHT,
    TOP_PX,
    capacity_ticks,
    colorbar_html,
)


def _rgba(color):
    r, g, b, a = color
    return f"rgba({r}, {g}, {b}, {a / 255:.2f})"


class TestCapacityTicks:
    def test_five_bins_from_zero_to_max(self):
        ticks = capacity_ticks(400.0)
        assert ticks[0] == (0.0, 0.0)
        assert ticks[-1] == (1.0, 400.0)
        assert len(ticks) == 6

    def test_levels_are_rounded_nice_steps(self):
        ticks = capacity_ticks(229862.0)
        assert [(fraction, level) for fraction, level in ticks if level] == [
            (45000.0 / 229862.0, 45000.0),
            (90000.0 / 229862.0, 90000.0),
            (135000.0 / 229862.0, 135000.0),
            (180000.0 / 229862.0, 180000.0),
            (1.0, 229862.0),
        ]

    def test_marks_land_near_even_percentages(self):
        # max/5 truncated to two digits -> marks ~20/40/60/80/100% of the max.
        for max_mw in (62000.0, 500.0, 1000.0, 77.0):
            ticks = capacity_ticks(max_mw)
            fractions = [fraction for fraction, _ in ticks[1:]]
            assert min(fractions) >= 0.19
            assert max(fractions[:-1]) <= 0.81

    def test_top_bin_is_never_smaller_than_the_others(self):
        for max_mw in (500.0, 1000.0, 12345.0, 229862.0, 77.0):
            ticks = capacity_ticks(max_mw)
            step = ticks[1][1] - ticks[0][1]
            top_bin = ticks[-1][1] - ticks[-2][1]
            assert top_bin >= step


class TestColorbarHtml:
    def test_gradient_uses_the_choropleth_ramp(self):
        html = colorbar_html(1000.0)
        assert _rgba(RAMP_LOW) in html
        assert _rgba(RAMP_HIGH) in html

    def test_caption_labels_the_capacity_in_gw(self):
        html = colorbar_html(62490.1)
        assert ">Capacity (GW)<" in html

    def test_marks_are_gw_rounded_to_one_decimal(self):
        html = colorbar_html(62490.1)
        assert "62.5</span>" in html  # 62,490.1 MW -> 62.5 GW
        for mark in ("0.0", "12.0", "24.0", "36.0", "48.0", "62.5"):
            assert f">{mark}<" in html

    def test_sub_gigawatt_scope_keeps_mw_scale(self):
        html = colorbar_html(900.0)
        assert ">Capacity (MW)<" in html
        for mark in ("0.0", "180.0", "360.0", "540.0", "720.0", "900.0"):
            assert f">{mark}<" in html

    def test_marks_carry_no_suffix(self):
        html = colorbar_html(62490.1)
        assert "62.5 MW" not in html
        assert "62,490.1" not in html
        assert "900.0 MW" not in colorbar_html(900.0)

    def test_mark_positions_match_their_levels_on_the_ramp(self):
        html = colorbar_html(229862.0)
        for fraction, level in capacity_ticks(229862.0):
            assert f"bottom:{fraction * 100:.0f}%" in html
        for level in (45_000, 90_000, 135_000, 180_000, 229_862):
            assert f">{level / 1000:,.1f}<" in html
        assert "Capacity (GW)" in html  # caption, not a suffix

    def test_overlay_never_blocks_the_map(self):
        assert "position:fixed" in colorbar_html(100.0)
        assert "pointer-events:none" in colorbar_html(100.0)

    def test_overlay_floats_above_the_deck(self):
        assert "z-index:999" in colorbar_html(100.0)

    def test_bar_centers_on_the_map_window(self):
        # Bar center (TOP_PX + half its height) sits on the map window center
        # (everything above the map + half the map height).
        assert TOP_PX + BAR_HEIGHT_PX / 2 == HEADER_STRIP_PX + MAP_HEIGHT / 2
        html = colorbar_html(100.0)
        assert f"top:{TOP_PX}px" in html
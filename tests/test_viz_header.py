"""Unit tests for the header aggregate formatting seam (issue #25).

`viz.header` formats the four live figures of the header above the map: the
scope title (level + displayed-area count, or the single area's name) and the
capacity (MW) / active-unit-count / area (km²) numbers.  Pure formatting on
plain numbers, mirroring the `viz.tooltip` seam split, so no database is
needed.
"""

from datetime import date

from viz.config import INITIAL_LEVEL, LEVEL_INDEX, MAP_LEVELS
from viz.data import (
    area_name_query,
    areas_query,
    fetch_areas,
    fetch_header_metrics,
    header_metrics_query,
)
from viz.header import (
    SINGULAR_LEVEL_PREFIX,
    format_area_km2,
    format_mw,
    format_unit_count,
    scope_title,
    single_area_title,
)


class TestMwFormatting:
    def test_mw_is_integer_thousands_separated(self):
        assert format_mw(12345.6) == "12,346"

    def test_mw_handles_a_clean_integer(self):
        assert format_mw(12000.0) == "12,000"

    def test_mw_of_zero_reads_zero(self):
        assert format_mw(0.0) == "0"


class TestCountFormatting:
    def test_count_is_thousands_separated(self):
        assert format_unit_count(543210) == "543,210"

    def test_small_count_has_no_separators(self):
        assert format_unit_count(999) == "999"

    def test_zero_count_reads_zero(self):
        assert format_unit_count(0) == "0"


class TestAreaFormatting:
    def test_area_is_integer_km2_thousands_separated(self):
        assert format_area_km2(357588.4) == "357,588"

    def test_zero_area_reads_zero(self):
        assert format_area_km2(0.0) == "0"


class TestSingleAreaTitle:
    def test_region_level_prefixes_the_name(self):
        assert single_area_title("Regions", "Berlin") == "Region Berlin"

    def test_district_level_prefixes_the_name(self):
        assert single_area_title("Districts", "Calw") == "District Calw"

    def test_municipality_level_prefixes_the_name(self):
        assert single_area_title("Municipalities", "Calw") == "Municipality Calw"

    def test_country_level_uses_the_bare_name(self):
        assert single_area_title("Germany", "Germany") == "Germany"


class TestScopeTitle:
    def test_exactly_one_area_shows_the_single_name(self):
        assert scope_title("Regions", 1, "Berlin") == "Region Berlin"

    def test_multiple_areas_show_level_and_count(self):
        assert scope_title("Regions", 19) == "Regions · 19 areas"

    def test_country_scope_is_the_single_named_area(self):
        assert scope_title("Germany", 1, "Germany") == "Germany"


class TestLevelConfig:
    def test_level_index_matches_the_chooser_labels(self):
        assert LEVEL_INDEX == {
            "Germany": 0,
            "Regions": 1,
            "Districts": 2,
            "Municipalities": 3,
        }

    def test_every_chooser_label_has_a_level(self):
        assert list(LEVEL_INDEX) == list(MAP_LEVELS)

    def test_initial_level_is_the_country(self):
        assert LEVEL_INDEX[INITIAL_LEVEL] == 0

    def test_four_level_labels_expected(self):
        assert len(LEVEL_INDEX) == 4


class TestSingularPrefixMap:
    def test_singular_prefixes_cover_the_sub_country_levels(self):
        assert SINGULAR_LEVEL_PREFIX == {
            "Regions": "Region",
            "Districts": "District",
            "Municipalities": "Municipality",
        }

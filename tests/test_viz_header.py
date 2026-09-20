"""Unit tests for the header aggregate seams (issue #25, render-opt).

`viz.header` formats the four live figures of the header above the map: the
scope title (level + displayed-area count, or the single area's name) and the
capacity (MW) / active-unit-count / area (km²) numbers, and `areas_summary`
derives the scope figures (count, km² sum, single name) from the boundary
rows the choropleth already fetched — no extra queries.  Pure formatting and
summarization on plain rows/numbers, so no database is needed.
"""

from viz.config import INITIAL_LEVEL, LEVEL_INDEX, MAP_LEVELS
from viz.header import (
    SINGULAR_LEVEL_PREFIX,
    areas_summary,
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
            "States": 1,
            "Regions": 2,
            "Districts": 3,
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


def _boundary_row(name, area=100.0):
    return {"name": name, "area": area, "geojson": "{}"}


class TestAreasSummary:
    def test_counts_and_sums_every_level_area(self):
        rows = [_boundary_row("Berlin", 891.0), _boundary_row("Hamburg", 755.0)]
        assert areas_summary(rows) == {
            "area_count": 2,
            "total_area_km2": 1646.0,
        }

    def test_name_selection_narrows_the_displayed_areas(self):
        rows = [_boundary_row("Berlin", 891.0), _boundary_row("Hamburg", 755.0)]
        assert areas_summary(rows, names=("Berlin",)) == {
            "area_count": 1,
            "total_area_km2": 891.0,
            "area_name": "Berlin",
        }

    def test_single_displayed_area_attaches_its_name(self):
        assert areas_summary([_boundary_row("Germany")])["area_name"] == "Germany"

    def test_many_areas_omit_the_name(self):
        rows = [_boundary_row("Berlin"), _boundary_row("Hamburg")]
        assert "area_name" not in areas_summary(rows)

    def test_empty_boundaries_sum_to_zero(self):
        assert areas_summary([]) == {"area_count": 0, "total_area_km2": 0}
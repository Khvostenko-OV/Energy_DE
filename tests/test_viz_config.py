"""Unit tests for the viz config defaults (issue #23).

The config module is the single home for the T1 user-facing defaults (active
timescope, checked sources, initial level, Light basemap, Germany overview
view), so these tests read as a spec of what those defaults are.
"""

from datetime import date

from viz.config import (
    CORE_SCHEMA,
    DEFAULT_SOURCES,
    GERMANY_CENTER,
    INITIAL_LEVEL,
    INITIAL_ZOOM,
    LEVEL_INDEX,
    LEVEL_UNIT_AREA_COLUMN,
    LIGHT_MAP_STYLE,
    MAP_HEIGHT,
    MAP_LEVELS,
    MARTS_SCHEMA,
    SERVICE_SCHEMA,
    STANDBY_MAP_HEIGHT,
    TIMESCOPE_START,
    default_timescope,
)


class TestTimescopeDefaults:
    def test_timescope_starts_at_epoch(self):
        assert TIMESCOPE_START == date(1900, 1, 1)

    def test_default_timescope_runs_to_today(self):
        assert default_timescope() == (date(1900, 1, 1), date.today())


class TestSourceDefaults:
    def test_all_sources_checked_by_default(self):
        assert DEFAULT_SOURCES == ("bio", "gas", "hydro", "solar", "wind", "storage")


class TestLevelDefaults:
    def test_initial_level_is_germany(self):
        assert INITIAL_LEVEL == "Germany"

    def test_level_chooser_starts_with_germany(self):
        assert MAP_LEVELS[0] == "Germany"

    def test_initial_level_maps_to_the_country_boundary(self):
        assert LEVEL_INDEX[INITIAL_LEVEL] == 0

    def test_every_chooser_label_maps_to_a_boundary_level(self):
        assert list(LEVEL_INDEX) == [label.split(" ")[0] for label in MAP_LEVELS]

    def test_levels_index_matches_the_boundary_table(self):
        assert LEVEL_INDEX == {
            "Germany": 0,
            "States": 1,
            "Regions": 2,
            "Districts": 3,
        }


class TestLevelAreaColumns:
    def test_every_level_maps_to_a_unit_area_column(self):
        assert list(LEVEL_UNIT_AREA_COLUMN) == [
            label.split(" ")[0] for label in MAP_LEVELS
        ]

    def test_country_needs_no_area_column(self):
        assert LEVEL_UNIT_AREA_COLUMN["Germany"] is None

    def test_attribute_matches_the_levels_spatial_grain(self):
        assert LEVEL_UNIT_AREA_COLUMN == {
            "Germany": None,
            "States": "state",
            "Regions": "region",
            "Districts": "district",
        }

    def test_columns_are_safe_static_attribute_names(self):
        assert not any(
            column and (";" in column or " " in column)
            for column in LEVEL_UNIT_AREA_COLUMN.values()
        )


class TestOverviewDefaults:
    def test_germany_center_is_a_wgs84_point(self):
        assert isinstance(GERMANY_CENTER["lon"], float)
        assert isinstance(GERMANY_CENTER["lat"], float)

    def test_initial_zoom_shows_the_whole_country(self):
        assert 4 < INITIAL_ZOOM < 7

    def test_map_window_is_large(self):
        assert MAP_HEIGHT >= 600

    def test_standby_map_is_just_a_hint(self):
        assert STANDBY_MAP_HEIGHT == 500
        assert STANDBY_MAP_HEIGHT < MAP_HEIGHT


class TestBasemapDefaults:
    def test_light_basemap_is_carto_positron(self):
        assert LIGHT_MAP_STYLE.startswith(
            "https://basemaps.cartocdn.com/gl/positron-gl-style/"
        )


class TestSchemaConstants:
    """The viz package is standalone (no ``etl`` import), so its schema-name
    constants must stay in lockstep with the pipeline's `etl.db_schema`."""

    def test_core_schema_matches_etl(self):
        from etl.db_schema import CORE_SCHEMA as ETL_CORE

        assert CORE_SCHEMA == ETL_CORE

    def test_service_schema_matches_etl(self):
        from etl.db_schema import SERVICE_SCHEMA as ETL_SERVICE

        assert SERVICE_SCHEMA == ETL_SERVICE

    def test_marts_schema_matches_etl(self):
        from etl.db_schema import MARTS_SCHEMA as ETL_MARTS

        assert MARTS_SCHEMA == ETL_MARTS

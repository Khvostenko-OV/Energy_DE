"""Unit tests for the viz config defaults (issue #23).

The config module is the single home for the T1 user-facing defaults (active
timescope, checked sources, initial level, Light basemap, Germany overview
view), so these tests read as a spec of what those defaults are.
"""

from datetime import date

from viz.config import (
    DEFAULT_SOURCES,
    GERMANY_CENTER,
    INITIAL_LEVEL,
    INITIAL_ZOOM,
    LIGHT_MAP_STYLE,
    MAP_HEIGHT,
    MAP_LEVELS,
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


class TestOverviewDefaults:
    def test_germany_center_is_a_wgs84_point(self):
        assert isinstance(GERMANY_CENTER["lon"], float)
        assert isinstance(GERMANY_CENTER["lat"], float)

    def test_initial_zoom_shows_the_whole_country(self):
        assert 4 < INITIAL_ZOOM < 7

    def test_map_window_is_large(self):
        assert MAP_HEIGHT >= 600


class TestBasemapDefaults:
    def test_light_basemap_is_carto_positron(self):
        assert LIGHT_MAP_STYLE.startswith(
            "https://basemaps.cartocdn.com/gl/positron-gl-style/"
        )

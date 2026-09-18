"""Unit tests for the app's drill-state seam (issue #19).

`next_drill_state` maps a choropleth click (a `location` string from
Dash's ``clickData``) onto the next active drill state without touching Dash,
the database, or the figure runtime.  The model under test is the boundary
GeoJSON, which arrives via `viz.data.load_level_geojson`; we monkeypatch it so
these tests stay disk-free and deterministic.
"""

import pytest

from viz.app import (
    INITIAL_STATE,
    OVERVIEW_CENTRE,
    breadcrumb_items,
    core_tables_message,
    figure_state,
    next_drill_state,
    overview_state,
    state_after_breadcrumb,
    state_after_click,
)
from viz.data import missing_core_tables
from viz.drill import CAPACITY_MW, UNIT_COUNT


def _geojson(level, area_names):
    """Synthetic per-level GeoJSON with named square features."""
    features = []
    for i, name in enumerate(area_names):
        x0 = 5.0 + i
        features.append(
            {
                "type": "Feature",
                "properties": {"name": name},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[x0, 49.0], [x0, 50.0], [x0 + 1, 50.0], [x0 + 1, 49.0], [x0, 49.0]]
                    ],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


@pytest.fixture
def _assets(monkeypatch):
    from viz import app as viz_app
    from viz import data as viz_data

    assets = {
        1: _geojson(1, ["Hessen"]),
        2: _geojson(2, ["Kassel"]),
        3: _geojson(3, ["Kassel"]),
    }
    monkeypatch.setattr(viz_app, "load_level_geojson", lambda level: assets[level])
    monkeypatch.setattr(viz_data, "load_level_geojson", lambda level: assets[level])
    return assets


LEVEL_1 = {"level": 1, "parent_filters": {}, "metric": CAPACITY_MW, "centre": None}


class TestDrillState:
    def test_first_click_drills_to_districts_scoped_by_region(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        assert state["level"] == 2
        assert state["parent_filters"] == {"region": "Hessen"}
        assert state["metric"] == CAPACITY_MW

    def test_second_click_drills_to_municipalities_scoped_by_chain(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        state = next_drill_state(state, "Kassel")
        assert state["level"] == 3
        assert state["parent_filters"] == {"region": "Hessen", "district": "Kassel"}

    def test_level_three_click_recenters_to_overview(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        state = next_drill_state(state, "Kassel")
        state = next_drill_state(state, "Kassel")
        assert state == overview_state(CAPACITY_MW)

    def test_drill_keeps_the_metric_toggle(self, _assets):
        state = dict(LEVEL_1, metric=UNIT_COUNT)
        state = next_drill_state(state, "Hessen")
        assert state["metric"] == UNIT_COUNT
        state = next_drill_state(state, "Kassel")
        assert state["metric"] == UNIT_COUNT

    def test_click_without_location_keeps_state(self, _assets):
        state = next_drill_state(LEVEL_1, None)
        assert state["level"] == 1
        assert state["parent_filters"] == {}

    def test_drill_recenters_on_clicked_areas_centroid(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        # Level-2 asset places "Kassel" at x in [5,6], y in [49,50].
        assert state["centre"] == (5.5, 49.5)


def _buttons(items):
    return [
        item
        for item in items
        if isinstance(getattr(item, "id", None), dict)
        and item.id.get("type") == "drill-breadcrumb"
    ]


class TestBreadcrumbs:
    def test_breadcrumbs_read_germany_region_district(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        state = next_drill_state(state, "Kassel")
        labels = [item.children for item in _buttons(breadcrumb_items(state))]
        assert labels == ["Germany", "Hessen", "Kassel"]

    def test_current_level_breadcrumb_is_disabled(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        items = _buttons(breadcrumb_items(state))
        assert items[0].disabled is False
        assert items[1].disabled is True

    def test_clicking_region_breadcrumb_drills_up_to_level_one(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        state = next_drill_state(state, "Kassel")
        state = state_after_breadcrumb(state, 1)
        assert state == overview_state(CAPACITY_MW)

    def test_clicking_region_breadcrumb_drills_up_to_level_two(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        state = next_drill_state(state, "Kassel")
        state = state_after_breadcrumb(state, 2)
        assert state["level"] == 2
        assert state["parent_filters"] == {"region": "Hessen"}
        assert state["metric"] == CAPACITY_MW

    def test_breadcrumb_drill_up_recenters_on_parent_centroid(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        state = next_drill_state(state, "Kassel")
        state = state_after_breadcrumb(state, 2)
        # Level-1 asset places "Hessen" at x in [5,6], y in [49,50].
        assert state["centre"] == (5.5, 49.5)

    def test_breadcrumb_click_noop_for_level_below_one_or_current(self, _assets):
        state = next_drill_state(LEVEL_1, "Hessen")
        assert state_after_breadcrumb(state, 0) == state
        assert state_after_breadcrumb(state, 1) != state
        assert state_after_breadcrumb(state, state["level"]) == state

    def test_breadcrumb_anchors_are_buttons_with_patterned_ids(self):
        items = breadcrumb_items(dict(LEVEL_1, level=2, parent_filters={"region": "Hessen"}))
        buttons = _buttons(items)
        assert buttons[0].id == {"type": "drill-breadcrumb", "level": 1}
        assert buttons[1].id == {"type": "drill-breadcrumb", "level": 2}


class TestEscapeToOverview:
    def test_empty_map_click_resets_way_back_to_level_one(self, _assets):
        # Drilled into an empty region (no units, no districts to click).
        state = next_drill_state(LEVEL_1, "Hessen")
        state = next_drill_state(state, "Kassel")
        assert state["level"] == 3
        # A click on the sea fetches no area name -> back to the whole country.
        assert state_after_click(state, None, was_map_click=True) == overview_state(
            CAPACITY_MW
        )

    def test_empty_map_click_recenters_on_germany(self, _assets):
        state = state_after_click(LEVEL_1, "Hessen", was_map_click=True)
        assert state["centre"] == (5.5, 49.5)
        assert state_after_click(state, None, was_map_click=True)["centre"] == OVERVIEW_CENTRE

    def test_reset_keeps_the_metric_toggle(self, _assets):
        state = dict(LEVEL_1, metric=UNIT_COUNT)
        assert state_after_click(state, None, was_map_click=True)["metric"] == UNIT_COUNT

    def test_overview_state_preserves_the_metric(self):
        assert overview_state(UNIT_COUNT)["metric"] == UNIT_COUNT
        assert overview_state(UNIT_COUNT)["level"] == 1
        assert overview_state(UNIT_COUNT)["parent_filters"] == {}
        assert overview_state(UNIT_COUNT)["centre"] == OVERVIEW_CENTRE

    def test_no_click_keeps_the_drill_state(self, _assets):
        state = dict(LEVEL_1, metric=UNIT_COUNT)
        assert state_after_click(state, None, was_map_click=False) is not None
        assert state_after_click(state, None, was_map_click=False) == state

    def test_area_click_still_drills_through_state_after_click(self, _assets):
        state = state_after_click(LEVEL_1, "Hessen", was_map_click=True)
        assert state["level"] == 2
        assert state["parent_filters"] == {"region": "Hessen"}


class TestFigureStateSeam:
    def test_breadcrumb_trigger_renders_target_state_regardless_of_stale_store(self, _assets):
        drilled = {"level": 3, "parent_filters": {"region": "Hessen", "district": "Kassel"}, "metric": CAPACITY_MW}
        # Store may still hold the drilled level-3 state when Dash batches the
        # breadcrumb click with the figure rebuild; the trigger, not the store,
        # wins.
        state = figure_state(drilled, CAPACITY_MW, {"type": "drill-breadcrumb", "level": 1})
        assert state == overview_state(CAPACITY_MW)

    def test_breadcrumb_trigger_preserves_the_metric(self, _assets):
        drilled = {"level": 3, "parent_filters": {"region": "Hessen", "district": "Kassel"}, "metric": UNIT_COUNT}
        state = figure_state(drilled, UNIT_COUNT, {"type": "drill-breadcrumb", "level": 2})
        assert state["metric"] == UNIT_COUNT
        assert state["level"] == 2

    def test_map_click_trigger_uses_the_store(self):
        drilled = {"level": 2, "parent_filters": {"region": "Hessen"}}
        state = figure_state(drilled, UNIT_COUNT, "drill-state.data")
        assert state["level"] == 2
        assert state["parent_filters"] == {"region": "Hessen"}
        assert state["metric"] == UNIT_COUNT

    def test_initial_render_uses_the_initial_state(self):
        state = figure_state(None, CAPACITY_MW, None)
        assert state == INITIAL_STATE or state["level"] == 1


class TestStandbyMap:
    def test_standby_map_renders_osm_basemap_without_traces(self):
        from viz.app import _standby_map

        data = _standby_map(dict(LEVEL_1, centre=OVERVIEW_CENTRE))
        assert data["layout"]["map"]["style"] == "open-street-map"
        assert data["data"] == []
        assert data["layout"]["map"]["center"] == {
            "lat": OVERVIEW_CENTRE[1],
            "lon": OVERVIEW_CENTRE[0],
        }

    def test_render_falls_back_to_standby_without_core_tables(self, monkeypatch):
        import viz.app as viz_app
        from viz.data import CoreTablesMissing

        def _missing(state):
            raise CoreTablesMissing(["generators"])

        monkeypatch.setattr(viz_app, "_build_map", _missing)
        data = viz_app._render_figure(dict(LEVEL_1, centre=OVERVIEW_CENTRE))
        assert data["layout"]["map"]["style"] == "open-street-map"
        assert data["data"] == []


class TestCoreTablesMessage:
    def test_message_lists_missing_table_names(self):
        from dash import html

        items = core_tables_message(["generators", "storages"])
        assert len(items) == 2
        names_text = items[0].children
        assert "core.generators" in names_text
        assert "core.storages" in names_text

    def test_message_includes_load_command(self):
        items = core_tables_message(["generators"])
        assert "python -m etl load" in items[1].children


class TestMissingCoreTables:
    def test_returns_empty_when_all_present(self, monkeypatch):
        from sqlalchemy import create_engine

        monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
        engine = create_engine("sqlite:///:memory:")

        class FakeInspector:
            def has_table(self, name, schema=None):
                return True

        import viz.data as vd

        monkeypatch.setattr(vd, "inspect", lambda engine: FakeInspector())
        assert missing_core_tables(engine) == []

    def test_returns_absent_tables(self, monkeypatch):
        from sqlalchemy import create_engine

        engine = create_engine("sqlite:///:memory:")

        class FakeInspector:
            def has_table(self, name, schema=None):
                return False

        import viz.data as vd

        monkeypatch.setattr(vd, "inspect", lambda engine: FakeInspector())
        assert sorted(missing_core_tables(engine)) == ["generators", "storages"]
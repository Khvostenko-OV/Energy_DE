"""Unit tests for the app's drill-state seam (issue #19).

`next_drill_state` maps a choropleth click (a `location` string from
Dash's ``clickData``) onto the next active drill state without touching Dash,
the database, or the figure runtime.  The model under test is the boundary
GeoJSON, which arrives via `viz.data.load_level_geojson`; we monkeypatch it so
these tests stay disk-free and deterministic.
"""

import pytest

from viz.app import INITIAL_STATE, next_drill_state
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
        assert state == dict(INITIAL_STATE, metric=CAPACITY_MW)

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
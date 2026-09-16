"""Unit tests for the choropleth fill-layer figure seam (issue #19).

The fill layer renders *beneath* the cluster scatter traces, colored by the
live per-area value for the active drill level.  Mirroring the drill seam, the
geometry→area mapping is metric-agnostic: only the value coloring and hover
unit differ between the installed-capacity MW sum (default) and the unit count
(toggle).  All tests run on synthetic per-level GeoJSON + a synthetic fills
frame (no database, no Dash runtime, no boundary assets on disk).
"""

import pandas as pd
import plotly.graph_objects as go
import pytest

from viz.drill import CAPACITY_MW, UNIT_COUNT
from viz.figure import add_choropleth_fill, build_units_map

HES = "Hessen"
NDS = "Niedersachsen"
BAY = "Bayern"

LEVEL_1_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": HES},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[8.0, 49.0], [8.0, 51.0], [10.0, 51.0], [10.0, 49.0], [8.0, 49.0]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": NDS},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[10.0, 51.0], [10.0, 54.0], [14.0, 54.0], [14.0, 51.0], [10.0, 51.0]]],
            },
        },
        {
            "type": "Feature",
            "properties": {"name": BAY},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[10.0, 47.0], [10.0, 50.0], [14.0, 50.0], [14.0, 47.0], [10.0, 47.0]]],
            },
        },
    ],
}

LEVEL_2_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {"name": "Kassel"},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[8.0, 51.0], [8.0, 52.0], [10.0, 52.0], [10.0, 51.0], [8.0, 51.0]]],
            },
        },
    ],
}


def _fills(frame, names, values):
    return frame.assign(name=names, value=values)


def _empty_figure():
    return build_units_map(
        pd.DataFrame(
            {
                "longitude": [10.5],
                "latitude": [50.5],
                "energy_source": ["wind"],
                "installed_capacity": [3000.0],
                "commissioning_date": ["2015-01-01"],
                "decommissioning_date": [None],
                "region": [HES],
                "district": ["Kassel"],
                "municipality": ["Kassel"],
            }
        ),
        pd.DataFrame(),
    )


def _find_trace(fig, trace_type):
    return [t for t in fig.data if t.type == trace_type][0]


# ------------------------------------------------------------------ #
#  The fill layer is a choropleth beneath the scatter                 #
# ------------------------------------------------------------------ #


class TestFillLayerIsBeneathTheScatter:
    def test_choropleth_is_added_beneath_the_scatter_traces(self):
        fig = _empty_figure()
        fills = _fills(pd.DataFrame(), [HES, NDS, BAY], [1200.0, 3000.0, 500.0])
        add_choropleth_fill(fig, LEVEL_1_GEOJSON, fills, CAPACITY_MW)

        assert fig.data[0].type == "choroplethmap"
        assert [t.type for t in fig.data[1:]] == ["scattermap"]

    def test_layer_carries_the_level_geojson_and_area_names(self):
        fig = _empty_figure()
        fills = _fills(pd.DataFrame(), [HES, NDS, BAY], [1200.0, 3000.0, 500.0])
        add_choropleth_fill(fig, LEVEL_1_GEOJSON, fills, CAPACITY_MW)
        layer = _find_trace(fig, "choroplethmap")
        assert layer.geojson == LEVEL_1_GEOJSON
        assert list(layer.locations) == [HES, NDS, BAY]
        assert layer.featureidkey == "properties.name"

    def test_fill_value_matches_the_fills_frame(self):
        fig = _empty_figure()
        fills = _fills(pd.DataFrame(), [HES, NDS, BAY], [1200.0, 3000.0, 500.0])
        add_choropleth_fill(fig, LEVEL_1_GEOJSON, fills, CAPACITY_MW)
        layer = _find_trace(fig, "choroplethmap")
        assert list(layer.z) == [1200.0, 3000.0, 500.0]

    def test_missing_region_keeps_its_fill_but_renders_transparent(self):
        fig = _empty_figure()
        fills = _fills(pd.DataFrame(), [HES, NDS], [1200.0, 3000.0])
        add_choropleth_fill(fig, LEVEL_1_GEOJSON, fills, CAPACITY_MW)
        layer = _find_trace(fig, "choroplethmap")
        assert set(layer.locations) == {HES, NDS}


# ------------------------------------------------------------------ #
#  Metric only affects value coloring + hover unit                    #
# ------------------------------------------------------------------ #


class TestMetricChangesValueOnly:
    def test_capacity_metric_colors_by_megawatts_with_mw_hover(self):
        fig = _empty_figure()
        fills = _fills(pd.DataFrame(), [HES], [1.2])
        add_choropleth_fill(fig, LEVEL_1_GEOJSON, fills, CAPACITY_MW)
        layer = _find_trace(fig, "choroplethmap")
        assert list(layer.z) == [1.2]
        assert "MW" in layer.hovertemplate
        assert "units" not in layer.hovertemplate.lower()

    def test_unit_count_metric_colors_by_count(self):
        fig = _empty_figure()
        fills = _fills(pd.DataFrame(), [HES], [12])
        add_choropleth_fill(fig, LEVEL_1_GEOJSON, fills, UNIT_COUNT)
        layer = _find_trace(fig, "choroplethmap")
        assert list(layer.z) == [12]

    def test_district_level_geometry_is_used_at_level_two(self):
        fig = _empty_figure()
        fills = _fills(pd.DataFrame(), ["Kassel"], [25])
        add_choropleth_fill(fig, LEVEL_2_GEOJSON, fills, UNIT_COUNT)
        layer = _find_trace(fig, "choroplethmap")
        assert layer.geojson == LEVEL_2_GEOJSON
        assert list(layer.locations) == ["Kassel"]

    def test_unknown_metric_is_rejected(self):
        with pytest.raises(ValueError):
            add_choropleth_fill(
                _empty_figure(), LEVEL_1_GEOJSON, _fills(pd.DataFrame(), [HES], [1]), "watts"
            )


# ------------------------------------------------------------------ #
#  The value frame is metric-agnostic by shape                        #
# ------------------------------------------------------------------ #


class TestFillFrameShape:
    def test_value_frame_just_needs_name_and_value(self):
        fig = _empty_figure()
        fills = pd.DataFrame({"name": [HES], "value": [9.5]})
        add_choropleth_fill(fig, LEVEL_1_GEOJSON, fills, CAPACITY_MW)
        layer = _find_trace(fig, "choroplethmap")
        assert list(layer.z) == [9.5]

    def test_no_fills_still_adds_an_empty_layer(self):
        fig = _empty_figure()
        add_choropleth_fill(fig, LEVEL_1_GEOJSON, pd.DataFrame(), CAPACITY_MW)
        layer = _find_trace(fig, "choroplethmap")
        assert isinstance(layer, go.Choroplethmap)
        assert list(layer.z) == []
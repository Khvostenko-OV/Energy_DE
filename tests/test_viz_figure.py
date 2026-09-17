"""Unit tests for the scatter-map figure builder (issue #18).

Exercise `build_units_map` on synthetic DataFrames (no database): trace layout
(one trace per energy source), palette color lookup, storage marker
assignment, clustering, and the open-street-map basemap.
"""

import pandas as pd
import plotly.graph_objects as go
import pytest

from viz.figure import CLUSTER_STEP, GERMANY_CENTER, INITIAL_ZOOM, build_units_map
from viz.palette import DEFAULT_COLOR, ENERGY_COLORS, MARKER_SYMBOL

GENERATOR_COLUMNS = (
    "longitude",
    "latitude",
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "region",
    "district",
    "municipality",
)


def _generator_row(source="wind", capacity=1000.0):
    return {
        "longitude": 10.5,
        "latitude": 50.5,
        "energy_source": source,
        "installed_capacity": capacity,
        "commissioning_date": "2015-01-01",
        "decommissioning_date": None,
        "region": "Hessen",
        "district": "Kassel",
        "municipality": "Kassel",
    }


def _storage_row(capacity=500.0):
    return {
        **_generator_row(source="storage", capacity=300.0),
        "storage_capacity": capacity,
    }


def _generators(*sources):
    rows = [_generator_row(source=s) for s in sources] or [_generator_row()]
    return pd.DataFrame(rows)


def _storages():
    return pd.DataFrame([_storage_row()])


def _trace_by_name(fig, name):
    return next(t for t in fig.data if t.name == name)


# ------------------------------------------------------------------ #
#  Trace structure                                                    #
# ------------------------------------------------------------------ #


class TestTraces:
    def test_build_units_map_returns_plotly_figure(self):
        fig = build_units_map(_generators("bio", "wind"), _storages())
        assert isinstance(fig, go.Figure)
        assert all(trace.type == "scattermap" for trace in fig.data)

    def test_one_trace_per_energy_source(self):
        fig = build_units_map(_generators("bio", "wind"), _storages())
        assert {t.name for t in fig.data} == {"Bio", "Wind", "Storage"}

    def test_trace_plots_the_sources_points(self):
        gens = pd.DataFrame(
            [_generator_row(source="solar", capacity=10.0)]
            + [
                dict(_generator_row(source="solar", capacity=20.0), longitude=8.1, latitude=49.3)
            ]
        )
        fig = build_units_map(gens, _storages())
        trace = _trace_by_name(fig, "Solar")
        assert list(trace.lon) == [10.5, 8.1]
        assert list(trace.lat) == [50.5, 49.3]

    def test_empty_frames_build_a_valid_figure(self):
        fig = build_units_map(pd.DataFrame(), pd.DataFrame())
        assert isinstance(fig, go.Figure)
        assert fig.data == ()
        assert fig.layout.map.style == "open-street-map"


# ------------------------------------------------------------------ #
#  Palette lookup                                                     #
# ------------------------------------------------------------------ #


class TestPalette:
    def test_palette_covers_all_seven_categories(self):
        assert set(ENERGY_COLORS) == {
            "bio", "gas", "hydro", "solar", "wind", "diesel", "storage",
        }

    def test_palette_lookup_colors_traces(self):
        fig = build_units_map(_generators("bio", "wind"), _storages())
        colors = {t.name.lower(): t.marker.color for t in fig.data}
        assert colors["bio"] == ENERGY_COLORS["bio"]
        assert colors["wind"] == ENERGY_COLORS["wind"]
        assert colors["storage"] == ENERGY_COLORS["storage"]

    def test_unknown_source_falls_back_to_default_color(self):
        gens = _generators("bio")
        gens["energy_source"] = "geothermal"
        fig = build_units_map(gens, _storages())
        trace = _trace_by_name(fig, "Geothermal")
        assert trace.marker.color == DEFAULT_COLOR

    def test_unknown_source_keeps_the_shared_circle_marker(self):
        storages = _storages()
        storages["energy_source"] = "geothermal"
        fig = build_units_map(_generators(), storages)
        trace = _trace_by_name(fig, "Geothermal")
        assert trace.marker.symbol == MARKER_SYMBOL


# ------------------------------------------------------------------ #
#  Marker symbol                                                      #
# ------------------------------------------------------------------ #


class TestMarkers:
    def test_all_traces_use_the_shared_circle_symbol(self):
        # MapLibre's scattermap only honors marker.color for "circle", so every
        # trace renders circles; storages differ by color (#4e342e) instead.
        fig = build_units_map(_generators("bio", "wind"), _storages())
        assert fig.data
        for trace in fig.data:
            assert trace.marker.symbol == MARKER_SYMBOL
        assert MARKER_SYMBOL == "circle"

    def test_layers_stack_bottom_to_top_storage_then_bio_on_top(self):
        # Plotly paints later traces over earlier ones, so the trace order IS
        # the paint stack: storage at the bottom, then wind, solar, hydro, gas,
        # and bio on the very top.
        fig = build_units_map(
            _generators("bio", "gas", "hydro", "solar", "wind"), _storages()
        )
        assert [t.name for t in fig.data] == [
            "Storage", "Wind", "Solar", "Hydro", "Gas", "Bio",
        ]

    def test_legend_reads_bio_down_to_storage(self):
        # The map legend renders the paint stack reversed, so the sidebar
        # starts with bio on top and ends with storage at the bottom.
        fig = build_units_map(
            _generators("bio", "gas", "hydro", "solar", "wind"), _storages()
        )
        assert fig.layout.legend.traceorder == "reversed"
        assert fig.layout.legend.x == 0
        assert fig.layout.legend.xanchor == "left"
        sidebar = list(reversed([t.name for t in fig.data]))
        assert sidebar == ["Bio", "Gas", "Hydro", "Solar", "Wind", "Storage"]


# ------------------------------------------------------------------ #
#  Clustering + basemap                                               #
# ------------------------------------------------------------------ #


class TestMap:
    def test_clustering_enabled_on_every_trace(self):
        fig = build_units_map(_generators("bio", "wind"), _storages())
        assert fig.data
        for trace in fig.data:
            assert trace.cluster.enabled
            assert trace.cluster.step == CLUSTER_STEP

    def test_open_street_map_basemap_centered_on_germany(self):
        fig = build_units_map(_generators(), _storages())
        assert fig.layout.map.style == "open-street-map"
        assert fig.layout.map.center.lat == GERMANY_CENTER["lat"]
        assert fig.layout.map.center.lon == GERMANY_CENTER["lon"]
        assert fig.layout.map.zoom == INITIAL_ZOOM


# ------------------------------------------------------------------ #
#  Hover text                                                         #
# ------------------------------------------------------------------ #


class TestHover:
    def test_one_hovercard_per_unit(self):
        fig = build_units_map(_generators("bio", "wind"), _storages())
        total = sum(len(trace.hovertext) for trace in fig.data)
        assert total == 3

    def test_generator_hovercard_names_kilowatts(self):
        fig = build_units_map(_generators("bio"), _storages())
        hover = _trace_by_name(fig, "Bio").hovertext
        assert "Installed capacity: 1 000.0 kW" in hover[0]
        assert "Commissioned: 2015-01-01" in hover[0]
        assert "Decommissioned: active" in hover[0]
        assert "Hessen · Kassel · Kassel" in hover[0]

    def test_storage_hovercard_names_both_capacities(self):
        fig = build_units_map(_generators(), _storages())
        hover = _trace_by_name(fig, "Storage").hovertext
        assert "Storage capacity: 500.0 kWh" in hover[0]
        assert "Installed capacity: 300.0 kW" in hover[0]
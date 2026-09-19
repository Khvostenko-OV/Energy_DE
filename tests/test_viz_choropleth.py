"""Unit tests for the choropleth seam (issue #26).

`viz.choropleth` turns the boundary/fill rows the app fetches into what the
GeoJsonLayer renders: a capacity-based rgba fill per area (`fill_color`) and
a GeoJSON FeatureCollection whose features carry that fill plus the hover
fields (`areas_feature_collection`).  Both are pure: synthetic boundary rows
carry raw `ST_AsGeoJSON` text, synthetic fill rows carry per-area capacity
(MW) and unit counts, and the join happens by area name.
"""

import json

from viz.choropleth import ZERO_FILL, areas_feature_collection, fill_color


def boundary_row(name, geojson):
    return {"name": name, "geojson": json.dumps(geojson)}


def polygon_feature(geometry):
    return {"type": "Feature", "geometry": geometry, "properties": {"name": "Berlin"}}


# A 2x2 degree square around (10, 50), as a GeoJSON MultiPolygon.
BERLIN_GEOMETRY = {
    "type": "MultiPolygon",
    "coordinates": [[[[9.0, 49.0], [11.0, 49.0], [11.0, 51.0], [9.0, 51.0], [9.0, 49.0]]]],
}

HAMBURG_GEOMETRY = {
    "type": "Polygon",
    "coordinates": [[[8.0, 53.0], [10.0, 53.0], [10.0, 54.0], [8.0, 54.0], [8.0, 53.0]]],
}


class TestFillColor:
    def test_max_capacity_area_paints_the_ramp_high_end(self):
        high = fill_color(500.0, 500.0)
        assert high[3] == 255  # fully opaque
        assert high[0] <= 60  # steep (dark) end of the blue ramp

    def test_zero_capacity_area_paints_no_fill(self):
        assert fill_color(0.0, 500.0) == ZERO_FILL

    def test_degenerate_max_paints_no_fill(self):
        assert fill_color(10.0, 0.0) == ZERO_FILL
        assert fill_color(0.0, 0.0) == ZERO_FILL

    def test_fill_is_more_saturated_as_capacity_grows(self):
        low = fill_color(50.0, 500.0)
        high = fill_color(500.0, 500.0)
        assert high[0] < low[0]
        assert high[2] > low[2]

    def test_partial_capacity_scales_into_the_ramp(self):
        color = fill_color(250.0, 500.0)
        assert isinstance(color, tuple)
        assert len(color) == 4
        assert all(isinstance(part, int) for part in color)

    def test_capacity_beyond_the_max_is_clamped(self):
        assert fill_color(900.0, 500.0) == fill_color(500.0, 500.0)


class TestAreasFeatureCollection:
    def test_one_feature_per_boundary_row_joined_by_name(self):
        rows = [boundary_row("Berlin", BERLIN_GEOMETRY)]
        fills = [{"name": "Berlin", "capacity_mw": 1200.0, "unit_count": 40}]
        features = areas_feature_collection(rows, fills)["features"]
        assert len(features) == 1
        assert features[0]["type"] == "Feature"
        assert features[0]["geometry"] == BERLIN_GEOMETRY
        assert features[0]["properties"]["name"] == "Berlin"

    def test_fill_values_flow_into_the_feature_properties(self):
        rows = [boundary_row("Berlin", BERLIN_GEOMETRY)]
        fills = [{"name": "Berlin", "capacity_mw": 1200.0, "unit_count": 40}]
        props = areas_feature_collection(rows, fills)["features"][0]["properties"]
        assert props["capacity_mw"] == 1200.0
        assert props["unit_count"] == 40

    def test_hover_card_field_pairs_are_prebuilt(self):
        rows = [boundary_row("Berlin", BERLIN_GEOMETRY)]
        fills = [{"name": "Berlin", "capacity_mw": 12345.6, "unit_count": 40}]
        props = areas_feature_collection(rows, fills)["features"][0]["properties"]
        assert props["source_header"] == "Berlin"
        assert "Capacity: 12,346 MW" in props["unit_body"]
        assert "Units: 40" in props["unit_body"]

    def test_fill_color_is_injected_per_feature(self):
        rows = [
            boundary_row("Berlin", BERLIN_GEOMETRY),
            boundary_row("Hamburg", HAMBURG_GEOMETRY),
        ]
        fills = [
            {"name": "Berlin", "capacity_mw": 500.0, "unit_count": 40},
            {"name": "Hamburg", "capacity_mw": 50.0, "unit_count": 3},
        ]
        collection = areas_feature_collection(rows, fills)
        props = {f["properties"]["name"]: f["properties"] for f in collection["features"]}
        assert props["Berlin"]["fill_color"] == fill_color(500.0, 500.0)
        assert props["Hamburg"]["fill_color"] == fill_color(50.0, 500.0)

    def test_area_without_fill_rows_renders_no_fill(self):
        rows = [boundary_row("Berlin", BERLIN_GEOMETRY)]
        props = areas_feature_collection(rows, [])["features"][0]["properties"]
        assert props["capacity_mw"] == 0.0
        assert props["unit_count"] == 0
        assert props["fill_color"] == ZERO_FILL

    def test_unmatched_fill_rows_are_dropped(self):
        rows = [boundary_row("Berlin", BERLIN_GEOMETRY)]
        fills = [
            {"name": "Berlin", "capacity_mw": 1.0, "unit_count": 1},
            {"name": "Phantom", "capacity_mw": 999.0, "unit_count": 9},
        ]
        names = [f["properties"]["name"] for f in areas_feature_collection(rows, fills)["features"]]
        assert names == ["Berlin"]

    def test_feature_order_follows_the_boundary_rows(self):
        rows = [
            boundary_row("Hamburg", HAMBURG_GEOMETRY),
            boundary_row("Berlin", BERLIN_GEOMETRY),
        ]
        fills = [
            {"name": "Berlin", "capacity_mw": 1.0, "unit_count": 1},
            {"name": "Hamburg", "capacity_mw": 2.0, "unit_count": 2},
        ]
        names = [f["properties"]["name"] for f in areas_feature_collection(rows, fills)["features"]]
        assert names == ["Hamburg", "Berlin"]

    def test_result_is_a_feature_collection(self):
        rows = []
        assert areas_feature_collection(rows, []) == {
            "type": "FeatureCollection",
            "features": [],
        }

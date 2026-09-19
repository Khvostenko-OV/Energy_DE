"""Unit tests for the viewport/camera seams (issue #26).

Three pure seams in `viz.viewport`: `geometry_points` flattens a GeoJSON
(Polygon/MultiPolygon) geometry into (lon, lat) pairs, `fit_viewstate` reduces
a point cloud to the (lon, lat, zoom) view that shows the whole bounding box,
and `should_refit` decides when the stored camera must be replaced (level or
area selection changed, or nothing stored yet) versus preserved across reruns
(source/timescope changes).  No database and no deck involved.
"""

import math

from viz.config import GERMANY_CENTER, INITIAL_ZOOM
from viz.viewport import (
    FIT_HEIGHT_PX,
    FIT_WIDTH_PX,
    MAX_FIT_ZOOM,
    MIN_FIT_ZOOM,
    _mercator_y,
    fit_viewstate,
    geometry_points,
    should_refit,
)

POLYGON = {
    "type": "Polygon",
    "coordinates": [[[10.0, 50.0], [12.0, 50.0], [12.0, 52.0], [10.0, 52.0], [10.0, 50.0]]],
}

MULTIPOLYGON = {
    "type": "MultiPolygon",
    "coordinates": [
        [[[10.0, 50.0], [11.0, 50.0], [11.0, 51.0], [10.0, 51.0], [10.0, 50.0]]],
        [[[5.0, 53.0], [6.0, 53.0], [6.0, 54.0], [5.0, 54.0], [5.0, 53.0]]],
    ],
}


class TestGeometryPoints:
    def test_polygon_rings_flatten_to_lon_lat_pairs(self):
        points = geometry_points(POLYGON)
        assert points[0] == (10.0, 50.0)
        assert points[-1] == (10.0, 50.0)
        assert len(points) == 5

    def test_multipolygon_flattens_every_polygon(self):
        points = geometry_points(MULTIPOLYGON)
        assert len(points) == 10
        assert (10.0, 50.0) in points
        assert (5.0, 53.0) in points

    def test_coordinates_with_elevation_keep_lon_lat(self):
        geometry = {
            "type": "Polygon",
            "coordinates": [[[10.0, 50.0, 200.0], [11.0, 50.0, 200.0]]],
        }
        assert geometry_points(geometry) == [(10.0, 50.0), (11.0, 50.0)]

    def test_unknown_geometry_types_yield_no_points(self):
        assert geometry_points({"type": "Point", "coordinates": [10.0, 50.0]}) == []


class TestFitViewstate:
    def test_empty_points_fall_back_to_the_germany_overview(self):
        view = fit_viewstate([])
        assert view["lon"] == GERMANY_CENTER["lon"]
        assert view["lat"] == GERMANY_CENTER["lat"]
        assert view["zoom"] == INITIAL_ZOOM

    def test_centers_on_the_bounding_box_midpoint(self):
        view = fit_viewstate([(10.0, 50.0), (12.0, 52.0)])
        assert view["lon"] == 11.0
        assert view["lat"] == 51.0

    def test_zoom_fits_both_spans(self):
        points = [(10.0, 50.0), (112.0, 52.0)]  # 102° lon, 2° lat
        view = fit_viewstate(points)
        # The narrower lat span would allow a higher zoom; lon wins → lower zoom.
        assert MIN_FIT_ZOOM <= view["zoom"] <= MAX_FIT_ZOOM

    def test_bigger_bbox_means_more_zoomed_out(self):
        small = fit_viewstate([(10.0, 50.0), (11.0, 51.0)])
        big = fit_viewstate([(6.0, 47.0), (15.0, 54.0)])
        assert big["zoom"] < small["zoom"]

    def test_zoom_fits_the_whole_country(self):
        country = fit_viewstate([(5.5, 47.0), (15.5, 55.0)])
        assert MIN_FIT_ZOOM <= country["zoom"] < 8

    def test_zooming_in_raw_points_is_capped(self):
        view = fit_viewstate([(10.0, 50.0), (10.001, 51.0)])
        assert view["zoom"] <= MAX_FIT_ZOOM

    def test_vertical_strip_fits_the_latitude_axis(self):
        points = [(10.0, 50.0), (10.0, 52.0)]  # all on one longitude
        view = fit_viewstate(points)
        assert view["lon"] == 10.0
        assert view["lat"] == 51.0
        assert MIN_FIT_ZOOM <= view["zoom"] <= MAX_FIT_ZOOM

    def test_horizontal_strip_fits_the_longitude_axis(self):
        points = [(10.0, 50.0), (12.0, 50.0)]  # all on one latitude
        view = fit_viewstate(points)
        assert view["lon"] == 11.0
        assert view["lat"] == 50.0
        assert MIN_FIT_ZOOM <= view["zoom"] <= MAX_FIT_ZOOM

    def test_single_point_zooms_to_max(self):
        view = fit_viewstate([(10.0, 50.0)])
        assert view == {"lon": 10.0, "lat": 50.0, "zoom": MAX_FIT_ZOOM}

    def test_fitted_bbox_occupies_at_most_half_the_nominal_window(self):
        # FIT_ZOOM_OUT backs the fitted zoom out by a couple of full zoom
        # levels, so the whole selected bbox — whose web-mercator pixel extent
        # halves with each zoom step — ends up well inside (at most a quarter
        # of) the assumed FIT_WIDTH_PX x FIT_HEIGHT_PX window.  This is the
        # "zoom out to see the scope" behavior the user asked for.
        for points in (
            [(5.0, 47.0), (15.5, 54.0)],  # wide bbox -> width-limited fit
            [(10.0, 47.0), (11.0, 55.0)],  # tall bbox -> height-limited fit
            [(10.0, 50.0), (12.0, 52.0)],  # proportioned bbox
        ):
            view = fit_viewstate(points)
            lons = [point[0] for point in points]
            lats = [point[1] for point in points]
            x_px = (max(lons) - min(lons)) / 360.0 * 256.0 * (2.0 ** view["zoom"])
            mercator_span = _mercator_y(max(lats)) - _mercator_y(min(lats))
            y_px = mercator_span / (2.0 * math.pi) * 256.0 * (2.0 ** view["zoom"])
            assert x_px <= FIT_WIDTH_PX / 2 + 1e-6
            assert y_px <= FIT_HEIGHT_PX / 2 + 1e-6


class TestShouldRefit:
    def test_no_stored_camera_always_refits(self):
        assert should_refit(None, None, level_label="Regions", area_names=["Berlin"]) is True

    def test_unchanged_level_and_areas_preserve_the_camera(self):
        stored = {"lon": 10.0, "lat": 50.0, "zoom": 8.0}
        scope = ("Regions", ("Berlin", "Hamburg"))
        assert (
            should_refit(stored, scope, level_label="Regions", area_names=["Hamburg", "Berlin"])
            is False
        )

    def test_level_change_replaces_the_camera(self):
        stored = {"lon": 10.0, "lat": 50.0, "zoom": 8.0}
        scope = ("Regions", ("Berlin",))
        assert should_refit(stored, scope, level_label="Districts", area_names=["Berlin"]) is True

    def test_area_selection_change_replaces_the_camera(self):
        stored = {"lon": 10.0, "lat": 50.0, "zoom": 8.0}
        scope = ("Regions", ("Berlin",))
        assert (
            should_refit(stored, scope, level_label="Regions", area_names=["Berlin", "Hamburg"])
            is True
        )

    def test_area_order_does_not_matter(self):
        stored = {"lon": 10.0, "lat": 50.0, "zoom": 8.0}
        scope = ("Regions", ("Berlin", "Hamburg"))
        assert (
            should_refit(stored, scope, level_label="Regions", area_names=["Hamburg", "Berlin"])
            is False
        )

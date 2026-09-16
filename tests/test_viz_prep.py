"""Tests for the boundary GeoJSON prep (issue #17).

Unit tests exercise the raw simplification function on synthetic polygons
(no DB); integration tests run the full generation against the live dev
PostGIS and assert level coverage + geometry validity of the generated files.
"""

import json
import math
import os

import geopandas as gpd
import numpy
import pytest
import shapely
from sqlalchemy import create_engine, text

from etl.db_schema import BOUNDARY_GEOJSON_FILES, SERVICE_SCHEMA
from etl.viz_prep import ROUND_DECIMALS, _simplify_geometry, generate_boundaries_geojson
from etl.verify import _verify_viz_prep

ENGINE = create_engine(os.environ["DATABASE_URL"])


def _spiky_polygon(points: int = 3000, radius: float = 1.0, amplitude: float = 0.1) -> shapely.geometry.Polygon:
    """Synthetic polygon: a ring of spikey vertices Douglas-Peucker should collapse."""
    coords = []
    for i in range(points):
        angle = 2 * math.pi * i / points
        radial = radius + amplitude * math.sin(angle * 40)
        coords.append((math.cos(angle) * radial, math.sin(angle) * radial))
    return shapely.geometry.Polygon(coords)


# ------------------------------------------------------------------ #
#  Unit tests — simplification on synthetic polygons (no DB)          #
# ------------------------------------------------------------------ #


def test_simplify_reduces_vertex_count():
    original = _spiky_polygon()
    simplified = _simplify_geometry(original)

    assert simplified.is_valid
    assert shapely.get_num_coordinates(simplified) < shapely.get_num_coordinates(original)


def test_simplify_rounds_coordinates_to_six_decimals():
    simplified = _simplify_geometry(_spiky_polygon(points=200))

    coords = shapely.get_coordinates(simplified)
    assert numpy.allclose(coords[:, :2], numpy.round(coords[:, :2], ROUND_DECIMALS))


def test_simplify_preserves_gross_shape():
    original = _spiky_polygon()
    simplified = _simplify_geometry(original)

    assert simplified.is_valid
    assert simplified.intersection(original).area >= 0.8 * original.area
    assert simplified.envelope.contains_properly(shapely.geometry.Point(0, 0))


def test_simplify_handles_multipolygon():
    part_a = shapely.geometry.Polygon([(0, 0), (0, 1), (1, 1), (1, 0), (0, 0)])
    part_b = shapely.affinity.translate(_spiky_polygon(points=500), 5, 5)
    multi = shapely.geometry.MultiPolygon([part_a, part_b])

    simplified = _simplify_geometry(multi)

    assert simplified.geom_type == "MultiPolygon"
    assert simplified.is_valid
    assert shapely.get_num_coordinates(simplified) < shapely.get_num_coordinates(multi)


def test_simplified_geojson_file_size_is_bounded(tmp_path):
    original = _spiky_polygon(points=3000, amplitude=0.15)
    simplified = _simplify_geometry(original)

    raw_path = tmp_path / "raw.geojson"
    out_path = tmp_path / "simplified.geojson"
    gpd.GeoDataFrame(
        {"name": ["probe"]}, geometry=[original], crs="EPSG:4326"
    ).to_file(raw_path, driver="GeoJSON")
    gpd.GeoDataFrame(
        {"name": ["probe"]}, geometry=[simplified], crs="EPSG:4326"
    ).to_file(out_path, driver="GeoJSON")

    raw_size = raw_path.stat().st_size
    simplified_size = out_path.stat().st_size
    assert raw_size > 20_000
    assert simplified_size < 10_000
    assert simplified_size < raw_size


# ------------------------------------------------------------------ #
#  Integration tests — live DB (service.boundaries levels 1-3)        #
# ------------------------------------------------------------------ #


@pytest.fixture(scope="module", autouse=True)
def _staging_ready(_staged_sources):
    """Staging is transformed once per session; transform requires boundaries to be
    loaded (a missing service.boundaries fails its precondition in conftest)."""


def _db_count(level: int) -> int:
    with ENGINE.connect() as conn:
        return int(
            conn.execute(
                text(f"SELECT COUNT(*) FROM {SERVICE_SCHEMA}.boundaries WHERE level = :level"),
                {"level": level},
            ).scalar()
        )


def test_generation_report_passes_and_writes_all_levels(tmp_path):
    report = generate_boundaries_geojson(tmp_path)

    assert report.passed, report.errors
    assert report.files == list(BOUNDARY_GEOJSON_FILES.values())
    assert report.features_by_level == {1: _db_count(1), 2: _db_count(2), 3: _db_count(3)}
    for path in BOUNDARY_GEOJSON_FILES.values():
        assert (tmp_path / path).is_file()


def test_feature_counts_match_service_boundaries(tmp_path):
    generate_boundaries_geojson(tmp_path)

    for level, filename in BOUNDARY_GEOJSON_FILES.items():
        data = json.loads((tmp_path / filename).read_text())
        assert len(data["features"]) == _db_count(level), filename


def test_generated_geometries_are_valid(tmp_path):
    generate_boundaries_geojson(tmp_path)
    assert _verify_viz_prep(ENGINE, tmp_path) == []

    for level, filename in BOUNDARY_GEOJSON_FILES.items():
        gdf = gpd.read_file(tmp_path / filename)
        assert len(gdf) == _db_count(level)
        assert gdf.geometry.is_valid.all(), f"invalid geometry in {filename}"
        assert gdf.geometry.is_empty.sum() == 0, f"empty geometry in {filename}"


def test_verify_detects_missing_feature(tmp_path):
    generate_boundaries_geojson(tmp_path)

    path = tmp_path / BOUNDARY_GEOJSON_FILES[1]
    data = json.loads(path.read_text())
    data["features"] = data["features"][:-1]
    path.write_text(json.dumps(data))

    errors = _verify_viz_prep(ENGINE, tmp_path)
    assert any("Level 1 feature count mismatch" in e for e in errors)
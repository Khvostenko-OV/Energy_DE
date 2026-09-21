"""Extract-stage seams (issue #33): source discovery and boundary level checks.

The extract CLI discovers unit sources by filename inside a folder and the
boundary load reads its level from the gpkg data. These are the folder-driven
and data-driven shape of the stage; the heavy per-file extraction runs against
the database (integration suite).
"""

import geopandas as gpd
from shapely.geometry import Polygon

from etl.config import SOURCE_NAMES
from etl.extract import extract_boundaries
from etl.utils import _source_from_filename

SOURCE_FILES = {
    "Bioenergy_V20260203.gpkg": "bio",
    "Gas_Producer_V20260203.gpkg": "gas",
    "Hydropower_V20260203.gpkg": "hydro",
    "Solar_Energy_V20260203.gpkg": "solar",
    "Wind_Energy_V20260203.gpkg": "wind",
    "Energy_Storage_V20260203.gpkg": "storage",
}


class TestSourceFromFilename:
    def test_every_source_file_maps_to_its_canonical_source(self):
        for filename, source in SOURCE_FILES.items():
            assert _source_from_filename(filename) == source

    def test_six_source_files_map_in_source_names_order(self):
        mapped = [_source_from_filename(f) for f in SOURCE_FILES]
        assert mapped == list(SOURCE_NAMES)

    def test_version_suffix_is_required(self):
        assert _source_from_filename("Bioenergy.gpkg") == ""
        assert _source_from_filename("Bioenergy_V2026020.gpkg") == ""
        assert _source_from_filename("Bioenergy_V20260203") == ""

    def test_solar_polygon_facets_are_not_mapped_to_solar(self):
        assert _source_from_filename("Solar_Energy_Polygons_V20260203.gpkg") == ""

    def test_cogeneration_units_is_not_a_loaded_source(self):
        assert _source_from_filename("Cogeneration_Units_V20260203.gpkg") == ""

    def test_unknown_files_are_skipped(self):
        assert _source_from_filename("New_Format_V20260203.gpkg") == ""


class TestBoundariesFailLoudlyWithoutLevel:
    def test_gpkg_lacking_level_column_is_an_error(self, tmp_path):
        gdf = gpd.GeoDataFrame(
            {
                "name": ["Test"],
                "iso": ["DEU"],
                "geometry": [Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])],
            },
            crs="EPSG:4326",
        )
        gpkg = tmp_path / "test_boundary.gpkg"
        gdf.to_file(gpkg, driver="GPKG")
        manifest = tmp_path / "boundaries.txt"
        manifest.write_text("test_boundary.gpkg\n")

        report = extract_boundaries(manifest)

        assert not report.passed
        assert any("no 'level' column" in e for e in report.errors)
"""Stamp the boundary level (0-3) into the four germany_*.gpkg boundary files.

Boundary levels are build metadata, not ETL logic: boundary=0 (country
outline), regions=1, districts=2, kreise=3. The ETL reads the level from each
file's data (extract_boundaries), so this script must be re-run whenever any
of the four files is rebuilt, so every germany_*.gpkg carries a single ``level``
column. Uses the same geopandas/to_postgis-style toolchain and EPSG:4326 CRS
as scripts/build_kreise.py.

Usage:  python scripts/stamp_boundary_levels.py
"""

import sys

import geopandas as gpd

LEVELS = {
    "data/boundaries/germany_boundary.gpkg": 0,
    "data/boundaries/germany_regions.gpkg": 1,
    "data/boundaries/germany_districts.gpkg": 2,
    "data/boundaries/germany_kreise.gpkg": 3,
}


def main() -> int:
    for path, level in LEVELS.items():
        gdf = gpd.read_file(path)
        gdf["level"] = level
        gdf.to_file(path, driver="GPKG")
        print(f"stamped level {level} into {path} ({len(gdf)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""Stamp the boundary level (0-3) into the four germany_*.gpkg boundary files.

Boundary levels are build metadata, not ETL logic, and must match
``etl.config.BOUNDARY_LEVEL_COLUMNS``: country outline = 0, states = 1,
regions = 2, districts = 3 — the ETL reads the level from each file's data
(``extract_boundaries``), so this script must be re-run whenever any of the
four files is rebuilt so every germany_*.gpkg carries a single ``level``
column.  Uses the same geopandas toolchain and EPSG:4326 CRS as
``scripts/build_kreise.py``.  Writes the level back into the layer it read
(keeping each file's one layer, whatever its name), never appending a second
one, so stale-layer debris cannot accumulate.

Usage:  python scripts/stamp_boundary_levels.py
"""

import sys

import geopandas as gpd
import pyogrio

LEVELS = {
    "data/boundaries/germany_boundary.gpkg": 0,
    "data/boundaries/germany_states.gpkg": 1,
    "data/boundaries/germany_regions.gpkg": 2,
    "data/boundaries/germany_districts.gpkg": 3,
}


def main() -> int:
    for path, level in LEVELS.items():
        layers = [entry[0] for entry in pyogrio.list_layers(str(path))]
        if len(layers) != 1:
            sys.exit(f"{path} has {len(layers)} layers, expected exactly one: {layers}")
        layer = layers[0]
        gdf = gpd.read_file(path, layer=layer)
        gdf["level"] = level
        gdf.to_file(path, driver="GPKG", layer=layer)
        print(f"stamped level {level} into {path} layer '{layer}' ({len(gdf)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
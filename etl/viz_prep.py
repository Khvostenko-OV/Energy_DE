"""Boundary GeoJSON preparation for the visualization layer (issue #17).

Reads the boundary reference layer (`service.boundaries`, levels 1-3) via
GeoPandas, simplifies each polygon (Douglas-Peucker) and rounds coordinates
to 6 decimal places, then writes one static GeoJSON file per level
(`level_1.geojson`, `level_2.geojson`, `level_3.geojson`) into an output
directory.  These files feed the Dash app's choropleth layer and are shipped
in the image's asset directory.  Level 0 (the country outline) is not needed
by the app and is skipped.  After generation the files are verified against
`service.boundaries` feature counts, failing loudly on drift.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import geopandas as gpd
import numpy
import shapely

from etl.config import get_engine
from etl.db_schema import BOUNDARY_GEOJSON_FILES, SERVICE_SCHEMA
from etl.reports import VizPrepReport
from etl.verify import _verify_viz_prep

log = logging.getLogger(__name__)

# Douglas-Peucker tolerance in WGS-84 degrees (~550 m); coarse enough to keep
# the generated assets small, fine enough to preserve choropleth shape on the
# Germany overview.
SIMPLIFY_TOLERANCE = 0.005

# Coordinate rounding precision in decimal places (~0.1 m at equator).
ROUND_DECIMALS = 6


def _simplify_geometry(geometry: shapely.Geometry) -> shapely.Geometry:
    """Simplify a polygon with Douglas-Peucker and round its coordinates.

    ``preserve_topology`` keeps the simplified ring from self-intersecting,
    and any degeneracies introduced by the subsequent coordinate rounding are
    repaired with ``shapely.make_valid``.  Empty geometries pass through
    untouched.  Returns the transformed geometry.
    """
    if geometry.is_empty:
        return geometry
    simplified = shapely.simplify(geometry, SIMPLIFY_TOLERANCE, preserve_topology=True)
    rounded = shapely.transform(
        simplified, lambda coords: numpy.round(coords, ROUND_DECIMALS)
    )
    if not rounded.is_valid:
        rounded = shapely.make_valid(rounded)
    return rounded


def generate_boundaries_geojson(outdir: Path) -> VizPrepReport:
    """Write per-level boundary GeoJSON files and verify them.

    Reads `service.boundaries` rows at levels 1-3 via GeoPandas, simplifies
    each geometry, and writes one GeoJSON file per level into OUTDIR.  The
    generated files are then checked against the stored feature counts.
    Returns a report; any drift is recorded in ``report.errors`` so the CLI
    can exit non-zero (fail loudly).
    """
    report = VizPrepReport(outdir=str(outdir))
    start = time.perf_counter()
    try:
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        engine = get_engine()

        gdf = gpd.read_postgis(
            f"SELECT name, area, level, geometry FROM {SERVICE_SCHEMA}.boundaries "
            "WHERE level IN (1, 2, 3)",
            engine,
            geom_col="geometry",
        )
        if gdf.empty:
            report.errors.append("service.boundaries has no level 1-3 rows")
        else:
            gdf["geometry"] = gdf["geometry"].apply(_simplify_geometry)
            for level, filename in sorted(BOUNDARY_GEOJSON_FILES.items()):
                subset = gdf[gdf["level"] == level].copy()
                if subset.empty:
                    report.errors.append(f"No boundary rows at level {level}")
                    continue
                subset.drop(columns=["level"]).to_file(outdir / filename, driver="GeoJSON")
                report.files.append(filename)
                report.features_by_level[level] = len(subset)
            report.errors.extend(_verify_viz_prep(engine, outdir))
    except Exception as e:
        report.errors.append(f"Boundary GeoJSON generation failed: {e}")
        log.exception("Boundary GeoJSON generation failed")

    report.total_time = time.perf_counter() - start
    if report.errors:
        for err in report.errors:
            log.error("Boundary GeoJSON failed: %s", err)
    else:
        log.info(
            "Boundary GeoJSON prepared (levels %s, %.3fs)",
            ", ".join(f"{k}:{v}" for k, v in sorted(report.features_by_level.items())),
            report.total_time,
        )
    return report
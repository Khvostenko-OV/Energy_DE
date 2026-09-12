from __future__ import annotations

import logging
import time
from datetime import date
from pathlib import Path

import geopandas as gpd
from sqlalchemy.engine import Engine

from etl.config import get_engine
from etl.utils import (
    BOUNDARY_COLUMN_MAPPING,
    BOUNDARY_FILE_LEVELS,
    BOUNDARY_RAW_COLUMNS,
    COLUMN_MAPPING,
    RAW_COLUMNS,
    RAW_SCHEMA,
    BoundariesReport,
    ExtractionReport,
    _build_secondary_attributes,
    _cast_types,
    _compute_boundary_areas,
    _create_log_table,
    _drop_duplicate_reference_ids,
    _ensure_schema,
    _is_logged,
    _log_load,
    _next_version_table,
    _verify_boundaries,
    _verify_extraction,
    source_from_filename,
)

log = logging.getLogger(__name__)


def extract_source(
    file_path: Path, engine: Engine | None = None, force: bool = False
) -> ExtractionReport:
    """Extract one unit source GPKG into a new versioned raw table.

    The energy source is derived from the file name. If the file's load
    signature (filename, filesize, modified_at) is already logged it is
    skipped unless force is set, in which case a new version is appended
    alongside a new loaded_files row. Each successful load writes
    raw.<source>_<YYYYMMDD>_<n> and verifies counts and reference_id
    uniqueness against the stored table.
    """
    report = ExtractionReport()
    t0 = time.perf_counter()
    try:
        engine = engine or get_engine()

        source = source_from_filename(file_path.name)
        if not source:
            raise ValueError(f"Cannot map filename {file_path.name!r} to an energy source")
        report.source = source

        log.info("Extracting %s from %s", source, file_path.name)

        _ensure_schema(engine)
        _create_log_table(engine)

        stat = file_path.stat()
        signature = (file_path.name, stat.st_size, stat.st_mtime)
        is_logged = _is_logged(engine, signature)

        if is_logged and not force:
            report.skipped = True
            log.info("Skipping %s: already loaded", file_path.name)
        else:
            if force and is_logged:
                log.info("Force reload requested for %s", file_path.name)

            t1 = time.perf_counter()
            log.info("Reading %s...", file_path.name)
            df = gpd.read_file(file_path)
            report.source_row_count = len(df)
            t2 = time.perf_counter()
            log.info("%d rows loaded, time %.3fs", len(df), t2 - t1)

            for old, new in COLUMN_MAPPING.get(source, {}).items():
                df = df.rename(columns={old: new})

            df["energy_source"] = source

            log.info("Casting types...")
            _cast_types(df)
            t3 = time.perf_counter()
            log.info("Type casting done, time %.3fs", t3 - t2)

            log.info("Dropping duplicates...")
            report.duplicates_dropped = _drop_duplicate_reference_ids(df)
            t4 = time.perf_counter()
            log.info(
                "%d duplicates removed, %d remaining, time %.3fs",
                report.duplicates_dropped, len(df), t4 - t3,
            )

            log.info("Building secondary attributes...")
            report.attributes_empty = _build_secondary_attributes(df)
            t5 = time.perf_counter()
            log.info("%d empty attributes, time %.3fs", report.attributes_empty, t5 - t4)

            keep_cols = [c for c in RAW_COLUMNS if c in df.columns] + [
                "geometry",
                "secondary_attributes",
            ]
            df = df[keep_cols]

            table_name = _next_version_table(engine, source, date.today())
            log.info("Writing to %s.%s ...", RAW_SCHEMA, table_name)
            df.to_postgis(
                table_name, engine, schema=RAW_SCHEMA, if_exists="fail",
                index=False,
            )
            report.loaded_to = table_name
            report.rows_loaded = len(df)
            t6 = time.perf_counter()
            log.info("%d rows written, time %.3fs", report.rows_loaded, t6 - t5)

            _log_load(engine, file_path.name, stat.st_size, stat.st_mtime, table_name)

            log.info("Verifying extraction...")
            report.errors = _verify_extraction(engine, table_name, report)
            t7 = time.perf_counter()
            log.info("Verification done, time %.3fs", t7 - t6)

    except Exception as e:
        if not report.source:
            report.source = file_path.name
        report.errors.append(f"Extraction failed: {e}")
        log.exception("Extraction failed for %s", file_path.name)

    report.total_time = time.perf_counter() - t0
    if report.skipped:
        log.info("Skipped %s (already loaded)", file_path.name)
    elif report.errors:
        for err in report.errors:
            log.error("Extraction failed for %s: %s", report.source, err)
    else:
        log.info("Extraction passed for %s (%d rows)", report.source, report.rows_loaded)
    log.info("Total time: %.3fs", report.total_time)

    return report


def extract_boundaries(manifest: Path, engine: Engine | None = None) -> BoundariesReport:
    """Load the boundary reference files listed in a manifest into raw.boundaries.

    MANIFEST lists one germany_*.gpkg file per line, resolved against the
    manifest's directory; each file's level (0-3) is read from its name. Every
    file is read into a GeoDataFrame, stripped to the raw column set (iso is
    mapped to country_iso), stamped with its level and written via
    to_postgis: the first file replaces the table, the rest append. Area is
    recomputed afterwards in km² via PostGIS.
    """
    report = BoundariesReport()
    try:
        engine = engine or get_engine()
        _ensure_schema(engine)

        filenames = [
            line.strip()
            for line in manifest.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        first = True
        for filename in filenames:
            stem = Path(filename).stem
            level = (
                BOUNDARY_FILE_LEVELS.get(stem[len("germany_"):])
                if stem.startswith("germany_") else None
            )
            if level is None:
                log.warning("Skipping %s: cannot map to a boundary level", filename)
                continue
            f = manifest.parent / filename
            log.info("Loading %s as level %d", filename, level)

            gdf = gpd.read_file(f)
            if "name" not in gdf.columns:
                raise ValueError(f"{filename} has no 'name' column")

            out = gdf.rename(columns=BOUNDARY_COLUMN_MAPPING)
            drop = [c for c in out.columns if c not in BOUNDARY_RAW_COLUMNS and c != "geometry"]
            out = out.drop(columns=drop)
            out["level"] = level
            out["area"] = 0.0

            out.to_postgis(
                "boundaries", engine, schema=RAW_SCHEMA,
                if_exists="replace" if first else "append",
                index=False,
            )
            first = False
            report.rows_by_level[level] = len(out)

        if report.rows_by_level:
            _compute_boundary_areas(engine)
            report.loaded = True
            report.errors = _verify_boundaries(engine)
    except Exception as e:
        report.errors.append(f"Boundary load failed: {e}")
        log.exception("Boundary load failed")

    return report
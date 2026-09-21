from __future__ import annotations

import json
import logging
import time
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas

from etl.config import get_engine
from etl.db_schema import (
    BOUNDARY_COLUMNS,
    BOUNDARY_COLUMN_MAPPING,
    RAW_COLUMNS,
    RAW_COLUMN_MAPPING,
    RAW_SCHEMA,
    SERVICE_SCHEMA,
)
from etl.db_utils import _create_log_table, _ensure_schema
from etl.reports import BoundariesReport, ExtractionReport
from etl.utils import (
    _compute_boundary_areas,
    _drop_duplicate_reference_ids,
    _is_logged,
    _log_load,
    _next_table_version,
    _read_manifest,
    _source_from_filename,
)
from etl.verify import _verify_boundaries, _verify_extraction

log = logging.getLogger(__name__)


def extract_source(file_path: Path, force: bool = False) -> ExtractionReport:
    """Extract one unit source GPKG into a new versioned raw table.

    The energy source is derived from the file name. If the file's load
    signature (filename, filesize, modified_at) is already logged it is
    skipped unless force is set, in which case a new version is appended
    alongside a new loaded_files row. Each successful load writes
    raw.<source>_<YYYYMMDD>_<n> and verifies counts and reference_id
    uniqueness against the stored table.
    """
    report = ExtractionReport()
    start = time.perf_counter()
    try:
        engine = get_engine()

        source = _source_from_filename(file_path.name)
        if not source:
            raise ValueError(f"Cannot map filename {file_path.name!r} to an energy source")
        report.source = source

        log.info("Extracting %s from %s", source, file_path.name)

        _ensure_schema(engine)
        _ensure_schema(engine, SERVICE_SCHEMA)
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

            log.info("Reading %s...", file_path.name)
            t = time.perf_counter()
            df = gpd.read_file(file_path)
            report.source_row_count = len(df)
            log.info("%d rows loaded, time %.3fs", len(df), time.perf_counter() - t)

            for old, new in RAW_COLUMN_MAPPING.get(source, {}).items():
                df = df.rename(columns={old: new})

            df["energy_source"] = source

            log.info("Casting types...")
            t = time.perf_counter()
            _cast_types(df)
            log.info("Type casting done, time %.3fs", time.perf_counter() - t)

            log.info("Dropping duplicates...")
            t = time.perf_counter()
            report.duplicates_dropped = _drop_duplicate_reference_ids(df)
            log.info(
                "%d duplicates removed, %d remaining, time %.3fs",
                report.duplicates_dropped, len(df), time.perf_counter() - t,
            )

            log.info("Building secondary attributes...")
            t = time.perf_counter()
            report.attributes_empty = _build_secondary_attributes(df)
            log.info(
                "%d empty attributes, time %.3fs",
                report.attributes_empty, time.perf_counter() - t,
            )

            keep_cols = [c for c in RAW_COLUMNS if c in df.columns]
            df = df[keep_cols]

            table_name = _next_table_version(engine, source, date.today())
            log.info("Writing to %s.%s ...", RAW_SCHEMA, table_name)
            t = time.perf_counter()
            df.to_postgis(
                table_name, engine, schema=RAW_SCHEMA, if_exists="fail",
                index=False,
            )
            report.loaded_to = table_name
            report.rows_loaded = len(df)
            log.info("%d rows written, time %.3fs", report.rows_loaded, time.perf_counter() - t)

            _log_load(engine, file_path.name, stat.st_size, stat.st_mtime, table_name)

            log.info("Verifying extraction...")
            t = time.perf_counter()
            report.errors = _verify_extraction(engine, table_name, report)
            log.info("Verification done, time %.3fs", time.perf_counter() - t)

    except Exception as e:
        if not report.source:
            report.source = file_path.name
        report.errors.append(f"Extraction failed: {e}")
        log.exception("Extraction failed for %s", file_path.name)

    report.total_time = time.perf_counter() - start
    if report.skipped:
        log.info("Skipped %s (already loaded)", file_path.name)
    elif report.errors:
        for err in report.errors:
            log.error("Extraction failed for %s: %s", report.source, err)
    else:
        log.info("Extraction passed for %s (%d rows)", report.source, report.rows_loaded)
    log.info("Total time: %.3fs", report.total_time)

    return report


def _cast_types(df: pandas.DataFrame) -> None:
    """Cast columns to the raw shape in place.

    Commissioning and decommissioning dates keep the day resolution of the
    source data; reference_date keeps its full timestamp including the time
    of day (the incremental-load freshness gate downstream).
    """
    for col in ("commissioning_date", "decommissioning_date"):
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: x[:10] if isinstance(x, str) and len(x) >= 10 else x
            )
            df[col] = pandas.to_datetime(df[col], errors="coerce").dt.date

    if "reference_date" in df.columns:
        df["reference_date"] = pandas.to_datetime(df["reference_date"], errors="coerce")

    df["installed_capacity"] = df["installed_capacity"].astype("Float64")
    df["x_coordinates"] = df["x_coordinates"].astype("Float64")
    df["y_coordinates"] = df["y_coordinates"].astype("Float64")
    df["geo_accuracy"] = df["geo_accuracy"].astype("Int64")
    if "storage_capacity" in df.columns:
        df["storage_capacity"] = df["storage_capacity"].astype("Float64")


def _build_secondary_attributes(df: pandas.DataFrame) -> int:
    """Fold secondary attributes into a serialized JSON column stored as text.

    All columns outside RAW_COLUMNS (and the geometry) are collapsed into a
    per-row JSON document, dropping null/empty values; numpy scalars and date
    values are stringified via the JSON default hook. Returns the count of
    rows whose document is empty.
    """
    attr_cols = [c for c in df.columns if c not in RAW_COLUMNS]
    df["secondary_attributes"] = df[attr_cols].apply(
        lambda row: {k: v for k, v in row.items() if not pandas.isna(v)},
        axis=1,
    )
    empty = int((df["secondary_attributes"].apply(len) == 0).sum())
    df["secondary_attributes"] = df["secondary_attributes"].apply(
        lambda d: json.dumps(d, default=str)
    )
    return empty


def extract_boundaries(manifest: Path, force: bool = False) -> BoundariesReport:
    """Load the boundary reference files listed in a manifest into service.boundaries.

    MANIFEST lists one germany_*.gpkg file per line, resolved against the
    manifest's directory; each file's level (0-3) is read from its `level`
    column, and a file without one fails loudly rather than mislabelling.
    Every file is read into a GeoDataFrame, stripped to the raw column set
    (iso is mapped to country_iso), stamped with its level and written via
    to_postgis: the first file replaces the table, the rest append. Area is
    computed in km² via PostGIS.

    The boundaries table is rebuilt atomically from the whole manifest, so a
    load only runs when at least one file's signature (filename, filesize,
    modified_at) is not yet logged in service.loaded_files or force is set;
    every file written is then logged.  If all files are already logged the
    entire operation is skipped.
    """
    report = BoundariesReport()
    start = time.perf_counter()
    try:
        engine = get_engine()
        _ensure_schema(engine, SERVICE_SCHEMA)
        _create_log_table(engine)

        filenames = _read_manifest(manifest)

        all_logged = True
        for filename in filenames:
            f = manifest.parent / filename
            stat = f.stat()
            sig = (f.name, stat.st_size, stat.st_mtime)
            if not _is_logged(engine, sig) or force:
                all_logged = False
                break

        if all_logged:
            report.skipped = True
            log.info("Skipping boundaries: all files already loaded")
        else:
            first = True
            for filename in filenames:
                f = manifest.parent / filename
                stat = f.stat()
                log.info("Loading %s", filename)

                gdf = gpd.read_file(f)
                if "name" not in gdf.columns:
                    raise ValueError(f"{filename} has no 'name' column")
                if "level" not in gdf.columns:
                    raise ValueError(f"{filename} has no 'level' column")
                levels = gdf["level"].unique()
                if len(levels) != 1:
                    raise ValueError(
                        f"{filename} must carry a single 'level' value, "
                        f"found {sorted(levels.tolist())}"
                    )
                level = int(levels[0])

                out = gdf.rename(columns=BOUNDARY_COLUMN_MAPPING)
                drop = [c for c in out.columns if c not in BOUNDARY_COLUMNS]
                out = out.drop(columns=drop)
                out["level"] = level
                out["area"] = 0.0

                out.to_postgis(
                    "boundaries", engine, schema=SERVICE_SCHEMA,
                    if_exists="replace" if first else "append",
                    index=False,
                )
                first = False
                report.rows_by_level[level] = len(out)

                _log_load(engine, f.name, stat.st_size, stat.st_mtime, "service.boundaries")

            if report.rows_by_level:
                _compute_boundary_areas(engine)
                report.loaded = True
                report.errors = _verify_boundaries(engine)
    except Exception as e:
        report.errors.append(f"Boundary load failed: {e}")
        log.exception("Boundary load failed")

    report.total_time = time.perf_counter() - start
    return report
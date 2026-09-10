from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.config import get_engine

log = logging.getLogger(__name__)

RAW_SCHEMA = "raw"

FILENAME_PATTERN = r"(bio|gas|hydro|solar|wind|storage)"

RAW_COLUMNS = [
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "storage_capacity",
    "storage_type",
    "x_coordinates",
    "y_coordinates",
    "geo_accuracy",
    "reference_id",
    "reference_date",
    "geometry",
]

COLUMN_MAPPING = {
    "gas": {"gas_production_capacity": "installed_capacity"},
}


@dataclass
class ExtractionReport:
    """Result of an extract stage run: row counts, timing and verification outcome."""

    source: str
    source_row_count: int
    rows_loaded: int
    duplicates_dropped: int
    properties_empty: int
    errors: list[str] = field(default_factory=list)
    total_time: float = 0.0

    @property
    def passed(self) -> bool:
        """True if the extraction completed without errors."""
        return not self.errors

    def summary(self) -> str:
        """Render the report as a human-readable summary string."""
        lines = [
            f"  Source file rows : {self.source_row_count}",
            f"  Rows loaded      : {self.rows_loaded}",
            f"  Duplicates dropped: {self.duplicates_dropped}",
            f"  Properties empty : {self.properties_empty}",
            f"  Status           : {'PASS' if self.passed else 'FAIL'}",
            f"  Total time       : {self.total_time:.3f}s",
        ]
        if self.errors:
            for e in self.errors:
                lines.append(f"  ERROR: {e}")
        return "\n".join(lines)


def _ensure_schema(engine: Engine) -> None:
    """Create the raw schema in the database if it does not exist."""
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {RAW_SCHEMA}"))
        conn.commit()


def _cast_types(df: pandas.DataFrame) -> None:
    """Cast columns to the raw shape in place.

    Commissioning and decommissioning dates keep the day resolution of the
    source data; reference_date keeps its full timestamp including the time
    of day.
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


def _drop_duplicate_reference_ids(df: pandas.DataFrame) -> int:
    """Drop rows whose non-null reference_id appears earlier in the file.

    Rows without a reference_id are never treated as duplicates: the solar
    file carries 39 such rows (Fraunhofer-sourced) that must all be retained.
    Returns the number of rows dropped.
    """
    before = len(df)
    dup_mask = df["reference_id"].duplicated(keep="first") & df["reference_id"].notna()
    df.drop(df.index[dup_mask], inplace=True)
    return before - len(df)


def _build_properties(df: pandas.DataFrame) -> int:
    """Fold secondary attributes into a properties dictionary column.

    All columns outside RAW_COLUMNS are collapsed into a per-row dictionary,
    dropping null/empty values. Returns the count of rows whose properties
    dictionary is empty.
    """
    props_cols = [c for c in df.columns if c not in RAW_COLUMNS]
    df["properties"] = df[props_cols].apply(
        lambda row: {k: v for k, v in row.items() if not pandas.isna(v)},
        axis=1,
    )
    return int((df["properties"].apply(len) == 0).sum())


def source_from_filename(filename: str) -> str:
    """Map a source file name to its canonical source key via regex.

    The match is case-insensitive, so 'Bioenergy_V20260203.gpkg' maps to
    'bio', 'Energy_Storage_V20260203.gpkg' to 'storage', and so on.
    Returns an empty string when the file name cannot be mapped.
    """
    match = re.search(FILENAME_PATTERN, filename, re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).lower()


def extract_source(file_path: Path, engine: Engine | None = None) -> ExtractionReport:
    """Extract one unit source GPKG into its raw table.

    The energy source is derived from the file name via regex. Applies the
    source's column renames, sets the canonical energy_source, casts dates
    and numerics, drops duplicate reference_ids, folds secondary attributes
    into properties, writes the table to PostGIS and verifies it against the
    loaded counts and key uniqueness. Returns an ExtractionReport.
    """
    import geopandas as gpd

    report = ExtractionReport(
        source="", source_row_count=0, rows_loaded=0, duplicates_dropped=0, properties_empty=0
    )

    t0 = time.perf_counter()
    try:
        engine = engine or get_engine()

        source = source_from_filename(file_path.name)
        if not source:
            raise ValueError(f"Cannot map filename {file_path.name!r} to an energy source")
        report.source = source

        log.info("Extracting %s from %s", source, file_path.name)

        _ensure_schema(engine)
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
        log.info("%d duplicates removed, %d remaining, time %.3fs", report.duplicates_dropped, len(df), t4 - t3)

        log.info("Building properties...")
        report.properties_empty = _build_properties(df)
        t5 = time.perf_counter()
        log.info("%d empty properties, time %.3fs", report.properties_empty, t5 - t4)

        cols_to_keep = [c for c in RAW_COLUMNS if c in df.columns] + ["properties"]
        df = df[cols_to_keep]

        log.info("Writing to PostGIS (%s)...", source)
        df.to_postgis(source, engine, schema=RAW_SCHEMA, if_exists="replace", index=False)
        report.rows_loaded = len(df)
        t6 = time.perf_counter()
        log.info("%d rows written, time %.3fs", report.rows_loaded, t6 - t5)

        log.info("Verifying extraction...")
        report.errors = _verify_extraction(engine, source, report)
        t7 = time.perf_counter()
        log.info("Verification done, time %.3fs", t7 - t6)

    except Exception as e:
        if not report.source:
            report.source = file_path.name
        report.errors.append(f"Extraction failed: {e}")
        log.exception("Extraction failed for %s", file_path.name)

    report.total_time = time.perf_counter() - t0
    if report.errors:
        for err in report.errors:
            log.error("Extraction failed for %s: %s", report.source, err)
    else:
        log.info("Extraction passed for %s (%d rows)", report.source, report.rows_loaded)
    log.info("Total time: %.3fs", report.total_time)

    return report


def _verify_extraction(engine: Engine, source: str, report: ExtractionReport) -> list[str]:
    """Verify the raw.<source> table against the extraction report.

    Checks the loaded count is consistent with the pre-dedupe source rows,
    matches the number of rows written to the table, and that no non-null
    reference_id appears more than once in the stored table. Returns a list
    of error strings, empty if verification passes.
    """
    errors: list[str] = []
    if report.rows_loaded != report.source_row_count - report.duplicates_dropped:
        errors.append(
            f"Row count mismatch: loaded {report.rows_loaded}, expected {report.source_row_count - report.duplicates_dropped}"
        )

    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT COUNT(*) FROM {RAW_SCHEMA}.{source}")
        ).scalar()
        if row != report.rows_loaded:
            errors.append(f"Row count mismatch: expected {report.rows_loaded}, got {row}")

        row = conn.execute(
            text(
                f"SELECT COUNT(*) FROM ("
                f"SELECT reference_id FROM {RAW_SCHEMA}.{source} "
                f"WHERE reference_id IS NOT NULL "
                f"GROUP BY reference_id HAVING COUNT(*) > 1) dups"
            )
        ).scalar()
        if row > 0:
            errors.append(f"Duplicate reference_ids found: {row}")

    return errors
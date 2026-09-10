from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.config import get_engine

log = logging.getLogger(__name__)

RAW_SCHEMA = "raw"

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "geo"

RAW_COLUMNS = [
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "x_coordinates",
    "y_coordinates",
    "geo_accuracy",
    "reference_id",
    "reference_date",
    "geometry",
]

SOURCES = {
    "bio": {
        "file": "Bioenergy_V20260203.gpkg",
        "energy_source": "Bio",
        "expected_rows": 23562,
    },
    "gas": {
        "file": "Gas_Producer_V20260203.gpkg",
        "energy_source": "Gas",
        "expected_rows": 304,
        "column_mapping": {"gas_production_capacity": "installed_capacity"},
    },
    "hydro": {
        "file": "Hydropower_V20260203.gpkg",
        "energy_source": "Hydro",
        "expected_rows": 8758,
    },
    "solar": {
        "file": "Solar_Energy_V20260203.gpkg",
        "energy_source": "Solar",
        "expected_rows": 14250,
    },
    "wind": {
        "file": "Wind_Energy_V20260203.gpkg",
        "energy_source": "Wind",
        "expected_rows": 33433,
    },
    "storage": {
        "file": "Energy_Storage_V20260203.gpkg",
        "energy_source": "Storage",
        "expected_rows": 1348,
    },
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
    """Cast dates and numeric columns to the uniform raw shape in place."""
    date_cols = ["commissioning_date", "decommissioning_date", "reference_date"]
    for col in date_cols:
        if col in df.columns:
            df[col] = df[col].apply(
                lambda x: x[:10] if isinstance(x, str) and len(x) >= 10 else x
            )
            df[col] = pandas.to_datetime(df[col], errors="coerce").dt.date

    df["installed_capacity"] = df["installed_capacity"].astype(float)
    df["x_coordinates"] = df["x_coordinates"].astype(float)
    df["y_coordinates"] = df["y_coordinates"].astype(float)
    df["geo_accuracy"] = df["geo_accuracy"].astype(int)


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


def extract_source(source: str, engine: Engine | None = None) -> ExtractionReport:
    """Extract one unit source GPKG into its raw table.

    Loads the source file, applies the source's column renames, sets the
    canonical energy_source, casts dates and numerics, drops duplicate
    reference_ids, folds secondary attributes into properties, writes the
    table to PostGIS and verifies it against the expected row count and
    key uniqueness. Returns an ExtractionReport.
    """
    import geopandas as gpd

    if source not in SOURCES:
        raise ValueError(f"Unknown source: {source}")

    config = SOURCES[source]
    engine = engine or get_engine()
    report = ExtractionReport(source=source, source_row_count=0, rows_loaded=0, duplicates_dropped=0, properties_empty=0)

    t0 = time.perf_counter()
    log.info("Start data extraction (%s)", source)

    try:
        _ensure_schema(engine)
        t1 = time.perf_counter()

        gpkg_path = DATA_DIR / config["file"]
        log.info("Reading %s...", gpkg_path.name)
        df = gpd.read_file(gpkg_path)
        report.source_row_count = len(df)
        t2 = time.perf_counter()
        log.info("%d rows loaded, time %.3fs", len(df), t2 - t1)

        for old, new in config.get("column_mapping", {}).items():
            df = df.rename(columns={old: new})

        df["energy_source"] = config["energy_source"]

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
        report.errors.append(f"Extraction failed: {e}")
        log.error("Extraction failed: %s", e)

    report.total_time = time.perf_counter() - t0
    log.info("Total time: %.3fs", report.total_time)

    return report


def _verify_extraction(engine: Engine, source: str, report: ExtractionReport) -> list[str]:
    """Verify the raw.<source> table against the extraction report.

    Checks the row count matches the source's expected count and the loaded
    count, and that no non-null reference_id appears more than once in the
    stored table. Returns a list of error strings, empty if verification
    passes.
    """
    errors: list[str] = []
    expected = SOURCES[source]["expected_rows"]
    if report.rows_loaded != expected:
        errors.append(f"Row count mismatch: expected {expected}, got {report.rows_loaded}")
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

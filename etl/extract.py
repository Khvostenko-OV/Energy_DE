from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.config import get_engine

log = logging.getLogger(__name__)

RAW_SCHEMA = "raw"

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


def extract_bioenergy(engine: Engine | None = None) -> ExtractionReport:
    """Extract the Bioenergy GPKG into the raw.bioenergy PostGIS table.
    Loads the source file, casts dates and numeric columns, drops duplicate
    reference_ids, folds secondary attributes into a properties dictionary,
    writes to PostGIS and runs verification. Returns an ExtractionReport.
    """
    import geopandas as gpd

    engine = engine or get_engine()
    report = ExtractionReport(source="bioenergy", source_row_count=0, rows_loaded=0, duplicates_dropped=0, properties_empty=0)

    t0 = time.perf_counter()
    log.info("Start data extraction")

    try:
        _ensure_schema(engine)
        t1 = time.perf_counter()

        gpkg_path = Path(__file__).resolve().parent.parent / "data" / "geo" / "Bioenergy_V20260203.gpkg"
        log.info("Reading %s...", gpkg_path.name)
        df = gpd.read_file(gpkg_path)
        report.source_row_count = len(df)
        t2 = time.perf_counter()
        log.info("%d rows loaded, time %.3fs", len(df), t2 - t1)

        df["energy_source"] = "Bio"

        log.info("Casting types...")
        date_cols = ["commissioning_date", "decommissioning_date", "reference_date"]
        for col in date_cols:
            df[col] = df[col].apply(
                lambda x: x[:10] if isinstance(x, str) and len(x) >= 10 else x
            )
            df[col] = gpd.pd.to_datetime(df[col], errors="coerce").dt.date

        df["installed_capacity"] = df["installed_capacity"].astype(float)
        df["x_coordinates"] = df["x_coordinates"].astype(float)
        df["y_coordinates"] = df["y_coordinates"].astype(float)
        df["geo_accuracy"] = df["geo_accuracy"].astype(int)
        t3 = time.perf_counter()
        log.info("Type casting done, time %.3fs", t3 - t2)

        log.info("Dropping duplicates...")
        key_cols = ["reference_id"]
        before = len(df)
        df = df.drop_duplicates(subset=key_cols, keep="first")
        report.duplicates_dropped = before - len(df)
        t4 = time.perf_counter()
        log.info("%d duplicates removed, %d remaining, time %.3fs", report.duplicates_dropped, len(df), t4 - t3)

        log.info("Building properties...")
        props_cols = [c for c in df.columns if c not in RAW_COLUMNS]
        df["properties"] = df[props_cols].apply(
            lambda row: {k: v for k, v in row.items() if v is not None and str(v) != "nan"},
            axis=1,
        )
        report.properties_empty = int((df["properties"].apply(len) == 0).sum())
        t5 = time.perf_counter()
        log.info("%d empty properties, time %.3fs", report.properties_empty, t5 - t4)

        cols_to_keep = [c for c in RAW_COLUMNS if c in df.columns] + ["properties"]
        df = df[cols_to_keep]

        log.info("Writing to PostGIS...")
        df.to_postgis("bioenergy", engine, schema=RAW_SCHEMA, if_exists="replace", index=False)
        report.rows_loaded = len(df)
        t6 = time.perf_counter()
        log.info("%d rows written, time %.3fs", report.rows_loaded, t6 - t5)

        log.info("Verifying extraction...")
        report.errors = _verify_extraction(engine, report)
        t7 = time.perf_counter()
        log.info("Verification done, time %.3fs", t7 - t6)

    except Exception as e:
        report.errors.append(f"Extraction failed: {e}")
        log.error(f"Extraction failed: {e}")

    report.total_time = time.perf_counter() - t0
    log.info("Total time: %.3fs", report.total_time)

    return report


def _verify_extraction(engine: Engine, report: ExtractionReport) -> list[str]:
    """Verify the raw.bioenergy table against the extraction report.
    Checks the stored row count matches the loaded count and that no
    reference_id appears more than once. Returns a list of error strings,
    empty if verification passes.
    """
    errors: list[str] = []
    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT COUNT(*) FROM {RAW_SCHEMA}.bioenergy")
        ).scalar()
        if row != report.rows_loaded:
            errors.append(f"Row count mismatch: expected {report.rows_loaded}, got {row}")

        row = conn.execute(
            text(f"SELECT COUNT(*) FROM (SELECT reference_id FROM {RAW_SCHEMA}.bioenergy GROUP BY reference_id HAVING COUNT(*) > 1) dups")
        ).scalar()
        if row > 0:
            errors.append(f"Duplicate reference_ids found: {row}")

    if report.rows_loaded != report.source_row_count - report.duplicates_dropped:
        errors.append(
            f"Row count mismatch: loaded {report.rows_loaded}, expected {report.source_row_count - report.duplicates_dropped}"
        )

    return errors

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date

import pandas
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.config import RAW_SCHEMA

log = logging.getLogger(__name__)

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
]

COLUMN_MAPPING = {
    "gas": {"gas_production_capacity": "installed_capacity"},
}

BOUNDARY_FILE_LEVELS = {
    "boundary": 0,
    "regions": 1,
    "districts": 2,
    "munis": 3,
}

BOUNDARY_COLUMN_MAPPING = {"iso": "country_iso"}

BOUNDARY_RAW_COLUMNS = ("country_iso", "name")


@dataclass
class ExtractionReport:
    """Result of one unit source extract: counts, version and verification outcome."""

    source: str = ""
    source_row_count: int = 0
    rows_loaded: int = 0
    duplicates_dropped: int = 0
    attributes_empty: int = 0
    loaded_to: str | None = None
    skipped: bool = False
    errors: list[str] = field(default_factory=list)
    total_time: float = 0.0

    @property
    def passed(self) -> bool:
        """True if the extract completed without errors (a skip is also a pass)."""
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"  Source file rows : {self.source_row_count}",
            f"  Rows loaded      : {self.rows_loaded}",
            f"  Duplicates dropped: {self.duplicates_dropped}",
            f"  Empty attributes  : {self.attributes_empty}",
            f"  Loaded to        : {self.loaded_to or '-'}",
            f"  Status           : {'SKIPPED (already loaded)' if self.skipped else ('PASS' if self.passed else 'FAIL')}",
            f"  Total time       : {self.total_time:.3f}s",
        ]
        if self.errors:
            for e in self.errors:
                lines.append(f"  ERROR: {e}")
        return "\n".join(lines)


@dataclass
class BoundariesReport:
    """Result of the boundary reference-data load."""

    loaded: bool = False
    rows_by_level: dict[int, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.errors

    def summary(self) -> str:
        lines = [
            f"  Loaded           : {'yes' if self.loaded else 'no (already present or error)'}",
            "  Rows by level    : " + (", ".join(f"{k}={v}" for k, v in sorted(self.rows_by_level.items())) or "-"),
            f"  Status           : {'PASS' if self.passed else 'FAIL'}",
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


def _create_log_table(engine: Engine) -> None:
    """Create the append-only loaded_files log if it does not exist."""
    with engine.connect() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {RAW_SCHEMA}.loaded_files (
                    filename    TEXT,
                    filesize    BIGINT,
                    modified_at TIMESTAMPTZ,
                    loaded_at   TIMESTAMPTZ,
                    loaded_to   TEXT
                )
                """
            )
        )
        conn.commit()


def _next_version_table(engine: Engine, source: str, day: date) -> str:
    """Compute the next versioned table name for a source on a given day.

    Versions follow raw.<source>_<YYYYMMDD>_<n> with a per-source counter that
    resets daily: the largest existing counter for the day is incremented,
    starting at 1 when none exists.
    """
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :schema"
            ),
            {"schema": RAW_SCHEMA},
        ).fetchall()

    prefix = f"{source}_{day:%Y%m%d}_"
    counters = []
    for name in (row[0] for row in rows):
        if name.startswith(prefix) and name[len(prefix):].isdigit():
            counters.append(int(name[len(prefix):]))
    return f"{prefix}{max(counters, default=0) + 1}"


def _is_logged(engine: Engine, signature: tuple[str, int, float]) -> bool:
    """True if the (filename, filesize, modified_at) load signature is logged."""
    filename, filesize, modified_at = signature
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"SELECT 1 FROM {RAW_SCHEMA}.loaded_files "
                "WHERE filename = :filename AND filesize = :filesize "
                "AND modified_at = to_timestamp(:modified_at) LIMIT 1"
            ),
            {"filename": filename, "filesize": filesize, "modified_at": modified_at},
        ).first()
        return row is not None


def _log_load(
    engine: Engine, filename: str, filesize: int, modified_at: float, loaded_to: str
) -> None:
    """Append one row to loaded_files recording a completed load action."""
    with engine.connect() as conn:
        conn.execute(
            text(
                f"INSERT INTO {RAW_SCHEMA}.loaded_files "
                "(filename, filesize, modified_at, loaded_at, loaded_to) "
                "VALUES (:filename, :filesize, to_timestamp(:modified_at), now(), :loaded_to)"
            ),
            {
                "filename": filename,
                "filesize": filesize,
                "modified_at": modified_at,
                "loaded_to": loaded_to,
            },
        )
        conn.commit()


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


def _build_secondary_attributes(df: pandas.DataFrame) -> int:
    """Fold secondary attributes into a serialized JSON column stored as text.

    All columns outside RAW_COLUMNS (and the geometry) are collapsed into a
    per-row JSON document, dropping null/empty values; numpy scalars and date
    values are stringified via the JSON default hook. Returns the count of
    rows whose document is empty.
    """
    attr_cols = [c for c in df.columns if c not in set(RAW_COLUMNS) and c not in ("geometry", "secondary_attributes")]
    df["secondary_attributes"] = df[attr_cols].apply(
        lambda row: {k: v for k, v in row.items() if not pandas.isna(v)},
        axis=1,
    )
    empty = int((df["secondary_attributes"].apply(len) == 0).sum())
    df["secondary_attributes"] = df["secondary_attributes"].apply(
        lambda d: json.dumps(d, default=str)
    )
    return empty


def _source_from_filename(filename: str) -> str:
    """Map a source file name to its canonical source key via regex.

    The match is case-insensitive, so 'Bioenergy_V20260203.gpkg' maps to
    'bio', 'Energy_Storage_V20260203.gpkg' to 'storage', and so on.
    Returns an empty string when the file name cannot be mapped.
    """
    match = re.search(FILENAME_PATTERN, filename, re.IGNORECASE)
    if not match:
        return ""
    return match.group(1).lower()


def _compute_boundary_areas(engine: Engine) -> None:
    """Fill area (km²) for every boundary row via PostGIS geodesic area."""
    with engine.connect() as conn:
        conn.execute(
            text(
                f"UPDATE {RAW_SCHEMA}.boundaries "
                f"SET area = ST_Area(geometry::geography) / 1e6"
            )
        )
        conn.commit()


def _verify_extraction(engine: Engine, table_name: str, report: ExtractionReport) -> list[str]:
    """Verify the loaded versioned table against the extraction report.

    Checks the loaded count is consistent with the pre-dedupe source rows and
    matches the number of rows stored, and that no non-null reference_id
    appears more than once in the stored table. Returns a list of error
    strings, empty if verification passes.
    """
    errors: list[str] = []
    expected = report.source_row_count - report.duplicates_dropped
    if report.rows_loaded != expected:
        errors.append(
            f"Row count mismatch: loaded {report.rows_loaded}, expected {expected}"
        )

    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT COUNT(*) FROM {RAW_SCHEMA}.{table_name}")
        ).scalar()
        if row != report.rows_loaded:
            errors.append(
                f"Row count mismatch in {table_name}: expected {report.rows_loaded}, got {row}"
            )

        dups = conn.execute(
            text(
                f"SELECT COUNT(*) FROM ("
                f"SELECT reference_id FROM {RAW_SCHEMA}.{table_name} "
                f"WHERE reference_id IS NOT NULL "
                f"GROUP BY reference_id HAVING COUNT(*) > 1) d"
            )
        ).scalar()
        if dups > 0:
            errors.append(f"Duplicate reference_ids found in {table_name}: {dups}")

    return errors


def _verify_boundaries(engine: Engine) -> list[str]:
    """Verify the boundaries table carries levels 0-3, one level-0 row, and areas."""
    errors: list[str] = []
    with engine.connect() as conn:
        counts = dict(
            conn.execute(
                text(
                    f"SELECT level, COUNT(*) FROM {RAW_SCHEMA}.boundaries "
                    f"GROUP BY level ORDER BY level"
                )
            ).fetchall()
        )
        names = conn.execute(
            text(
                f"SELECT level, name FROM {RAW_SCHEMA}.boundaries "
                f"ORDER BY level LIMIT 1"
            )
        )

        for level in range(4):
            if level not in counts:
                errors.append(f"Boundaries missing level {level}")

        if counts.get(0, 0) != 1:
            errors.append(f"Expected exactly 1 country-outline row at level 0, got {counts.get(0)}")

        bad_area = conn.execute(
            text(
                f"SELECT COUNT(*) FROM {RAW_SCHEMA}.boundaries "
                f"WHERE area IS NULL OR area <= 0"
            )
        ).scalar()
        if bad_area:
            errors.append(f"{bad_area} boundaries have null or non-positive area")

        if not errors:
            levels = ", ".join(f"{k}:{counts[k]}" for k in sorted(counts))
            level_names = ", ".join(f"{row[1]}" for row in names.fetchall())
            log.info("Boundaries verified (%s rows; sample names: %s)", levels, level_names)

    return errors
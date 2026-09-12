from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

import pandas
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.config import RAW_SCHEMA, SERVICE_SCHEMA

FILENAME_PATTERN = r"(bio|gas|hydro|solar|wind|storage)"

RAW_COLUMNS = (
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
    "secondary_attributes",
)

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

BOUNDARY_RAW_COLUMNS = ("country_iso", "name", "geometry")


def _version_tables(engine: Engine, source: str) -> list[tuple[str, int, str]]:
    """List raw.<source>_<YYYYMMDD>_<n> tables as (day, counter, name), sorted."""
    pattern = re.compile(rf"^{re.escape(source)}_(\d{{8}})_(\d+)$")
    tables: list[tuple[str, int, str]] = []
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = :schema"
            ),
            {"schema": RAW_SCHEMA},
        ).fetchall()
    for name in (row[0] for row in rows):
        match = pattern.match(name)
        if match:
            tables.append((match.group(1), int(match.group(2)), name))
    tables.sort()
    return tables


def _next_version_table(engine: Engine, source: str, day: date) -> str:
    """Compute the next versioned table name for a source on a given day.

    Versions follow raw.<source>_<YYYYMMDD>_<n> with a per-source counter that
    resets daily: the largest existing counter for the day is incremented,
    starting at 1 when none exists.
    """
    counters = [
        n
        for (d, n, _name) in _version_tables(engine, source)
        if d == f"{day:%Y%m%d}"
    ]
    return f"{source}_{day:%Y%m%d}_{max(counters, default=0) + 1}"


def _latest_version_table(engine: Engine, source: str) -> str | None:
    """Return the most recent raw.<source>_<YYYYMMDD>_<n> table name, or None."""
    versions = _version_tables(engine, source)
    return versions[-1][2] if versions else None


def _is_logged(engine: Engine, signature: tuple[str, int, float]) -> bool:
    """True if the (filename, filesize, modified_at) load signature is logged."""
    filename, filesize, modified_at = signature
    with engine.connect() as conn:
        row = conn.execute(
            text(
                f"SELECT 1 FROM {SERVICE_SCHEMA}.loaded_files "
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
                f"INSERT INTO {SERVICE_SCHEMA}.loaded_files "
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


def _read_manifest(manifest: Path) -> list[str]:
    """Read a manifest file into a list of file names, one per line.

    Blank lines and '#' comments are dropped; each line is stripped exactly
    once.
    """
    names = [line.strip() for line in manifest.read_text().splitlines()]
    return [name for name in names if name and not name.startswith("#")]


def _compute_boundary_areas(engine: Engine) -> None:
    """Fill area (km²) for every boundary row via PostGIS geodesic area."""
    with engine.connect() as conn:
        conn.execute(
            text(
                f"UPDATE {SERVICE_SCHEMA}.boundaries "
                f"SET area = ST_Area(geometry::geography) / 1e6"
            )
        )
        conn.commit()
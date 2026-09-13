from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.db_schema import RAW_SCHEMA, SERVICE_SCHEMA, STAGING_SCHEMA, STORAGE_COLUMNS


def _ensure_schema(engine: Engine, schema: str = RAW_SCHEMA) -> None:
    """Create the given schema in the database if it does not exist."""
    with engine.connect() as conn:
        conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
        conn.commit()


def _create_log_table(engine: Engine) -> None:
    """Create the append-only loaded_files log if it does not exist."""
    with engine.connect() as conn:
        conn.execute(
            text(
                f"""
                CREATE TABLE IF NOT EXISTS {SERVICE_SCHEMA}.loaded_files (
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


def _create_staging_tables(engine: Engine, source: str) -> None:
    """Drop and recreate the source's three staging tables with constraints."""
    storage_shape = ""
    if source == "storage":
        storage_shape = (
            f"{STORAGE_COLUMNS[0]}         TEXT,\n"
            f"{STORAGE_COLUMNS[1]}  DOUBLE PRECISION,\n"
        )
    with engine.begin() as conn:
        conn.execute(
            text(f"DROP TABLE IF EXISTS {STAGING_SCHEMA}.{source}_units_properties CASCADE")
        )
        conn.execute(text(f"DROP TABLE IF EXISTS {STAGING_SCHEMA}.{source}_properties CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {STAGING_SCHEMA}.{source} CASCADE"))
        conn.execute(
            text(
                f"""
                CREATE TABLE {STAGING_SCHEMA}.{source} (
                    unit_id              TEXT PRIMARY KEY,
                    energy_source        TEXT NOT NULL,
                    {storage_shape}
                    installed_capacity   DOUBLE PRECISION,
                    commissioning_date   DATE,
                    decommissioning_date DATE,
                    geometry             geometry(Point, 4326),
                    geo_accuracy         BIGINT,
                    x_coordinates        DOUBLE PRECISION,
                    y_coordinates        DOUBLE PRECISION,
                    reference_id         TEXT,
                    reference_date       TIMESTAMP,
                    secondary_attributes TEXT,
                    country_iso          TEXT,
                    region               TEXT,
                    district             TEXT,
                    municipality         TEXT,
                    bad_quality          BOOLEAN NOT NULL
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE {STAGING_SCHEMA}.{source}_properties (
                    param_id BIGINT PRIMARY KEY,
                    name     TEXT NOT NULL,
                    value    TEXT NOT NULL,
                    UNIQUE (name, value)
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE {STAGING_SCHEMA}.{source}_units_properties (
                    unit_id  TEXT NOT NULL REFERENCES {STAGING_SCHEMA}.{source}(unit_id),
                    param_id BIGINT NOT NULL REFERENCES {STAGING_SCHEMA}.{source}_properties(param_id),
                    PRIMARY KEY (unit_id, param_id)
                )
                """
            )
        )

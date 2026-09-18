"""Read-only data access for the Streamlit viz app (issue #23).

The app queries PostGIS directly.  Under the seeded stack it connects through
the read-only `viz_reader` role via `VIZ_DATABASE_URL`, falling back to the
pipeline `DATABASE_URL` on the dev host.  `missing_core_tables` is the
standby-detection seam: with an unreachable database an engine connect raises
and the caller treats it like missing tables.

`unit_query` / `fetch_active_units` (issue #24) build and run the active-unit
queries the scatter layers render.  Both are pure seams — the SQL and its
bound params are asserted directly, and fetches run through an injectable
engine so tests never touch a real database.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from etl.db_schema import CORE_SCHEMA

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# The core tables the map renders; absent tables mean the app shows the
# "No core tables" standby map instead of a failed ``FROM core.<table>``
# (a dev/test run drops core while the app may stay open).
CORE_VIS_TABLES = ("generators", "storages")

# The single value `core.storages.energy_source` carries; generators carry
# the five loaded source labels instead.
STORAGE_SOURCE = "storage"

# Columns every fetched unit row needs for the scatter layer and its tooltip.
# Generators project UNIT_COLUMNS; storages add storage_capacity (kWh).
UNIT_COLUMNS = (
    "unit_id",
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "longitude",
    "latitude",
    "region",
    "district",
    "municipality",
)
UNIT_COLUMNS_SQL = ", ".join(UNIT_COLUMNS)
STORAGE_COLUMNS = UNIT_COLUMNS + ("storage_capacity",)
STORAGE_COLUMNS_SQL = ", ".join(STORAGE_COLUMNS)


def get_viz_engine() -> Engine:
    """Engine for the viz read path: ``VIZ_DATABASE_URL`` when present, else ``DATABASE_URL``."""
    url = os.environ.get("VIZ_DATABASE_URL") or os.environ["DATABASE_URL"]
    return create_engine(url)


def missing_core_tables(
    engine: Engine | None = None, tables: tuple[str, ...] = CORE_VIS_TABLES
) -> list[str]:
    """Core tables in ``tables`` that are absent from the ``core`` schema."""
    engine = engine or get_viz_engine()
    with engine.connect() as conn:
        present = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema"
                ),
                {"schema": CORE_SCHEMA},
            )
        }
    return [table for table in tables if table not in present]


def unit_query(
    table: str,
    columns: str,
    *,
    active_from: date,
    active_to: date,
    source: str,
) -> tuple[str, dict]:
    """SQL + bound params for the active-unit fetch on ``core.<table>``.

    ``table`` is ``"generators"`` or ``"storages"`` and ``columns`` their
    projection; both are module constants, never user input.  ``source``
    filters ``energy_source`` (storages carry the single ``"storage"`` value).
    The timescope predicate is the issue #24 single active-unit filter: units
    commissioned by ``active_to`` that are not decommissioned before
    ``active_from``.
    """
    sql = (
        f"SELECT {columns} FROM core.{table} "
        "WHERE energy_source = :source "
        "AND commissioning_date <= :to "
        "AND (decommissioning_date IS NULL OR decommissioning_date >= :from)"
    )
    params = {"source": source, "from": active_from, "to": active_to}
    return sql, params


def run_query(engine: Engine, sql: str, params: dict) -> list[dict[str, Any]]:
    """Execute ``sql`` with bound ``params``; return rows as dicts."""
    with engine.connect() as conn:
        # ``Row`` iterates as a value sequence in SQLAlchemy 2.x, so map via
        # the mapping view rather than ``dict(row)``.
        return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def fetch_active_units(
    engine: Engine,
    *,
    active_from: date,
    active_to: date,
    sources: tuple[str, ...],
) -> dict[str, list[dict[str, Any]]]:
    """energy_source → active unit rows for the checked ``sources``.

    Each checked generator source is fetched from ``core.generators``;
    ``storage`` (a single category) is fetched from ``core.storages`` once.
    """
    units: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        if source == STORAGE_SOURCE:
            table, columns = "storages", STORAGE_COLUMNS_SQL
        else:
            table, columns = "generators", UNIT_COLUMNS_SQL
        sql, params = unit_query(
            table,
            columns,
            active_from=active_from,
            active_to=active_to,
            source=source,
        )
        units[source] = run_query(engine, sql, params)
    return units

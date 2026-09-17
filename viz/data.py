"""Read-only data layer for the Dash app (issue #18).

The app queries PostGIS directly — `core.generators` / `core.storages` over
their longitude/latitude columns plus the attributes the map and hovercards
need (energy_source, capacities, commissioning/decommissioning dates, and the
region/district/municipality keys).  Under the seeded stack the app connects
through the read-only `viz_reader` role via `VIZ_DATABASE_URL` (written by the
seed script, issue #21), falling back to the pipeline `DATABASE_URL` on the
dev host.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from etl.db_schema import BOUNDARY_LEVEL_COLUMNS, CORE_SCHEMA, OUTSIDE_REGION
from viz.drill import DrillValue, drill_value

CORE_DOTENV = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(CORE_DOTENV)

GENERATOR_QUERY_COLUMNS = (
    "longitude",
    "latitude",
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "region",
    "district",
    "municipality",
)

STORAGE_QUERY_COLUMNS = GENERATOR_QUERY_COLUMNS + ("storage_capacity",)


def get_viz_engine() -> Engine:
    """Engine for the viz read path: VIZ_DATABASE_URL when present, else DATABASE_URL."""
    url = os.environ.get("VIZ_DATABASE_URL") or os.environ["DATABASE_URL"]
    return create_engine(url)


def _fetch(table: str, columns: tuple[str, ...], engine: Engine | None) -> pd.DataFrame:
    """Read the named core table's query columns over longitude/latitude order."""
    columns_sql = ", ".join(columns)
    return pd.read_sql(
        f"SELECT {columns_sql} FROM {CORE_SCHEMA}.{table} "
        "ORDER BY longitude, latitude",
        engine or get_viz_engine(),
    )


def fetch_generators(engine: Engine | None = None) -> pd.DataFrame:
    """All core.generators rows with the columns the scatter map renders."""
    return _fetch("generators", GENERATOR_QUERY_COLUMNS, engine)


def fetch_storages(engine: Engine | None = None) -> pd.DataFrame:
    """All core.storages rows; adds storage_capacity to the generator column set."""
    return _fetch("storages", STORAGE_QUERY_COLUMNS, engine)


ACTIVE_UNITS_WHERE = "decommissioning_date IS NULL OR decommissioning_date > CURRENT_DATE"


def fetch_level_fills(
    level: int,
    parent_filters: dict,
    metric: str,
    engine: Engine | None = None,
) -> pd.DataFrame:
    """Live per-area value frame for the active drill level (issue #19).

    Aggregates the ACTIVE generator+storage union (mirroring `etl.marts`
    `_ACTIVE`) by the boundary column of ``level`` — region/district/
    municipality — scoped by the accumulated ``parent_filters`` chain that a
    `viz.drill.plan_drill` produced.  ``metric`` is resolved through
    `viz.drill.drill_value`, so the value expression is the ONLY metric-aware
    part (MW sum vs unit count); the area→level query scope is identical for
    both metrics.  Returns a ``(name, value)`` frame in name order.
    """
    value: DrillValue = drill_value(metric)
    column = BOUNDARY_LEVEL_COLUMNS[level]
    where = [f"({ACTIVE_UNITS_WHERE})"]
    for name, area in parent_filters.items():
        where.append(f"{name} = '{area}'")
    scope = " AND ".join(where) if where else "TRUE"

    sql = f"""
        SELECT COALESCE({column}, '{OUTSIDE_REGION}') AS name,
               {value.value_expr} AS value
        FROM (
            SELECT {column}, installed_capacity
            FROM {CORE_SCHEMA}.generators
            WHERE {scope}
            UNION ALL
            SELECT {column}, installed_capacity
            FROM {CORE_SCHEMA}.storages
            WHERE {scope}
        ) active_units
        GROUP BY COALESCE({column}, '{OUTSIDE_REGION}')
        ORDER BY name
    """
    return pd.read_sql(sql, engine or get_viz_engine())
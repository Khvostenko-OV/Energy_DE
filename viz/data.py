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

import json
import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
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

# Env seam for the boundary GeoJSON asset directory (issue #19/#21).  Under
# the containerized stack the seed mounts the prep output here; on the dev
# host it falls back to the pipeline's own prep output directory.
VIZ_BOUNDARY_ASSET_DIR = os.environ.get(
    "VIZ_BOUNDARY_ASSET_DIR",
    str(Path(__file__).resolve().parent.parent / "data" / "viz_assets"),
)


def load_level_geojson(level: int, asset_dir: str | Path | None = None) -> dict:
    """Load the boundary GeoJSON for a drill level (1..3) as a dict."""
    directory = Path(asset_dir) if asset_dir else Path(VIZ_BOUNDARY_ASSET_DIR)
    try:
        filename = {
            1: "level_1.geojson",
            2: "level_2.geojson",
            3: "level_3.geojson",
        }[level]
    except KeyError:
        raise FileNotFoundError(
            f"no boundary asset for level {level}; drill levels are 1..3"
        ) from None
    try:
        with (directory / filename).open() as fh:
            return json.load(fh)
    except FileNotFoundError:
        raise FileNotFoundError(
            f"boundary asset {directory / filename} missing; "
            "run 'python -m etl boundaries-geojson <outdir>' (issue #17) or "
            "point VIZ_BOUNDARY_ASSET_DIR at it"
        ) from None


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
    params = {}
    for index, (name, area) in enumerate(parent_filters.items()):
        # Column names are whitelisted against the boundary schema (the chain
        # is built by plan_drill from BOUNDARY_LEVEL_COLUMNS only); the area
        # values flow from browser click data, so they are bound parameters.
        if name not in BOUNDARY_LEVEL_COLUMNS.values():
            raise ValueError(f"unknown drill filter column: {name!r}")
        param = f"area_{index}"
        where.append(f"{name} = :{param}")
        params[param] = area
    scope = " AND ".join(where) if where else "TRUE"

    sql = text(f"""
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
    """)
    return pd.read_sql(sql, engine or get_viz_engine(), params=params)
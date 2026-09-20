"""Read-only data access for the Streamlit viz app (issue #23).

The app queries PostGIS directly.  Under the seeded stack it connects through
the read-only `viz_reader` role via `VIZ_DATABASE_URL`, falling back to the
pipeline `DATABASE_URL` on the dev host.  `missing_core_tables` is the
standby-detection seam: with an unreachable database an engine connect raises
and the caller treats it like missing tables.

`unit_query` / `fetch_active_units` (issue #24) build and run the active-unit
queries the scatter layers render, and `header_metrics_query` /
`fetch_header_metrics` plus `areas_query` / `area_name_query` / `fetch_areas`
(issue #25) build and run the header aggregate queries — the capacity/count
union over the checked active units and the displayed-area count / km² sum
from `service.boundaries`.  All are pure seams: the SQL and its bound params
are asserted directly, and fetches run through an injectable engine so tests
never touch a real database.

Issue #26 adds the choropleth feeds: `boundary_names_query` /
`fetch_area_names` supply the area-multiselect options, `boundaries_query` /
`fetch_boundaries` fetch the selected areas' GeoJSON geometry, and
`boundary_fill_query` / `fetch_boundary_fill` aggregate the checked active
units per displayed area via a spatial join (capacity in MW, unit count),
under the same timescope/source filters as the scatter and header.

The header follows the selection like the scatter: `fetch_areas` takes the
optional ``names`` and `header_metrics_query` / `fetch_header_metrics` one of
the `LEVEL_UNIT_AREA_COLUMN` attributes, so with a proper subset of areas
picked the scope, area (km²), capacity and unit-count figures all narrow to
the selected areas (issue #26).  On the all-areas selection no filter applies
and every active unit counts.  `unit_query` / `fetch_active_units` use the
same attribute filter, so the scatter points show exactly the units the header
totals — with one exception: a unit sitting on a shared border is attributed
to each area it intersects (the spatial fill), while the header counts it in
its named region once.
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

# The single active-units predicate (issue #24): commissioned by ``:to`` and
# not decommissioned before ``:from``.  Shared verbatim by the scatter-layer
# unit fetches and the header aggregates, so both always resolve the same
# active set — the map and the header can't drift apart.
ACTIVE_UNIT_PREDICATE = (
    "commissioning_date >= :from "
    "AND (decommissioning_date IS NULL OR decommissioning_date >= :to)"
)

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


def _unit_table(source: str) -> str:
    """Core table carrying ``source``: ``storages`` holds the single storage
    category, ``generators`` every generator source."""
    return "storages" if source == STORAGE_SOURCE else "generators"


def unit_query(
    table: str,
    columns: str,
    *,
    active_from: date,
    active_to: date,
    source: str,
    area_column: str | None = None,
    area_names: tuple[str, ...] = (),
) -> tuple[str, dict]:
    """SQL + bound params for the active-unit fetch on ``core.<table>``.

    ``table`` is ``"generators"`` or ``"storages"`` and ``columns`` their
    projection; both are module constants, never user input.  ``source``
    filters ``energy_source`` (storages carry the single ``"storage"`` value).
    The timescope predicate is the issue #24 single active-unit filter: units
    commissioned by ``active_to`` that are not decommissioned before
    ``active_from``.

    ``area_column`` narrows the rows to ``area_names`` (``ANY(:area_names)``)
    when both are given — the unit attribute naming the selected areas from
    `LEVEL_UNIT_AREA_COLUMN` (issue #26), a config constant like ``table``
    rather than user input.  Without them every active unit qualifies.
    """
    sql = (
        f"SELECT {columns} FROM core.{table} "
        "WHERE energy_source = :source "
        f"AND {ACTIVE_UNIT_PREDICATE}"
    )
    params = {"source": source, "from": active_from, "to": active_to}
    if area_column and area_names:
        sql += f" AND {area_column} = ANY(:area_names)"
        params["area_names"] = list(area_names)
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
    area_column: str | None = None,
    area_names: tuple[str, ...] = (),
) -> dict[str, list[dict[str, Any]]]:
    """energy_source → active unit rows for the checked ``sources``.

    Each checked generator source is fetched from ``core.generators``;
    ``storage`` (a single category) is fetched from ``core.storages`` once.
    ``area_column`` / ``area_names`` narrow every fetch to the selected areas
    (issue #26); None/empty leaves the points unfiltered.
    """
    units: dict[str, list[dict[str, Any]]] = {}
    for source in sources:
        table = _unit_table(source)
        columns = STORAGE_COLUMNS_SQL if table == "storages" else UNIT_COLUMNS_SQL
        sql, params = unit_query(
            table,
            columns,
            active_from=active_from,
            active_to=active_to,
            source=source,
            area_column=area_column,
            area_names=area_names,
        )
        units[source] = run_query(engine, sql, params)
    return units


def areas_query(level: int, names: tuple[str, ...] | None = None) -> tuple[str, dict]:
    """SQL + bound params for the displayed-area header: count and km² sum.

    Counts ``service.boundaries`` rows at ``level`` and sums their stored
    ``area`` column (km²).  ``names`` narrows the displayed areas (issue #26);
    None means every area at the level.  Sea/EEZ polygons live at level 1 and
    count like any other region — documented, not special-cased (issue #25).
    """
    sql = (
        "SELECT COUNT(*) AS area_count, "
        "COALESCE(SUM(area), 0.0) AS total_area "
        "FROM service.boundaries WHERE level = :level"
    )
    params: dict = {"level": level}
    if names is not None:
        sql += " AND name = ANY(:names)"
        params["names"] = list(names)
    return sql, params


def area_name_query(
    level: int, names: tuple[str, ...] | None = None
) -> tuple[str, dict]:
    """SQL + bound params for the single displayed area's name."""
    sql = "SELECT name FROM service.boundaries WHERE level = :level"
    params: dict = {"level": level}
    if names is not None:
        sql += " AND name = ANY(:names)"
        params["names"] = list(names)
    return sql, params


def fetch_areas(
    engine: Engine, level: int, names: tuple[str, ...] | None = None
) -> dict[str, Any]:
    """Area figures for the header at ``level``: count, km² sum, and — when
    exactly one area is displayed — its name.

    The displayed areas are the optional ``names`` selection (default: every
    area at the level).  The name is fetched only when ``COUNT(*)`` is 1, so
    the region/district/municipality levels (many rows) never read the name
    back.
    """
    sql, params = areas_query(level, names)
    row = run_query(engine, sql, params)[0]
    areas: dict[str, Any] = {
        "area_count": row["area_count"],
        "total_area_km2": row["total_area"],
    }
    if areas["area_count"] == 1:
        name_sql, _ = area_name_query(level, names)
        areas["area_name"] = run_query(engine, name_sql, params)[0]["name"]
    return areas


def header_metrics_query(
    active_from: date,
    active_to: date,
    sources: tuple[str, ...],
    area_column: str | None = None,
    area_names: tuple[str, ...] = (),
) -> tuple[str, dict]:
    """SQL + bound params for the header's active-unit aggregates.

    One single-column ``installed_capacity`` subquery per checked source,
    under the issue #24 predicate — the same filter ``unit_query`` applies to
    the scatter layers — wrapped in an aggregate that counts rows and sums
    installed capacity (kW) ÷ 1000 → MW.  Storage's single category reads
    ``core.storages`` like the unit fetches; every other source reads
    ``core.generators``.

    ``area_column`` narrows every subquery to ``area_names`` when both are
    given (a `LEVEL_UNIT_AREA_COLUMN` constant, issue #26), so the header
    totals follow the selected areas exactly like the scatter points.
    """
    parts: list[str] = []
    params: dict[str, date | str] = {"from": active_from, "to": active_to}
    for n, source in enumerate(sources):
        table = _unit_table(source)
        parts.append(
            f"SELECT installed_capacity FROM core.{table} "
            f"WHERE energy_source = :source_{n} "
            f"AND {ACTIVE_UNIT_PREDICATE}"
            + (f" AND {area_column} = ANY(:area_names)" if area_column and area_names else "")
        )
        params[f"source_{n}"] = source
    if area_column and area_names:
        params["area_names"] = list(area_names)
    if not parts:
        raise ValueError("sources must contain at least one entry")
    sql = (
        "SELECT COUNT(*) AS unit_count, "
        "COALESCE(SUM(installed_capacity), 0.0) / 1000.0 AS capacity_mw "
        f"FROM ({' UNION ALL '.join(parts)}) AS units"
    )
    return sql, params


def fetch_header_metrics(
    engine: Engine,
    *,
    active_from: date,
    active_to: date,
    sources: tuple[str, ...],
    area_column: str | None = None,
    area_names: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Header capacity (MW) and active-unit count for the checked sources.

    ``area_column`` / ``area_names`` narrow the totals to the selected areas
    (issue #26).  With nothing checked the header reads zeros and no query
    runs — the same contract the empty-unit-fetch satisfies for the scatter
    layers.
    """
    if not sources:
        return {"unit_count": 0, "capacity_mw": 0.0}
    sql, params = header_metrics_query(
        active_from,
        active_to,
        sources,
        area_column=area_column,
        area_names=area_names,
    )
    return run_query(engine, sql, params)[0]


def boundary_names_query(level: int) -> tuple[str, dict]:
    """SQL + bound params for the area-multiselect options at ``level``.

    Returns the area names of ``service.boundaries`` ordered alphabetically,
    so the multiselect options (and the fit-view scope signature) stay stable
    across reruns regardless of storage order.
    """
    sql = "SELECT name FROM service.boundaries WHERE level = :level ORDER BY name"
    return sql, {"level": level}


def fetch_area_names(engine: Engine, level: int) -> list[str]:
    """Area names at ``level`` for the multiselect, in stable order."""
    sql, params = boundary_names_query(level)
    return [row["name"] for row in run_query(engine, sql, params)]


def boundaries_query(
    level: int, names: tuple[str, ...] | None = None
) -> tuple[str, dict]:
    """SQL + bound params for the choropleth boundary geometry.

    One row per displayed area with its name and GeoJSON geometry
    (``ST_AsGeoJSON``, WGS-84).  ``names`` narrows the displayed areas
    (issue #26); None means every area at the level.  The name is the join key
    the choropleth seam matches fill rows against.
    """
    sql = (
        "SELECT name, ST_AsGeoJSON(geometry) AS geojson "
        "FROM service.boundaries WHERE level = :level"
    )
    params: dict = {"level": level}
    if names is not None:
        sql += " AND name = ANY(:names)"
        params["names"] = list(names)
    sql += " ORDER BY name"
    return sql, params


def fetch_boundaries(
    engine: Engine, *, level: int, names: tuple[str, ...] | None = None
) -> list[dict[str, Any]]:
    """Boundary rows (name + GeoJSON text) for the displayed scope."""
    sql, params = boundaries_query(level, names)
    return run_query(engine, sql, params)


def boundary_fill_query(
    level: int,
    *,
    names: tuple[str, ...] | None,
    active_from: date,
    active_to: date,
    sources: tuple[str, ...],
) -> tuple[str, dict]:
    """SQL + bound params for the per-area choropleth fill.

    Aggregates the checked active units per displayed area: total installed
    capacity (kW) ÷ 1000 → MW and the unit count.  The unit rows come from the
    same per-source union the scatter and header use (`_unit_table` +
    `ACTIVE_UNIT_PREDICATE`), spatially joined with ``ST_Intersects`` — the
    pipeline's own spatial-join predicate (transform `sjoin intersects`).  A
    unit sitting exactly on a shared border intersects both areas and is
    attributed to each, so the per-area fills do not strictly reconcile with
    the header total — same semantics as the pipeline's own spatial join.  A
    ``LEFT JOIN`` keeps every displayed area in the result even when no active
    unit falls inside it: it reads a zero fill (issue #26).
    """
    parts: list[str] = []
    params: dict = {"level": level, "from": active_from, "to": active_to}
    for n, source in enumerate(sources):
        table = _unit_table(source)
        parts.append(
            f"SELECT unit_id, installed_capacity, geometry FROM core.{table} "
            f"WHERE energy_source = :source_{n} "
            f"AND {ACTIVE_UNIT_PREDICATE}"
        )
        params[f"source_{n}"] = source
    if not parts:
        raise ValueError("sources must contain at least one entry")
    if names is not None:
        params["names"] = list(names)
    sql = (
        "SELECT b.name AS name, "
        "COALESCE(SUM(u.installed_capacity), 0.0) / 1000.0 AS capacity_mw, "
        "COUNT(u.unit_id) AS unit_count "
        "FROM service.boundaries AS b "
        "LEFT JOIN (" + " UNION ALL ".join(parts) + ") AS u "
        "ON ST_Intersects(b.geometry, u.geometry) "
        "WHERE b.level = :level"
        + (" AND b.name = ANY(:names)" if names is not None else "")
        + " GROUP BY b.name"
    )
    return sql, params


def fetch_boundary_fill(
    engine: Engine,
    *,
    level: int,
    names: tuple[str, ...] | None,
    active_from: date,
    active_to: date,
    sources: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Per-area capacity (MW) and unit count for the choropleth fill.

    With nothing checked the choropleth reads an empty fill (every displayed
    area renders the zero fill via the join's default) and no query runs.
    """
    if not sources:
        return []
    sql, params = boundary_fill_query(
        level,
        names=names,
        active_from=active_from,
        active_to=active_to,
        sources=sources,
    )
    return run_query(engine, sql, params)

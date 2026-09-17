"""Integration tests for the viz data layer (issue #18).

Run against the live dev PostGIS (`DATABASE_URL`).  The module-scoped fixture
loads both core kinds fresh and drops them on teardown — mirroring the other
core-consuming modules — so `core.generators` / `core.storages` fully exist
for the query assertions regardless of test ordering.
"""

import os

import pytest
from sqlalchemy import create_engine, text

from etl.db_schema import BOUNDARY_LEVEL_COLUMNS, CORE_SCHEMA, OUTSIDE_REGION
from etl.load import load_generators, load_storages
from viz.data import (
    GENERATOR_QUERY_COLUMNS,
    STORAGE_QUERY_COLUMNS,
    fetch_generators,
    fetch_level_fills,
    fetch_storages,
    get_viz_engine,
)
from viz.drill import CAPACITY_MW, UNIT_COUNT
from viz.palette import ENERGY_COLORS

ENGINE = create_engine(os.environ["DATABASE_URL"])

CORE_TABLES = (
    ("generators", "generator_units_properties", "generator_properties"),
    ("storages", "storage_units_properties", "storage_properties"),
)


def _drop_core():
    with ENGINE.begin() as conn:
        for table, links, props in CORE_TABLES:
            conn.execute(text(f"DROP TABLE IF EXISTS {CORE_SCHEMA}.{links} CASCADE"))
            conn.execute(text(f"DROP TABLE IF EXISTS {CORE_SCHEMA}.{props} CASCADE"))
            conn.execute(text(f"DROP TABLE IF EXISTS {CORE_SCHEMA}.{table} CASCADE"))


def _scalar(sql: str):
    with ENGINE.connect() as conn:
        return conn.execute(text(sql)).scalar()


@pytest.fixture(scope="module")
def _core_loaded():
    """Load both core kinds fresh; drop them again at module teardown."""
    _drop_core()
    gen_report = load_generators()
    sto_report = load_storages()
    assert gen_report.passed, gen_report.errors
    assert sto_report.passed, sto_report.errors
    yield
    _drop_core()


@pytest.fixture(scope="module", autouse=True)
def _staging_ready(_staged_sources):
    """Staging is transformed once per session; nothing to do here."""


# ------------------------------------------------------------------ #
#  Engine selection                                                   #
# ------------------------------------------------------------------ #


class TestEngine:
    def test_get_viz_engine_uses_database_url_when_viz_url_absent(self, monkeypatch):
        monkeypatch.delenv("VIZ_DATABASE_URL", raising=False)
        engine = get_viz_engine()
        expected = create_engine(os.environ["DATABASE_URL"])
        assert str(engine.url) == str(expected.url)

    def test_get_viz_engine_prefers_viz_database_url(self, monkeypatch):
        monkeypatch.setenv(
            "VIZ_DATABASE_URL", "postgresql://viz_reader@localhost:5432/energy_de"
        )
        engine = get_viz_engine()
        assert engine.url.username == "viz_reader"
        assert engine.url.database == "energy_de"


# ------------------------------------------------------------------ #
#  Query shape                                                        #
# ------------------------------------------------------------------ #


class TestQueryShape:
    def test_generators_query_returns_expected_columns(self, _core_loaded):
        df = fetch_generators(ENGINE)
        assert set(df.columns) == set(GENERATOR_QUERY_COLUMNS)

    def test_storages_query_returns_expected_columns(self, _core_loaded):
        df = fetch_storages(ENGINE)
        assert set(df.columns) == set(STORAGE_QUERY_COLUMNS)

    def test_generators_are_non_empty(self, _core_loaded):
        assert not fetch_generators(ENGINE).empty

    def test_storages_are_non_empty(self, _core_loaded):
        assert not fetch_storages(ENGINE).empty


# ------------------------------------------------------------------ #
#  Row counts match core                                              #
# ------------------------------------------------------------------ #


class TestRowCounts:
    def test_generators_row_count_matches_core(self, _core_loaded):
        df = fetch_generators(ENGINE)
        stored = int(_scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators"))
        assert len(df) == stored

    def test_storages_row_count_matches_core(self, _core_loaded):
        df = fetch_storages(ENGINE)
        stored = int(_scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.storages"))
        assert len(df) == stored


# ------------------------------------------------------------------ #
#  Value sanity                                                       #
# ------------------------------------------------------------------ #


class TestValues:
    def test_generators_coordinates_are_world_bounds(self, _core_loaded):
        df = fetch_generators(ENGINE)
        assert df["longitude"].between(-180, 180).all()
        assert df["latitude"].between(-90, 90).all()

    def test_storages_coordinates_are_world_bounds(self, _core_loaded):
        df = fetch_storages(ENGINE)
        assert df["longitude"].between(-180, 180).all()
        assert df["latitude"].between(-90, 90).all()

    def test_generators_energy_sources_are_the_five_generator_sources(self, _core_loaded):
        df = fetch_generators(ENGINE)
        assert set(df["energy_source"]) == {"bio", "gas", "hydro", "solar", "wind"}
        assert set(df["energy_source"]) <= set(ENERGY_COLORS)

    def test_storages_are_the_storage_kind(self, _core_loaded):
        df = fetch_storages(ENGINE)
        assert set(df["energy_source"]) == {"storage"}

    def test_region_keys_are_largely_populated(self, _core_loaded):
        for frame in (fetch_generators(ENGINE), fetch_storages(ENGINE)):
            for column in ("region", "district", "municipality"):
                assert column in frame.columns
                assert frame[column].notna().mean() > 0.5, f"{column} mostly null"


# ------------------------------------------------------------------ #
#  Live level fills (issue #19)                                       #
# ------------------------------------------------------------------ #


def _direct_fills_sql(level, parent_filters):
    """One live GROUP BY over core for the drill level + parent chain.

    Mirrors `viz.data.fetch_level_fills` semantics on purpose so the seam is
    pinned against a fresh, hand-written aggregation of the same core tables
    (the marts-style reconcile guarantee: stored/live + direct must agree).
    """
    column = BOUNDARY_LEVEL_COLUMNS[level]
    where = []
    for name, area in parent_filters.items():
        where.append(f"'{area}' = {name}")
    scope = " AND ".join(where)
    scope = f" WHERE {scope}" if scope else ""
    return f"""
        SELECT COALESCE({column}, '{OUTSIDE_REGION}') AS name
        FROM (
            SELECT {column} FROM {CORE_SCHEMA}.generators{scope}
            UNION ALL
            SELECT {column} FROM {CORE_SCHEMA}.storages{scope}
        ) active
        GROUP BY COALESCE({column}, '{OUTSIDE_REGION}')
    """


class TestLevelFills:
    def test_level_1_capacity_fills_reconcile_to_direct_core_sql(self, _core_loaded):
        fills = fetch_level_fills(1, {}, CAPACITY_MW, ENGINE)
        expected_sql = _direct_fills_sql(1, {})
        assert set(fills.columns) == {"name", "value"}
        assert set(fills["name"]) == set(_scalar_df(expected_sql))

    def test_level_1_unit_count_fills_reconcile_to_direct_core_sql(self, _core_loaded):
        fills = fetch_level_fills(1, {}, UNIT_COUNT, ENGINE)
        expected_sql = _direct_fills_sql(1, {})
        assert set(fills.columns) == {"name", "value"}
        assert set(fills["name"]) == set(_scalar_df(expected_sql))

    def test_level_2_fills_scoped_by_region_parent(self, _core_loaded):
        fills = fetch_level_fills(2, {"region": "Hessen"}, CAPACITY_MW, ENGINE)
        assert not fills.empty
        assert set(fills["name"]) == set(_scalar_df(_direct_fills_sql(2, {"region": "Hessen"})))

    def test_level_3_fills_scoped_by_region_and_district_parents(self, _core_loaded):
        fills = fetch_level_fills(
            3, {"region": "Hessen", "district": "Kassel"}, UNIT_COUNT, ENGINE
        )
        assert not fills.empty
        expected = set(
            _scalar_df(
                _direct_fills_sql(3, {"region": "Hessen", "district": "Kassel"})
            )
        )
        assert set(fills["name"]) == expected

    def test_both_metrics_share_the_area_set(self, _core_loaded):
        cap = fetch_level_fills(2, {"region": "Hessen"}, CAPACITY_MW, ENGINE)
        count = fetch_level_fills(2, {"region": "Hessen"}, UNIT_COUNT, ENGINE)
        assert set(cap["name"]) == set(count["name"])


def _scalar_df(sql):
    """Column of a query result as a python list (the direct-SQL oracle)."""
    with ENGINE.connect() as conn:
        return [row[0] for row in conn.execute(text(sql)).fetchall()]
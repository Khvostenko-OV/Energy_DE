"""Unit tests for the viz data-access seam (issue #23).

Two seams live in `viz.data`: the engine selection (`VIZ_DATABASE_URL` with a
`DATABASE_URL` fallback) and the standby detection (`missing_core_tables`).
Neither touches a real database — the engine tests only build engines and the
standby tests drive a stub engine whose rows mimic `information_schema`.
"""

import os
from contextlib import nullcontext
from datetime import date

from sqlalchemy import create_engine

from viz.data import (
    CORE_VIS_TABLES,
    STORAGE_COLUMNS_SQL,
    UNIT_COLUMNS_SQL,
    fetch_active_units,
    get_viz_engine,
    missing_core_tables,
    run_query,
    unit_query,
)


class _StubRows:
    def __init__(self, names):
        self._names = list(names)

    def __iter__(self):
        return iter((name,) for name in self._names)


class _StubConnection:
    def __init__(self, names):
        self._names = names

    def execute(self, query, params=None):
        return _StubRows(self._names)


class _StubEngine:
    """Fake SQLAlchemy engine: connect() yields rows for the named tables."""

    def __init__(self, names):
        self._names = names

    def connect(self):
        return nullcontext(_StubConnection(self._names))


class TestEngineSelection:
    def test_uses_database_url_when_viz_url_absent(self, monkeypatch):
        monkeypatch.delenv("VIZ_DATABASE_URL", raising=False)
        engine = get_viz_engine()
        expected = create_engine(os.environ["DATABASE_URL"])
        assert str(engine.url) == str(expected.url)

    def test_prefers_viz_database_url(self, monkeypatch):
        monkeypatch.setenv("VIZ_DATABASE_URL", "postgresql://viz_reader@localhost:5432/energy_de")
        engine = get_viz_engine()
        assert engine.url.username == "viz_reader"
        assert engine.url.database == "energy_de"


class TestStandbyDetection:
    def test_no_missing_tables_when_all_present(self):
        assert missing_core_tables(_StubEngine(["generators", "storages"])) == []

    def test_returns_absent_tables_in_order(self):
        assert missing_core_tables(_StubEngine(["storages"])) == ["generators"]

    def test_all_missing_when_core_is_empty(self):
        assert missing_core_tables(_StubEngine([])) == ["generators", "storages"]

    def test_known_core_vis_tables(self):
        assert CORE_VIS_TABLES == ("generators", "storages")


class _RecordingConnection:
    """Connection that records (sql, params) pairs and returns no rows."""

    def __init__(self, engine):
        self.engine = engine

    def execute(self, query, params=None):
        self.engine.calls.append((str(query), params))
        return []


class _RecordingEngine:
    """Fake SQLAlchemy engine: records queries, executes nothing."""

    def __init__(self):
        self.calls = []

    def connect(self):
        return nullcontext(_RecordingConnection(self))


class TestUnitQuery:
    def test_generator_query_targets_core_generators_with_unit_columns(self):
        sql, params = unit_query(
            "generators",
            UNIT_COLUMNS_SQL,
            active_from=date(1990, 1, 1),
            active_to=date(2010, 1, 1),
            source="solar",
        )
        assert sql == (
            "SELECT unit_id, energy_source, installed_capacity, commissioning_date, "
            "decommissioning_date, longitude, latitude, region, district, municipality "
            "FROM core.generators "
            "WHERE energy_source = :source "
            "AND commissioning_date <= :to "
            "AND (decommissioning_date IS NULL OR decommissioning_date >= :from)"
        )

    def test_storage_query_adds_storage_capacity(self):
        sql, _ = unit_query(
            "storages",
            STORAGE_COLUMNS_SQL,
            active_from=date(1990, 1, 1),
            active_to=date(2010, 1, 1),
            source="storage",
        )
        assert sql.startswith(
            "SELECT unit_id, energy_source, installed_capacity, commissioning_date, "
            "decommissioning_date, longitude, latitude, region, district, municipality, "
            "storage_capacity FROM core.storages "
        )

    def test_timescope_is_the_single_active_predicate_with_bound_params(self):
        sql, params = unit_query(
            "generators",
            UNIT_COLUMNS_SQL,
            active_from=date(1990, 1, 1),
            active_to=date(2010, 1, 1),
            source="solar",
        )
        assert "commissioning_date <= :to" in sql
        assert "decommissioning_date IS NULL OR decommissioning_date >= :from" in sql
        assert params == {
            "source": "solar",
            "from": date(1990, 1, 1),
            "to": date(2010, 1, 1),
        }


class TestFetchActiveUnits:
    def test_queries_storages_once_and_generators_per_checked_source(self):
        engine = _RecordingEngine()
        result = fetch_active_units(
            engine,
            active_from=date(2020, 1, 1),
            active_to=date(2021, 1, 1),
            sources=("solar", "wind", "storage"),
        )
        assert [sql for sql, _ in engine.calls] == [
            "SELECT unit_id, energy_source, installed_capacity, commissioning_date, "
            "decommissioning_date, longitude, latitude, region, district, municipality "
            "FROM core.generators "
            "WHERE energy_source = :source "
            "AND commissioning_date <= :to "
            "AND (decommissioning_date IS NULL OR decommissioning_date >= :from)",
            "SELECT unit_id, energy_source, installed_capacity, commissioning_date, "
            "decommissioning_date, longitude, latitude, region, district, municipality "
            "FROM core.generators "
            "WHERE energy_source = :source "
            "AND commissioning_date <= :to "
            "AND (decommissioning_date IS NULL OR decommissioning_date >= :from)",
            "SELECT unit_id, energy_source, installed_capacity, commissioning_date, "
            "decommissioning_date, longitude, latitude, region, district, municipality, "
            "storage_capacity FROM core.storages "
            "WHERE energy_source = :source "
            "AND commissioning_date <= :to "
            "AND (decommissioning_date IS NULL OR decommissioning_date >= :from)",
        ]
        assert [params for _, params in engine.calls] == [
            {"source": "solar", "from": date(2020, 1, 1), "to": date(2021, 1, 1)},
            {"source": "wind", "from": date(2020, 1, 1), "to": date(2021, 1, 1)},
            {"source": "storage", "from": date(2020, 1, 1), "to": date(2021, 1, 1)},
        ]
        assert list(result) == ["solar", "wind", "storage"]


class _MappingRow:
    def __init__(self, **values):
        self._mapping = values


class _RowsConnection:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, query, params=None):
        return self.rows


class _RowsEngine:
    def __init__(self, rows):
        self.rows = rows

    def connect(self):
        return nullcontext(_RowsConnection(self.rows))


class TestRunQuery:
    def test_rows_come_back_as_dicts(self):
        rows = [_MappingRow(unit_id=1, energy_source="solar", installed_capacity=120.0)]
        result = run_query(
            _RowsEngine(rows),
            "SELECT ... FROM core.generators",
            {"source": "solar"},
        )
        assert result == [
            {"unit_id": 1, "energy_source": "solar", "installed_capacity": 120.0}
        ]

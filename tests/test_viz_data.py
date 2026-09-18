"""Unit tests for the viz data-access seams (issues #23, #25).

Seams live in `viz.data`: the engine selection (`VIZ_DATABASE_URL` with a
`DATABASE_URL` fallback), the standby detection (`missing_core_tables`), the
active-unit fetches (issue #24), and the header aggregates (issue #25) — the
capacity/count union over checked active units plus the displayed-area count
and km² sum from `service.boundaries`.  None touch a real database: the
engine tests only build engines, the standby tests drive a stub engine whose
rows mimic `information_schema`, and the fetch tests drive recording or
row-returning stub engines.
"""

import os
from contextlib import nullcontext
from datetime import date

import pytest
from sqlalchemy import create_engine

from viz.data import (
    CORE_VIS_TABLES,
    STORAGE_COLUMNS_SQL,
    UNIT_COLUMNS_SQL,
    area_name_query,
    areas_query,
    fetch_active_units,
    fetch_areas,
    fetch_header_metrics,
    get_viz_engine,
    header_metrics_query,
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


class TestAreasQuery:
    def test_counts_and_sums_area_at_the_level(self):
        sql, params = areas_query(1)
        assert sql == (
            "SELECT COUNT(*) AS area_count, "
            "COALESCE(SUM(area), 0.0) AS total_area "
            "FROM service.boundaries WHERE level = :level"
        )
        assert params == {"level": 1}

    def test_offshore_area_is_not_special_cased(self):
        sql, _ = areas_query(1)
        assert "area" in sql
        assert "filter" not in sql


class TestAreaNameQuery:
    def test_selects_the_single_displayed_area_name(self):
        sql, params = area_name_query(0)
        assert sql == "SELECT name FROM service.boundaries WHERE level = :level"
        assert params == {"level": 0}


class _AreasStub:
    """Stub engine whose rows depend on the executed query (count/name)."""

    def __init__(self, count, name):
        self._count = count
        self._name = name
        self.calls = []

    def connect(self):
        return nullcontext(_AreasConnection(self))


class _AreasConnection:
    def __init__(self, stub):
        self._stub = stub

    def execute(self, query, params=None):
        self._stub.calls.append((str(query), params))
        if "COUNT" in str(query):
            return [_MappingRow(area_count=self._stub._count, total_area=357588.4)]
        return [_MappingRow(name=self._stub._name)]


class TestFetchAreas:
    def test_returns_count_and_km2_sum(self):
        rows = [_MappingRow(area_count=19, total_area=357588.4)]
        result = fetch_areas(_RowsEngine(rows), 1)
        assert result["area_count"] == 19
        assert result["total_area_km2"] == 357588.4

    def test_adds_the_area_name_when_exactly_one_area(self):
        stub = _AreasStub(count=1, name="Germany")
        result = fetch_areas(stub, 0)
        assert result["area_name"] == "Germany"

    def test_exactly_one_area_triggers_the_name_query(self):
        stub = _AreasStub(count=1, name="Germany")
        fetch_areas(stub, 0)
        assert [sql for sql, _ in stub.calls] == [
            "SELECT COUNT(*) AS area_count, "
            "COALESCE(SUM(area), 0.0) AS total_area "
            "FROM service.boundaries WHERE level = :level",
            "SELECT name FROM service.boundaries WHERE level = :level",
        ]

    def test_no_name_key_when_many_areas(self):
        stub = _AreasStub(count=19, name="Germany")
        result = fetch_areas(stub, 1)
        assert "area_name" not in result
        assert len(stub.calls) == 1


class TestHeaderMetricsQuery:
    def test_generator_sources_read_core_generators(self):
        sql, _ = header_metrics_query(
            date(1990, 1, 1), date(2010, 1, 1), sources=("solar", "wind")
        )
        assert sql == (
            "SELECT COUNT(*) AS unit_count, "
            "COALESCE(SUM(installed_capacity), 0.0) / 1000.0 AS capacity_mw "
            "FROM ("
            "SELECT installed_capacity FROM core.generators "
            "WHERE energy_source = :source_0 "
            "AND commissioning_date <= :to "
            "AND (decommissioning_date IS NULL OR decommissioning_date >= :from)"
            " UNION ALL "
            "SELECT installed_capacity FROM core.generators "
            "WHERE energy_source = :source_1 "
            "AND commissioning_date <= :to "
            "AND (decommissioning_date IS NULL OR decommissioning_date >= :from)"
            ") AS units"
        )

    def test_storage_source_reads_core_storages(self):
        sql, _ = header_metrics_query(
            date(1990, 1, 1), date(2010, 1, 1), sources=("solar", "storage")
        )
        assert (
            "SELECT installed_capacity FROM core.storages "
            "WHERE energy_source = :source_1 " in sql
        )
        assert "FROM core.generators" in sql

    def test_predicate_matches_the_unit_fetch(self):
        sql, _ = header_metrics_query(
            date(1990, 1, 1), date(2010, 1, 1), sources=("wind",)
        )
        assert "commissioning_date <= :to" in sql
        assert "decommissioning_date IS NULL OR decommissioning_date >= :from" in sql

    def test_capacity_is_kw_sum_divided_by_1000(self):
        sql, _ = header_metrics_query(
            date(1990, 1, 1), date(2010, 1, 1), sources=("wind",)
        )
        assert "COALESCE(SUM(installed_capacity), 0.0) / 1000.0 AS capacity_mw" in sql

    def test_params_are_bound_per_source_plus_timescope(self):
        sql, params = header_metrics_query(
            date(1990, 1, 1), date(2010, 1, 1), sources=("solar", "storage")
        )
        assert params == {
            "from": date(1990, 1, 1),
            "to": date(2010, 1, 1),
            "source_0": "solar",
            "source_1": "storage",
        }

    def test_empty_sources_are_rejected(self):
        with pytest.raises(ValueError):
            header_metrics_query(date(1990, 1, 1), date(2010, 1, 1), sources=())


class TestFetchHeaderMetrics:
    def test_returns_capacity_and_unit_count(self):
        rows = [_MappingRow(unit_count=3, capacity_mw=12.0)]
        result = fetch_header_metrics(
            _RowsEngine(rows),
            active_from=date(2020, 1, 1),
            active_to=date(2021, 1, 1),
            sources=("wind",),
        )
        assert result == {"unit_count": 3, "capacity_mw": 12.0}

    def test_empty_sources_yield_zero_without_a_query(self):
        engine = _RecordingEngine()
        result = fetch_header_metrics(
            engine,
            active_from=date(2020, 1, 1),
            active_to=date(2021, 1, 1),
            sources=(),
        )
        assert engine.calls == []
        assert result == {"unit_count": 0, "capacity_mw": 0.0}

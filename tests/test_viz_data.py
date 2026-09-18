"""Unit tests for the viz data-access seam (issue #23).

Two seams live in `viz.data`: the engine selection (`VIZ_DATABASE_URL` with a
`DATABASE_URL` fallback) and the standby detection (`missing_core_tables`).
Neither touches a real database — the engine tests only build engines and the
standby tests drive a stub engine whose rows mimic `information_schema`.
"""

import os
from contextlib import nullcontext

from sqlalchemy import create_engine

from viz.data import CORE_VIS_TABLES, get_viz_engine, missing_core_tables


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

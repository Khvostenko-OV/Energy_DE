"""Shared session-scoped fixtures (one transform per test session)."""

import pytest

from etl.config import SOURCE_NAMES
from etl.transform import transform_sorces


@pytest.fixture(scope="session")
def _staged_sources():
    """Transform all six sources into staging once per session.

    Every module's `_staging_ready` / `_transformed_all` autouse fixture
    depends on this instead of re-transforming, so the whole suite pays for
    the spatial joins exactly once.  Sharing is safe because every test that
    mutates staging restores it (or re-transforms the affected source in a
    `finally`).
    """
    for source in SOURCE_NAMES:
        report = transform_sorces(source)
        assert report.passed, report.errors
"""Precondition guards: transform/load fail cleanly, never raise.

`python -m etl transform` requires a raw.<source>_* version table and
`python -m etl load` requires the staging tables; when they are absent the
stage must report a clear, submitted-style failure instead of crashing with an
undifferentiated exception.  The transform guard is exercised through the
public `transform_source` with an unknown source name (no raw tables exist for
it); the load guard is exercised through `_load` with a fabricated kind whose
staging sources do not exist.  Both tests are non-destructive — they do not
drop, rename, or rebuild any real tables.
"""

import os

from sqlalchemy import create_engine

from etl.load import _load, _CoreKind
from etl.transform import transform_source

ENGINE = create_engine(os.environ["DATABASE_URL"])


def test_transform_fails_cleanly_when_raw_tables_missing():
    report = transform_source("nonexistent_source")

    assert not report.passed
    assert report.raw_table is None
    assert report.rows_read == 0
    assert len(report.errors) == 1
    message = report.errors[0]
    assert "raw tables missing for source 'nonexistent_source'" in message
    assert "run 'python -m etl extract' first" in message


def test_load_fails_cleanly_when_staging_tables_missing():
    kind = _CoreKind(
        core_table="generators",
        staging_sources=("nonexistent_staging",),
        properties_table="generator_properties",
        units_properties_table="generator_units_properties",
        column_map={},
        onshore_sources=(),
        check_storage_capacity=False,
        verifier=lambda engine, report: [],
        create_table=lambda engine: None,
    )

    report = _load(kind)

    assert not report.passed
    assert report.rows_read == 0
    assert len(report.errors) == 1
    message = report.errors[0]
    assert "staging tables missing for generators" in message
    assert "run 'python -m etl transform' first" in message
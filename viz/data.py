"""Read-only data access for the Streamlit viz app (issue #23).

The app queries PostGIS directly.  Under the seeded stack it connects through
the read-only `viz_reader` role via `VIZ_DATABASE_URL`, falling back to the
pipeline `DATABASE_URL` on the dev host.  `missing_core_tables` is the
standby-detection seam: with an unreachable database an engine connect raises
and the caller treats it like missing tables.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from etl.db_schema import CORE_SCHEMA

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# The core tables the map renders; absent tables mean the app shows the
# "No core tables" standby map instead of a failed ``FROM core.<table>``
# (a dev/test run drops core while the app may stay open).
CORE_VIS_TABLES = ("generators", "storages")


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

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")

# Database schema names, overridable via env (defaults shown).  This module is
# the single home for `.env`-driven settings: `etl.db_schema` re-exports these
# names so `from etl.db_schema import ...` callers keep working.
RAW_SCHEMA = os.environ.get("RAW_SCHEMA", "raw")
STAGING_SCHEMA = os.environ.get("STAGING_SCHEMA", "stage")
CORE_SCHEMA = os.environ.get("CORE_SCHEMA", "core")
SERVICE_SCHEMA = os.environ.get("SERVICE_SCHEMA", "service")
MARTS_SCHEMA = os.environ.get("MARTS_SCHEMA", "marts")

SOURCE_NAMES = ("bio", "gas", "hydro", "solar", "wind", "storage")


def sources_data_dir() -> Path:
    """Resolve the unit sources folder (default: <repo>/data/sources)."""
    return Path(os.environ.get("SOURCES_DATA_DIR", str(REPO_ROOT / "data" / "sources")))


def boundaries_manifest() -> Path:
    """Resolve the boundaries manifest path (default: <repo>/data/boundaries/boundaries.txt)."""
    return Path(
        os.environ.get("BOUNDARIES_MANIFEST", str(REPO_ROOT / "data" / "boundaries" / "boundaries.txt"))
    )


def get_engine():
    url = os.environ["DATABASE_URL"]
    return create_engine(url)

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")

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

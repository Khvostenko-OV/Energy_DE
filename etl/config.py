import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

SOURCE_NAMES = ("bio", "gas", "hydro", "solar", "wind", "storage")

SYNTHETIC_ID_PREFIX = "syn_"


def get_engine():
    url = os.environ["DATABASE_URL"]
    return create_engine(url)

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

RAW_SCHEMA = "raw"


def get_engine():
    url = os.environ["DATABASE_URL"]
    return create_engine(url)

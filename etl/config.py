"""ETL configuration and the fixed database schema.

Single home for the environment-driven settings (connection URL, data paths,
schema names) and the fixed schema layout (column shapes, boundary mapping,
collision vocabulary) the raw/staging/core/service/marts layers all read
from (`config.py` absorbed `db_schema.py`).
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine

REPO_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(REPO_ROOT / ".env")

# --- Environment-driven settings ---------------------------------------------

# Database schema names, overridable via env (defaults shown).
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


# --- Fixed database schema ---------------------------------------------------

# State key shown for units the spatial join left outside every boundary; a
# state-null unit is a load-stage collision that still reaches core, so the
# mart pivots report it under this bucket instead of a NULL key (#9).
OUTSIDE_STATE = "outside"

# Generator sources consolidated into core.generators (storage is separate).
STAGING_GENERATOR_SOURCES = ("bio", "gas", "hydro", "solar", "wind")

RAW_COLUMNS = (
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "storage_capacity",
    "storage_type",
    "x_coordinates",
    "y_coordinates",
    "geo_accuracy",
    "geometry",
    "reference_id",
    "reference_date",
    "secondary_attributes",
)

RAW_COLUMN_MAPPING = {
    "gas": {"gas_production_capacity": "installed_capacity"},
}

BAD_QUALITY_PROPERTY = "bad_quality"

STORAGE_COLUMNS = ("storage_type", "storage_capacity")

STAGING_COLUMNS = (
    "unit_id",
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "x_coordinates",
    "y_coordinates",
    "geo_accuracy",
    "geometry",
    "reference_id",
    "reference_date",
    "secondary_attributes",
    "country_iso",
    "state",
    "region",
    "district",
    BAD_QUALITY_PROPERTY,
) + STORAGE_COLUMNS


DECOMPOSED_PROPERTIES = (
    "biomass_type",
    "fuel_type",
    "technology",
    "reference_source",
    "solar_type",
    "note",
    "location",
    "alignment",
    "inclination",
    "hydro_type",
    "inflow_type",
    "manufacturer",
    "rotor_diameter",
    "hub_height",
)


BOUNDARY_COLUMNS = ("country_iso", "name", "geometry")

BOUNDARY_COLUMN_MAPPING = {"iso": "country_iso"}

# Boundary-geometry simplification tolerance (degrees) used to materialize the
# per-row `service.boundaries.geojson` column once at pipeline load, so the viz
# app never re-simplifies or re-encodes geometry per rerun (issue #31).  Cuts
# the district-level payload ≈3.5× (≈14 MB → ≈4 MB) at a fidelity cost well
# under a pixel at the app's zoom range.
BOUNDARY_SIMPLIFY_TOLERANCE = 0.001

BOUNDARY_LEVEL_COLUMNS = {1: "state", 2: "region", 3: "district"}

CORE_GENERATORS_COLUMNS = (
    "unit_id",
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "geometry",
    "longitude",
    "latitude",
    "geo_accuracy",
    "reference_id",
    "reference_date",
    "secondary_attributes",
    "country_iso",
    "state",
    "region",
    "district",
    "collision",
)

COLLISION_PROPERTY = "collision"
CLOSE_TO_PROPERTY = "close_to"
CLOSE_LOCATION_REASON = "close location"
OUTSIDE_LOCATION_COLLISION_REASON = "outside location"
ONSHORE_IN_SEA_COLLISION_REASON = "onshore unit in the sea"
STORAGE_CAPACITY_COLLISION_REASON = "storage_capacity <= 0 or null"

# Sources whose units are onshore-only: an energy_source in this set whose
# state is a sea/EEZ area is an "onshore unit in the sea" collision.
ONSHORE_SOURCES = ("bio", "gas", "hydro", "solar")

SYNTHETIC_ID_PREFIX = "syn_"

# Sea/EEZ areas at boundary level 1 (the state grain) — assigning any of these
# as a state to an onshore-only source (bio/gas/hydro/solar) flags an
# onshore-in-sea collision.
SEA_REGIONS = ("North Sea", "Baltic Sea", "Kattegat")

COLLISION_CLOSE_DISTANCE_M = 10.0
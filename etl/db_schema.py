"""Fixed database schema: schema names, column shapes, and boundary mapping.

Single home for the tables the pipeline builds, so the raw/extract, stage/
transform, and verification layers all read the same layout.
"""

RAW_SCHEMA = "raw"
STAGING_SCHEMA = "stage"
CORE_SCHEMA = "core"
SERVICE_SCHEMA = "serv"

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
    "reference_id",
    "reference_date",
    "geometry",
    "secondary_attributes",
)

RAW_COLUMN_MAPPING = {
    "gas": {"gas_production_capacity": "installed_capacity"},
}

BOUNDARY_FILE_LEVELS = {
    "boundary": 0,
    "regions": 1,
    "districts": 2,
    "munis": 3,
}

BOUNDARY_COLUMNS = ("country_iso", "name", "geometry")

BOUNDARY_COLUMN_MAPPING = {"iso": "country_iso"}

BAD_QUALITY_PROPERTY = "bad_quality"

STORAGE_COLUMNS = ("storage_type", "storage_capacity")

STAGING_COLUMNS = (
    "unit_id",
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "geometry",
    "geo_accuracy",
    "x_coordinates",
    "y_coordinates",
    "reference_id",
    "reference_date",
    "country_iso",
    "region",
    "district",
    "municipality",
    BAD_QUALITY_PROPERTY,
) + STORAGE_COLUMNS

BOUNDARY_LEVEL_COLUMNS = {1: "region", 2: "district", 3: "municipality"}
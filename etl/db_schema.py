"""Fixed database schema: schema names, column shapes, and boundary mapping.

Single home for the tables the pipeline builds, so the raw/extract, stage/
transform, and verification layers all read the same layout.
"""

RAW_SCHEMA = "raw"
STAGING_SCHEMA = "stage"
CORE_SCHEMA = "core"
SERVICE_SCHEMA = "service"
MARTS_SCHEMA = "marts"

# Region key shown for units the spatial join left outside every boundary; a
# region-null unit is a load-stage collision that still reaches core, so the
# mart pivots report it under this bucket instead of a NULL key (#9).
OUTSIDE_REGION = "outside"

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
    "region",
    "district",
    "municipality",
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


BOUNDARY_FILE_LEVELS = {
    "boundary": 0,
    "regions": 1,
    "districts": 2,
    "munis": 3,
}

BOUNDARY_COLUMNS = ("country_iso", "name", "geometry")

BOUNDARY_COLUMN_MAPPING = {"iso": "country_iso"}

BOUNDARY_LEVEL_COLUMNS = {1: "region", 2: "district", 3: "municipality"}

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
    "region",
    "district",
    "municipality",
    "collision",
)

COLLISION_PROPERTY = "collision"
CLOSE_TO_PROPERTY = "close_to"
CLOSE_LOCATION_REASON = "close location"
REGION_NULL_COLLISION_REASON = "region is null"
ONSHORE_IN_SEA_COLLISION_REASON = "onshore unit in the sea"
STORAGE_CAPACITY_COLLISION_REASON = "storage_capacity <= 0 or null"

# Sources whose units are onshore-only: an energy_source in this set whose
# region is a sea/EEZ area is an "onshore unit in the sea" collision.
ONSHORE_SOURCES = ("bio", "gas", "hydro", "solar")

SYNTHETIC_ID_PREFIX = "syn_"

# Sea/EEZ areas at boundary level 1 — assigning any of these as a region to an
# onshore-only source (bio/gas/hydro/solar) flags an onshore-in-sea collision.
SEA_REGIONS = ("North Sea", "Baltic Sea", "Kattegat")

COLLISION_CLOSE_DISTANCE_M = 10.0
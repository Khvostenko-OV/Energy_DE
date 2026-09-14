"""Integration tests for the spec v2.2 transform contract (issue #11).

Run against the live dev PostGIS (`DATABASE_URL`), since the staging stage
reads from raw versioned tables and writes via PostGIS.  All sources are
transformed once per module by a shared fixture (the transform is idempotent
— it drops and re-creates the staging tables) and the tests assert against
that shared staging state.
"""

import os

import pytest
from sqlalchemy import create_engine, text

from etl.db_schema import DECOMPOSED_PROPERTIES
from etl.transform import transform_source

ENGINE = create_engine(os.environ["DATABASE_URL"])

SOURCE_NAMES = ("bio", "gas", "hydro", "solar", "wind", "storage")

WHITELIST = set(DECOMPOSED_PROPERTIES)

EXPECTED_PROPERTIES = {
    "bio": {"biomass_type", "fuel_type", "reference_source", "technology"},
    "gas": {"reference_source", "technology"},
    "hydro": {"hydro_type", "inflow_type", "reference_source"},
    "solar": {
        "alignment",
        "inclination",
        "location",
        "note",
        "reference_source",
        "solar_type",
    },
    "wind": {
        "hub_height",
        "location",
        "manufacturer",
        "note",
        "reference_source",
        "rotor_diameter",
    },
    "storage": {"reference_source", "technology"},
}

EXPECTED_JSON_KEYS = {
    "bio": {"biogas_unit", "chp_unit"},
    "gas": set(),
    "hydro": set(),
    "solar": {"area_id"},
    "wind": {"turbine_type"},
    "storage": set(),
}

EXPECTED_REGION_NULLS = {"hydro": 15, "solar": 5, "wind": 1, "storage": 30}
EXPECTED_BAD_QUALITY = {"bio": 0, "gas": 0, "hydro": 0, "solar": 12, "wind": 0, "storage": 0}


def run_transform(source: str):
    report = transform_source(source)
    assert report.passed, report.errors


def scalar(sql: str) -> int:
    with ENGINE.connect() as conn:
        return int(conn.execute(text(sql)).scalar())


@pytest.fixture(scope="module", autouse=True)
def _transformed_all():
    """Transform every source once per module."""
    for source in SOURCE_NAMES:
        run_transform(source)


def test_staging_tables_have_secondary_attributes_column():
    for source in SOURCE_NAMES:
        with ENGINE.connect() as conn:
            cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'stage' AND table_name = :name"
                    ),
                    {"name": source},
                )
            }
        assert "secondary_attributes" in cols, f"stage.{source} missing secondary_attributes"


@pytest.mark.parametrize("source", SOURCE_NAMES)
def test_staging_secondary_attributes_keep_only_nonwhitelist_keys(source):
    with ENGINE.connect() as conn:
        actual = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT DISTINCT jsonb_object_keys(secondary_attributes::jsonb) "
                    f"FROM stage.{source}"
                )
            )
        }
    assert actual == EXPECTED_JSON_KEYS[source]
    assert not (actual & WHITELIST), f"whitelisted keys leaked into stage.{source} json"


@pytest.mark.parametrize("source", SOURCE_NAMES)
def test_properties_tables_contain_only_whitelisted_keys(source):
    with ENGINE.connect() as conn:
        names = {
            row[0]
            for row in conn.execute(
                text(f"SELECT DISTINCT name FROM stage.{source}_properties")
            )
        }
    names.discard("bad_quality")
    assert names == EXPECTED_PROPERTIES[source], f"stage.{source}_properties: {names}"
    assert not (names - WHITELIST)


def test_region_null_units_no_longer_bad_quality():
    for source in SOURCE_NAMES:
        region_nulls = scalar(
            f"SELECT COUNT(*) FROM stage.{source} WHERE region IS NULL"
        )
        bad = scalar(f"SELECT COUNT(*) FROM stage.{source} WHERE bad_quality")
        bad_region = scalar(
            f"SELECT COUNT(*) FROM stage.{source} WHERE region IS NULL AND bad_quality"
        )
        assert region_nulls == EXPECTED_REGION_NULLS.get(source, 0)
        assert bad == EXPECTED_BAD_QUALITY[source]
        assert bad_region == 0
        assert (
            scalar(
                f"SELECT COUNT(*) FROM stage.{source}_units_properties up "
                f"JOIN stage.{source}_properties p ON p.param_id = up.param_id "
                f"WHERE p.name = 'bad_quality' AND p.value LIKE '%region%'"
            )
            == 0
        )
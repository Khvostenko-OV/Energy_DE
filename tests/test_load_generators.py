"""Integration tests for the core.generators load (issue #6).

Run against the live dev PostGIS (`DATABASE_URL`).  core tables are loaded
once per module via a shared fixture — read-only tests query that shared
state; the idempotency and incremental-update tests manage their own core
lifecycle because they need fresh loads.
"""

import os

import pytest
from sqlalchemy import create_engine, text

from etl.db_schema import CORE_SCHEMA, STAGING_SCHEMA, STAGING_GENERATOR_SOURCES
from etl.load import load_generators
from etl.transform import transform_source

ENGINE = create_engine(os.environ["DATABASE_URL"])

GENERATOR_SOURCES = STAGING_GENERATOR_SOURCES  # bio, gas, hydro, solar, wind


def _scalar(sql: str) -> int:
    with ENGINE.connect() as conn:
        return int(conn.execute(text(sql)).scalar())


def _ensure_staging():
    """Transform all generator sources to ensure staging tables are fresh."""
    for source in GENERATOR_SOURCES:
        report = transform_source(source)
        assert report.passed, report.errors


def _drop_core():
    """Drop core tables so each test/module starts clean."""
    with ENGINE.begin() as conn:
        for tbl in (
            "units_properties",
            "properties",
            "generators",
        ):
            conn.execute(text(f"DROP TABLE IF EXISTS {CORE_SCHEMA}.{tbl} CASCADE"))


@pytest.fixture(scope="module")
def _loaded_core():
    """Load all generator sources into core.generators once per module."""
    _drop_core()
    report = load_generators()
    assert report.passed, report.errors
    yield report
    _drop_core()


@pytest.fixture(scope="module", autouse=True)
def _staging_ready():
    """Transform all generator sources once per module."""
    _ensure_staging()


# ------------------------------------------------------------------ #
#  Table shape                                                         #
# ------------------------------------------------------------------ #


class TestTableShape:
    def test_generators_exists(self, _loaded_core):
        n = _scalar(
            "SELECT COUNT(*) FROM information_schema.tables "
            f"WHERE table_schema = '{CORE_SCHEMA}' AND table_name = 'generators'"
        )
        assert n == 1

    def test_generators_columns(self, _loaded_core):
        with ENGINE.connect() as conn:
            cols = {
                row[0]
                for row in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        f"WHERE table_schema = '{CORE_SCHEMA}' AND table_name = 'generators'"
                    )
                )
            }
        expected = {
            "unit_id",
            "collision",
            "secondary_attributes",
            "geometry",
            "longitude",
            "latitude",
            "energy_source",
            "installed_capacity",
            "commissioning_date",
            "decommissioning_date",
            "geo_accuracy",
            "reference_id",
            "reference_date",
            "country_iso",
            "region",
            "district",
            "municipality",
        }
        assert expected.issubset(cols), f"Missing columns: {expected - cols}"

    def test_generators_unit_id_is_serial(self, _loaded_core):
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT data_type FROM information_schema.columns "
                    f"WHERE table_schema = '{CORE_SCHEMA}' AND table_name = 'generators' "
                    "AND column_name = 'unit_id'"
                )
            ).fetchone()
        assert row is not None
        assert row[0] == "integer"

    def test_generators_collision_default_false(self, _loaded_core):
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT column_default FROM information_schema.columns "
                    f"WHERE table_schema = '{CORE_SCHEMA}' "
                    "AND table_name = 'generators' AND column_name = 'collision'"
                )
            ).fetchone()
        assert row is not None
        assert row[0] == "false"

    def test_generators_geometry_point_4326(self, _loaded_core):
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT srid, type FROM geometry_columns "
                    f"WHERE f_table_schema = '{CORE_SCHEMA}' AND f_table_name = 'generators'"
                )
            ).fetchone()
        assert row is not None
        assert row[0] == 4326
        assert row[1] == "POINT"

    def test_generators_has_longitude_latitude(self, _loaded_core):
        with ENGINE.connect() as conn:
            for col in ("longitude", "latitude"):
                row = conn.execute(
                    text(
                        "SELECT data_type FROM information_schema.columns "
                        f"WHERE table_schema = '{CORE_SCHEMA}' AND table_name = 'generators' "
                        f"AND column_name = '{col}'"
                    )
                ).fetchone()
                assert row is not None, f"Missing column {col}"


# ------------------------------------------------------------------ #
#  First load — row counts and uniqueness                              #
# ------------------------------------------------------------------ #


class TestFirstLoad:
    def test_first_load_row_count(self, _loaded_core):
        """Only bad_quality=false staging rows land in core."""
        good_staging = _scalar(
            "SELECT " + " + ".join(
                f"(SELECT COUNT(*) FROM {STAGING_SCHEMA}.{s} WHERE NOT bad_quality)"
                for s in GENERATOR_SOURCES
            )
        )
        core_count = _scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators")
        assert core_count == good_staging
        assert _loaded_core.rows_inserted == good_staging

    def test_no_duplicate_reference_id_pairs(self, _loaded_core):
        dups = _scalar(
            f"SELECT COUNT(*) FROM ("
            f"SELECT energy_source, reference_id FROM {CORE_SCHEMA}.generators "
            f"WHERE reference_id IS NOT NULL "
            f"GROUP BY energy_source, reference_id HAVING COUNT(*) > 1) d"
        )
        assert dups == 0

    def test_energy_sources_covered(self, _loaded_core):
        with ENGINE.connect() as conn:
            sources = sorted(
                row[0]
                for row in conn.execute(
                    text(
                        f"SELECT DISTINCT energy_source FROM {CORE_SCHEMA}.generators "
                        "ORDER BY 1"
                    )
                ).fetchall()
            )
        assert sources == sorted(GENERATOR_SOURCES)


# ------------------------------------------------------------------ #
#  Idempotency — running twice gives the same result                   #
# ------------------------------------------------------------------ #


class TestIdempotency:
    def test_load_twice_same_counts(self):
        _drop_core()
        r1 = load_generators()
        count_after_first = _scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators")
        assert count_after_first == r1.rows_inserted

        r2 = load_generators()
        count_after_second = _scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators")
        assert count_after_second == count_after_first
        assert r2.rows_inserted == 0
        assert r2.rows_skipped == count_after_first
        assert r1.idempotent and r2.idempotent


# ------------------------------------------------------------------ #
#  Incremental update — freshness gate                                  #
# ------------------------------------------------------------------ #


class TestIncrementalUpdate:
    def test_fresher_row_updates_in_place(self):
        load_generators()
        # Pick an existing unit with a reference_id
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT unit_id, energy_source, reference_id, reference_date "
                    f"FROM {CORE_SCHEMA}.generators "
                    f"WHERE reference_id IS NOT NULL LIMIT 1"
                )
            ).fetchone()
        assert row is not None
        core_unit_id, energy_source, reference_id, old_ref_date = row

        # Update staging to have a fresher reference_date for this unit
        import datetime

        new_ref_date = datetime.datetime(2999, 1, 1, 0, 0, 0)
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"UPDATE {STAGING_SCHEMA}.{energy_source} "
                    f"SET reference_date = :new_date "
                    f"WHERE reference_id = :ref_id"
                ),
                {"new_date": new_ref_date, "ref_id": reference_id},
            )

        load_generators()

        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT unit_id, reference_date "
                    f"FROM {CORE_SCHEMA}.generators "
                    f"WHERE reference_id = :ref_id"
                ),
                {"ref_id": reference_id},
            ).fetchone()
        assert row is not None
        assert row[0] == core_unit_id  # same unit_id
        assert row[1] >= new_ref_date  # reference_date refreshed

        # Restore staging
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"UPDATE {STAGING_SCHEMA}.{energy_source} "
                    f"SET reference_date = :old_date "
                    f"WHERE reference_id = :ref_id"
                ),
                {"old_date": old_ref_date, "ref_id": reference_id},
            )

    def test_staler_row_skipped(self):
        load_generators()
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT unit_id, energy_source, reference_id, reference_date "
                    f"FROM {CORE_SCHEMA}.generators "
                    f"WHERE reference_id IS NOT NULL LIMIT 1"
                )
            ).fetchone()
        assert row is not None
        core_unit_id, energy_source, reference_id, old_ref_date = row

        # Set staging to a much older reference_date
        import datetime

        stale_date = datetime.datetime(1900, 1, 1, 0, 0, 0)
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"UPDATE {STAGING_SCHEMA}.{energy_source} "
                    f"SET reference_date = :stale_date "
                    f"WHERE reference_id = :ref_id"
                ),
                {"stale_date": stale_date, "ref_id": reference_id},
            )

        load_generators()

        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT unit_id, reference_date "
                    f"FROM {CORE_SCHEMA}.generators "
                    f"WHERE reference_id = :ref_id"
                ),
                {"ref_id": reference_id},
            ).fetchone()
        assert row is not None
        assert row[0] == core_unit_id
        # Should NOT be updated to the stale date
        assert row[1] > stale_date

        # Restore staging
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"UPDATE {STAGING_SCHEMA}.{energy_source} "
                    f"SET reference_date = :old_date "
                    f"WHERE reference_id = :ref_id"
                ),
                {"old_date": old_ref_date, "ref_id": reference_id},
            )


# ------------------------------------------------------------------ #
#  Collision detection                                                  #
# ------------------------------------------------------------------ #


class TestCollisions:
    def test_region_null_flagged(self, _loaded_core):
        region_null_collisions = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators "
            f"WHERE region IS NULL AND collision"
        )
        staging_region_null = sum(
            _scalar(f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{s} WHERE NOT bad_quality AND region IS NULL")
            for s in GENERATOR_SOURCES
        )
        assert region_null_collisions == staging_region_null

    def test_onshore_in_sea_flagged(self, _loaded_core):
        # bio/gas/hydro/solar in sea regions should be flagged collision
        sea_regions = "'North Sea', 'Baltic Sea', 'Kattegat'"
        onshore_sea = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators "
            f"WHERE energy_source IN ('bio','gas','hydro','solar') "
            f"AND region IN ({sea_regions}) AND collision"
        )
        expected = sum(
            _scalar(
                f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{s} "
                f"WHERE NOT bad_quality AND region IN ({sea_regions})"
            )
            for s in ("bio", "gas", "hydro", "solar")
        )
        assert onshore_sea == expected

    def test_collision_property_links_exist(self, _loaded_core):
        collision_links = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators g "
            f"JOIN {CORE_SCHEMA}.units_properties gp ON gp.unit_id = g.unit_id "
            f"JOIN {CORE_SCHEMA}.properties p ON p.prop_id = gp.prop_id "
            f"WHERE g.collision AND p.name = 'collision'"
        )
        collision_rows = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators WHERE collision"
        )
        assert collision_links == collision_rows

    def test_close_to_links_for_close_pairs(self, _loaded_core):
        close_to_links = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators g "
            f"JOIN {CORE_SCHEMA}.units_properties gp ON gp.unit_id = g.unit_id "
            f"JOIN {CORE_SCHEMA}.properties p ON p.prop_id = gp.prop_id "
            f"WHERE p.name = 'close_to'"
        )
        # Every close_to link means a pair of geo_accuracy=1 units within 10m
        if close_to_links > 0:
            # Each close_to link should have a corresponding close_to on the other unit
            assert close_to_links % 2 == 0


# ------------------------------------------------------------------ #
#  Verification — counts reconcile                                      #
# ------------------------------------------------------------------ #


class TestVerification:
    def test_generator_count_reconciles(self, _loaded_core):
        good_staging = sum(
            _scalar(f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{s} WHERE NOT bad_quality")
            for s in GENERATOR_SOURCES
        )
        core_count = _scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators")
        assert core_count == good_staging

    def test_capacity_reconciles(self, _loaded_core):
        staging_cap = _scalar(
            "SELECT " + " + ".join(
                f"COALESCE((SELECT SUM(installed_capacity) FROM {STAGING_SCHEMA}.{s} WHERE NOT bad_quality), 0)"
                for s in GENERATOR_SOURCES
            )
        )
        core_cap = _scalar(
            f"SELECT SUM(installed_capacity) FROM {CORE_SCHEMA}.generators"
        )
        assert abs(core_cap - staging_cap) < 0.01
"""Integration tests for the core dimension machinery + annotation integrity (issue #8).

Issue #8's mechanics (the per-kind `*_properties` / `*_units_properties`
tables, the staging-whitelist transfer, and refresh on in-place updates) live
in the generator and storage load suites.  This module owns the *cross-table*
and *annotation-integrity* acceptance criteria the ticket demands: the link
counts must reconcile exactly to the staging whitelist decomposition, no link
may reference a missing unit, `bad_quality` must never reach core, every
`collision=true` row must carry a collision link (and no `collision=false`
row may carry one), and the verifier must fail loudly when any of that drifts.

Run against the live dev PostGIS (`DATABASE_URL`).  Both kinds are loaded once
per module via a shared fixture; negative drift tests mutate core state, call
the verifiers directly, and restore the state before returning.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from etl.db_schema import (
    BAD_QUALITY_PROPERTY,
    COLLISION_PROPERTY,
    CORE_SCHEMA,
    DECOMPOSED_PROPERTIES,
    STAGING_SCHEMA,
    STAGING_GENERATOR_SOURCES,
)
from etl.load import load_generators, load_storages
from etl.reports import LoadReport
from etl.transform import transform_sorces
from etl.verify import _verify_load_generators, _verify_load_storages

ENGINE = create_engine(os.environ["DATABASE_URL"])

GENERATOR_SOURCES = STAGING_GENERATOR_SOURCES

# (core_table, properties_table, units_properties_table) per unit-kind.
GENERATOR_KIND = ("generators", "generator_properties", "generator_units_properties")
STORAGE_KIND = ("storages", "storage_properties", "storage_units_properties")

WHITELIST_SQL = ", ".join(f"'{n}'" for n in DECOMPOSED_PROPERTIES)
ANNOTATION_SQL = f"'{COLLISION_PROPERTY}'"


def _scalar(sql: str):
    with ENGINE.connect() as conn:
        return conn.execute(text(sql)).scalar()


def _drop_core():
    """Drop core tables so the module starts and ends clean."""
    with ENGINE.begin() as conn:
        for kind in (GENERATOR_KIND, STORAGE_KIND):
            _, props, links = kind
            for tbl in (links, props):
                conn.execute(text(f"DROP TABLE IF EXISTS {CORE_SCHEMA}.{tbl} CASCADE"))
            conn.execute(
                text(f"DROP TABLE IF EXISTS {CORE_SCHEMA}.{kind[0]} CASCADE")
            )


@pytest.fixture(scope="module")
def _loaded_core():
    """Load both unit-kinds into core once per module."""
    _drop_core()
    gen_report = load_generators()
    sto_report = load_storages()
    assert gen_report.passed, gen_report.errors
    assert sto_report.passed, sto_report.errors
    yield {"generators": gen_report, "storages": sto_report}
    _drop_core()


@pytest.fixture(scope="module", autouse=True)
def _staging_ready(_staged_sources):
    """Staging is transformed once per session; nothing to do here."""


# ------------------------------------------------------------------ #
#  Whitelist-only dimension + exact reconciliation                     #
# ------------------------------------------------------------------ #


class TestWhitelistDimension:
    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_no_property_outside_whitelist_and_annotations(self, _loaded_core, kind):
        _, props, _ = kind
        stray = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.{props} "
            f"WHERE name NOT IN ({WHITELIST_SQL}, {ANNOTATION_SQL})"
        )
        assert stray == 0

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_bad_quality_absent_from_core(self, _loaded_core, kind):
        _, props, _ = kind
        n = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.{props} "
            f"WHERE name = '{BAD_QUALITY_PROPERTY}' LIMIT 1"
        )
        assert n == 0

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_no_orphaned_links(self, _loaded_core, kind):
        table, _, links = kind
        orphans = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.{links} up "
            f"LEFT JOIN {CORE_SCHEMA}.{table} u ON u.unit_id = up.unit_id "
            f"WHERE u.unit_id IS NULL"
        )
        assert orphans == 0


class TestReconciliation:
    def test_generator_properties_reconcile(self, _loaded_core):
        staged = set()
        core = set()
        with ENGINE.connect() as conn:
            for s in GENERATOR_SOURCES:
                rows = conn.execute(
                    text(
                        f"SELECT DISTINCT p.name, p.value "
                        f"FROM {STAGING_SCHEMA}.{s}_units_properties up "
                        f"JOIN {STAGING_SCHEMA}.{s}_properties p ON p.param_id = up.param_id "
                        f"JOIN {STAGING_SCHEMA}.{s} u ON u.unit_id = up.unit_id "
                        f"WHERE NOT u.bad_quality AND p.name <> '{BAD_QUALITY_PROPERTY}'"
                    )
                ).fetchall()
                staged.update((n, v) for n, v in rows)
            core = set(
                conn.execute(
                    text(
                        f"SELECT name, value FROM {CORE_SCHEMA}.generator_properties "
                        f"WHERE name IN ({WHITELIST_SQL})"
                    )
                ).fetchall()
            )
        assert staged == core

    def test_generator_links_reconcile(self, _loaded_core):
        staged_links = sum(
            int(_scalar(
                f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{s}_units_properties up "
                f"JOIN {STAGING_SCHEMA}.{s}_properties p ON p.param_id = up.param_id "
                f"JOIN {STAGING_SCHEMA}.{s} u ON u.unit_id = up.unit_id "
                f"WHERE NOT u.bad_quality AND p.name <> '{BAD_QUALITY_PROPERTY}'"
            ))
            for s in GENERATOR_SOURCES
        )
        core_links = int(
            _scalar(
                f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generator_units_properties up "
                f"JOIN {CORE_SCHEMA}.generator_properties p ON p.prop_id = up.prop_id "
                f"WHERE p.name IN ({WHITELIST_SQL})"
            )
        )
        assert core_links == staged_links

    def test_storage_properties_reconcile(self, _loaded_core):
        staged = set()
        with ENGINE.connect() as conn:
            rows = conn.execute(
                text(
                    f"SELECT DISTINCT p.name, p.value "
                    f"FROM {STAGING_SCHEMA}.storage_units_properties up "
                    f"JOIN {STAGING_SCHEMA}.storage_properties p ON p.param_id = up.param_id "
                    f"JOIN {STAGING_SCHEMA}.storage u ON u.unit_id = up.unit_id "
                    f"WHERE NOT u.bad_quality AND p.name <> '{BAD_QUALITY_PROPERTY}'"
                )
            ).fetchall()
            staged.update((n, v) for n, v in rows)
            core = set(
                conn.execute(
                    text(
                        f"SELECT name, value FROM {CORE_SCHEMA}.storage_properties "
                        f"WHERE name IN ({WHITELIST_SQL})"
                    )
                ).fetchall()
            )
        assert staged == core

    def test_storage_links_reconcile(self, _loaded_core):
        staged_links = int(
            _scalar(
                f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.storage_units_properties up "
                f"JOIN {STAGING_SCHEMA}.storage_properties p ON p.param_id = up.param_id "
                f"JOIN {STAGING_SCHEMA}.storage u ON u.unit_id = up.unit_id "
                f"WHERE NOT u.bad_quality AND p.name <> '{BAD_QUALITY_PROPERTY}'"
            )
        )
        core_links = int(
            _scalar(
                f"SELECT COUNT(*) FROM {CORE_SCHEMA}.storage_units_properties up "
                f"JOIN {CORE_SCHEMA}.storage_properties p ON p.prop_id = up.prop_id "
                f"WHERE p.name IN ({WHITELIST_SQL})"
            )
        )
        assert core_links == staged_links


# ------------------------------------------------------------------ #
#  Collision annotation integrity (per-unit, not just aggregate)       #
# ------------------------------------------------------------------ #


class TestCollisionAnnotationIntegrity:
    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_every_collision_row_has_a_collision_link(self, _loaded_core, kind):
        table, props, links = kind
        missing = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.{table} g "
            f"WHERE g.collision AND NOT EXISTS ("
            f"SELECT 1 FROM {CORE_SCHEMA}.{links} up "
            f"JOIN {CORE_SCHEMA}.{props} p ON p.prop_id = up.prop_id "
            f"WHERE up.unit_id = g.unit_id AND p.name = '{COLLISION_PROPERTY}')"
        )
        assert missing == 0

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_no_collision_link_on_clean_row(self, _loaded_core, kind):
        table, props, links = kind
        stale = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.{table} g "
            f"WHERE NOT g.collision AND EXISTS ("
            f"SELECT 1 FROM {CORE_SCHEMA}.{links} up "
            f"JOIN {CORE_SCHEMA}.{props} p ON p.prop_id = up.prop_id "
            f"WHERE up.unit_id = g.unit_id AND p.name = '{COLLISION_PROPERTY}')"
        )
        assert stale == 0

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_region_null_rows_carry_collision_link(self, _loaded_core, kind):
        table, props, links = kind
        outside = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.{table} g "
            f"WHERE g.region IS NULL AND NOT EXISTS ("
            f"SELECT 1 FROM {CORE_SCHEMA}.{links} up "
            f"JOIN {CORE_SCHEMA}.{props} p ON p.prop_id = up.prop_id "
            f"WHERE up.unit_id = g.unit_id AND p.name = '{COLLISION_PROPERTY}')"
        )
        assert outside == 0

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_region_null_rows_are_collision_flagged(self, _loaded_core, kind):
        table, _, _ = kind
        unflagged = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.{table} "
            f"WHERE region IS NULL AND NOT collision"
        )
        assert unflagged == 0

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_collision_link_value_carries_region_null_reason(self, _loaded_core, kind):
        """'correct' links: a region-null row's collision value names the reason."""
        table, props, links = kind
        stripped = _scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.{table} g "
            f"JOIN {CORE_SCHEMA}.{links} up ON up.unit_id = g.unit_id "
            f"JOIN {CORE_SCHEMA}.{props} p ON p.prop_id = up.prop_id "
            f"WHERE g.region IS NULL AND p.name = '{COLLISION_PROPERTY}' "
            f"AND p.value NOT LIKE '%region is null%'"
        )
        assert stripped == 0


# ------------------------------------------------------------------ #
#  Drift detection — the cross-table checks must fail loudly           #
# ------------------------------------------------------------------ #


class TestDriftDetection:
    """Negative tests: inject drift into core and assert the verifier flags it."""

    def _collided_unit(self, kind):
        """Return the (unit_id, prop_id) of any collision=true row's link."""
        table, props, links = kind
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT up.unit_id, up.prop_id "
                    f"FROM {CORE_SCHEMA}.{links} up "
                    f"JOIN {CORE_SCHEMA}.{props} p ON p.prop_id = up.prop_id "
                    f"JOIN {CORE_SCHEMA}.{table} g ON g.unit_id = up.unit_id "
                    f"WHERE g.collision AND p.name = '{COLLISION_PROPERTY}' "
                    f"LIMIT 1"
                )
            ).fetchone()
        assert row is not None, f"No collision link on a collided unit in core.{table}"
        return int(row[0]), int(row[1])

    def _collision_prop_id(self, kind):
        _, props, _ = kind
        row = _scalar(
            f"SELECT prop_id FROM {CORE_SCHEMA}.{props} "
            f"WHERE name = '{COLLISION_PROPERTY}' LIMIT 1"
        )
        assert row is not None, f"No collision property row in core.{props}"
        return int(row)

    def _clean_unit(self, kind):
        table = kind[0]
        row = _scalar(
            f"SELECT unit_id FROM {CORE_SCHEMA}.{table} "
            f"WHERE NOT collision LIMIT 1"
        )
        assert row is not None, f"No collision=false row in core.{table}"
        return int(row)

    def _verifier(self, kind):
        return _verify_load_generators if kind[0] == "generators" else _verify_load_storages

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_verifier_flags_missing_collision_link(self, _loaded_core, kind):
        table, _, links = kind
        uid, prop_id = self._collided_unit(kind)
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {CORE_SCHEMA}.{links} "
                    f"WHERE unit_id = :uid AND prop_id = :pid"
                ),
                {"uid": uid, "pid": prop_id},
            )
        try:
            errors = self._verifier(kind)(ENGINE, LoadReport())
            assert any(COLLISION_PROPERTY in e for e in errors), f"errors: {errors}"
        finally:
            with ENGINE.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO {CORE_SCHEMA}.{links} (unit_id, prop_id) "
                        f"VALUES (:uid, :pid) ON CONFLICT DO NOTHING"
                    ),
                    {"uid": uid, "pid": prop_id},
                )

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_verifier_flags_stale_collision_link(self, _loaded_core, kind):
        table, props, links = kind
        uid = self._clean_unit(kind)
        prop_id = self._collision_prop_id(kind)
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {CORE_SCHEMA}.{links} (unit_id, prop_id) "
                    f"VALUES (:uid, :pid) ON CONFLICT DO NOTHING"
                ),
                {"uid": uid, "pid": prop_id},
            )
        try:
            errors = self._verifier(kind)(ENGINE, LoadReport())
            assert any(COLLISION_PROPERTY in e for e in errors), f"errors: {errors}"
        finally:
            with ENGINE.begin() as conn:
                conn.execute(
                    text(
                        f"DELETE FROM {CORE_SCHEMA}.{links} "
                        f"WHERE unit_id = :uid AND prop_id = :pid"
                    ),
                    {"uid": uid, "pid": prop_id},
                )

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_verifier_flags_bad_quality_leak(self, _loaded_core, kind):
        table, props, links = kind
        uid = int(_scalar(f"SELECT unit_id FROM {CORE_SCHEMA}.{table} LIMIT 1"))
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {CORE_SCHEMA}.{props} (name, value) "
                    f"VALUES ('{BAD_QUALITY_PROPERTY}', 'drift') "
                    f"ON CONFLICT (name, value) DO NOTHING"
                )
            )
            pid = conn.execute(
                text(
                    f"SELECT prop_id FROM {CORE_SCHEMA}.{props} "
                    f"WHERE name = '{BAD_QUALITY_PROPERTY}' AND value = 'drift'"
                )
            ).scalar()
            conn.execute(
                text(
                    f"INSERT INTO {CORE_SCHEMA}.{links} (unit_id, prop_id) "
                    f"VALUES (:uid, :pid) ON CONFLICT DO NOTHING"
                ),
                {"uid": uid, "pid": pid},
            )
        try:
            errors = self._verifier(kind)(ENGINE, LoadReport())
            assert any(BAD_QUALITY_PROPERTY in e for e in errors), f"errors: {errors}"
        finally:
            with ENGINE.begin() as conn:
                conn.execute(
                    text(
                        f"DELETE FROM {CORE_SCHEMA}.{links} "
                        f"WHERE unit_id = :uid AND prop_id = "
                        f"(SELECT prop_id FROM {CORE_SCHEMA}.{props} "
                        f"WHERE name = '{BAD_QUALITY_PROPERTY}' AND value = 'drift')"
                    ),
                    {"uid": uid},
                )
                conn.execute(
                    text(
                        f"DELETE FROM {CORE_SCHEMA}.{props} "
                        f"WHERE name = '{BAD_QUALITY_PROPERTY}' AND value = 'drift'"
                    )
                )

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_verifier_flags_compensated_drift(self, _loaded_core, kind):
        """Aggregate-insensitive drift: move a collision link from a collided
        unit to a clean one keeps the flagged/linked counts equal, so only a
        per-unit check can see it."""
        table, props, links = kind
        collided_uid, prop_id = self._collided_unit(kind)
        clean_uid = self._clean_unit(kind)
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {CORE_SCHEMA}.{links} "
                    f"WHERE unit_id = :uid AND prop_id = :pid"
                ),
                {"uid": collided_uid, "pid": prop_id},
            )
            conn.execute(
                text(
                    f"INSERT INTO {CORE_SCHEMA}.{links} (unit_id, prop_id) "
                    f"VALUES (:uid, :pid) ON CONFLICT DO NOTHING"
                ),
                {"uid": clean_uid, "pid": prop_id},
            )
        try:
            errors = self._verifier(kind)(ENGINE, LoadReport())
            assert any(COLLISION_PROPERTY in e for e in errors), f"errors: {errors}"
        finally:
            with ENGINE.begin() as conn:
                conn.execute(
                    text(
                        f"DELETE FROM {CORE_SCHEMA}.{links} "
                        f"WHERE unit_id = :uid AND prop_id = :pid"
                    ),
                    {"uid": clean_uid, "pid": prop_id},
                )
                conn.execute(
                    text(
                        f"INSERT INTO {CORE_SCHEMA}.{links} (unit_id, prop_id) "
                        f"VALUES (:uid, :pid) ON CONFLICT DO NOTHING"
                    ),
                    {"uid": collided_uid, "pid": prop_id},
                )

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_verifier_flags_whitelist_link_drift(self, _loaded_core, kind):
        table, _, links = kind
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT up.unit_id, up.prop_id "
                    f"FROM {CORE_SCHEMA}.{links} up "
                    f"JOIN {CORE_SCHEMA}.{kind[1]} p ON p.prop_id = up.prop_id "
                    f"WHERE p.name IN ({WHITELIST_SQL}) "
                    f"LIMIT 1"
                )
            ).fetchone()
        assert row is not None
        uid, prop_id = int(row[0]), int(row[1])
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"DELETE FROM {CORE_SCHEMA}.{links} "
                    f"WHERE unit_id = :uid AND prop_id = :pid"
                ),
                {"uid": uid, "pid": prop_id},
            )
        try:
            errors = self._verifier(kind)(ENGINE, LoadReport())
            assert any("link" in e for e in errors), f"errors: {errors}"
        finally:
            with ENGINE.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO {CORE_SCHEMA}.{links} (unit_id, prop_id) "
                        f"VALUES (:uid, :pid) ON CONFLICT DO NOTHING"
                    ),
                    {"uid": uid, "pid": prop_id},
                )

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_orphaned_link_rejected_by_schema(self, _loaded_core, kind):
        """A link whose unit_id points nowhere must be rejected by the FK."""
        table, props, links = kind
        prop_id = self._collision_prop_id(kind)
        bogus = 9_999_999
        assert int(_scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.{table} WHERE unit_id = {bogus}")) == 0
        with ENGINE.begin() as conn:
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        f"INSERT INTO {CORE_SCHEMA}.{links} (unit_id, prop_id) "
                        f"VALUES (:uid, :pid)"
                    ),
                    {"uid": bogus, "pid": prop_id},
                )

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_verifier_flags_stripped_region_null_reason(self, _loaded_core, kind):
        """A region-null row whose collision value lost its reason is 'correct'
        drift the value-level check must catch."""
        table, props, links = kind
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT up.unit_id, p.prop_id, p.value "
                    f"FROM {CORE_SCHEMA}.{links} up "
                    f"JOIN {CORE_SCHEMA}.{props} p ON p.prop_id = up.prop_id "
                    f"JOIN {CORE_SCHEMA}.{table} g ON g.unit_id = up.unit_id "
                    f"WHERE g.region IS NULL AND p.name = '{COLLISION_PROPERTY}' "
                    f"LIMIT 1"
                )
            ).fetchone()
        assert row is not None, f"No region-null collided unit in core.{table}"
        prop_id, orig_value = int(row[1]), str(row[2])
        marker = f"drift-{uuid.uuid4().hex}"
        tampered = orig_value.replace("region is null", marker)
        with ENGINE.begin() as conn:
            conn.execute(
                text(f"UPDATE {CORE_SCHEMA}.{props} SET value = :v WHERE prop_id = :pid"),
                {"v": tampered, "pid": prop_id},
            )
        try:
            errors = self._verifier(kind)(ENGINE, LoadReport())
            assert any("region is null" in e for e in errors), f"errors: {errors}"
        finally:
            with ENGINE.begin() as conn:
                conn.execute(
                    text(f"UPDATE {CORE_SCHEMA}.{props} SET value = :v WHERE prop_id = :pid"),
                    {"v": orig_value, "pid": prop_id},
                )

    def test_verifier_flags_stripped_capacity_reason(self, _loaded_core):
        """Storages: a capacity-invalid row whose value lost that reason is drift."""
        table, props, links = STORAGE_KIND
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT up.unit_id, p.prop_id, p.value "
                    f"FROM {CORE_SCHEMA}.{links} up "
                    f"JOIN {CORE_SCHEMA}.{props} p ON p.prop_id = up.prop_id "
                    f"JOIN {CORE_SCHEMA}.{table} g ON g.unit_id = up.unit_id "
                    f"WHERE (g.storage_capacity IS NULL OR g.storage_capacity <= 0) "
                    f"AND p.name = '{COLLISION_PROPERTY}' "
                    f"LIMIT 1"
                )
            ).fetchone()
        assert row is not None, "No capacity-invalid collided storage"
        prop_id, orig_value = int(row[1]), str(row[2])
        marker = f"drift-{uuid.uuid4().hex}"
        tampered = orig_value.replace("storage_capacity <= 0 or null", marker)
        with ENGINE.begin() as conn:
            conn.execute(
                text(f"UPDATE {CORE_SCHEMA}.{props} SET value = :v WHERE prop_id = :pid"),
                {"v": tampered, "pid": prop_id},
            )
        try:
            errors = self._verifier(STORAGE_KIND)(ENGINE, LoadReport())
            assert any("storage_capacity" in e for e in errors), f"errors: {errors}"
        finally:
            with ENGINE.begin() as conn:
                conn.execute(
                    text(f"UPDATE {CORE_SCHEMA}.{props} SET value = :v WHERE prop_id = :pid"),
                    {"v": orig_value, "pid": prop_id},
                )

    @pytest.mark.parametrize(
        "kind", [GENERATOR_KIND, STORAGE_KIND], ids=["generators", "storages"]
    )
    def test_load_fails_loudly_on_drift(self, _loaded_core, kind):
        """A no-change load still runs the verifier and fails on injected drift."""
        table, props, links = kind
        uid = int(_scalar(f"SELECT unit_id FROM {CORE_SCHEMA}.{table} LIMIT 1"))
        with ENGINE.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO {CORE_SCHEMA}.{props} (name, value) "
                    f"VALUES ('{BAD_QUALITY_PROPERTY}', 'drift') "
                    f"ON CONFLICT (name, value) DO NOTHING"
                )
            )
            pid = conn.execute(
                text(
                    f"SELECT prop_id FROM {CORE_SCHEMA}.{props} "
                    f"WHERE name = '{BAD_QUALITY_PROPERTY}' AND value = 'drift'"
                )
            ).scalar()
            conn.execute(
                text(
                    f"INSERT INTO {CORE_SCHEMA}.{links} (unit_id, prop_id) "
                    f"VALUES (:uid, :pid) ON CONFLICT DO NOTHING"
                ),
                {"uid": uid, "pid": pid},
            )
        try:
            report = (
                load_generators() if kind[0] == "generators" else load_storages()
            )
            assert not report.passed
            assert any(BAD_QUALITY_PROPERTY in e for e in report.errors), report.errors
        finally:
            with ENGINE.begin() as conn:
                conn.execute(
                    text(
                        f"DELETE FROM {CORE_SCHEMA}.{links} "
                        f"WHERE prop_id = (SELECT prop_id FROM {CORE_SCHEMA}.{props} "
                        f"WHERE name = '{BAD_QUALITY_PROPERTY}' AND value = 'drift')"
                    )
                )
                conn.execute(
                    text(
                        f"DELETE FROM {CORE_SCHEMA}.{props} "
                        f"WHERE name = '{BAD_QUALITY_PROPERTY}' AND value = 'drift'"
                    )
                )


# ------------------------------------------------------------------ #
#  Refresh on in-place update (ADR 0001)                              #
# ------------------------------------------------------------------ #


class TestRefreshOnUpdate:
    def test_updated_unit_links_reflect_new_record(self, _loaded_core):
        """Relink on update: adding a staging whitelist pair links it in core,
        and removing it from staging unlinks it again (no orphan, ADR 0001)."""
        with ENGINE.connect() as conn:
            row = conn.execute(
                text(
                    f"SELECT g.unit_id, g.energy_source, g.reference_id "
                    f"FROM {CORE_SCHEMA}.generators g "
                    f"WHERE g.reference_id IS NOT NULL LIMIT 1"
                )
            ).fetchone()
        assert row is not None
        core_unit_id, energy_source, reference_id = int(row[0]), row[1], row[2]

        with ENGINE.connect() as conn:
            staging_unit = conn.execute(
                text(
                    f"SELECT unit_id FROM {STAGING_SCHEMA}.{energy_source} "
                    f"WHERE reference_id = :r"
                ),
                {"r": reference_id},
            ).scalar()
            core_pairs = set(
                conn.execute(
                    text(
                        f"SELECT p.name, p.value "
                        f"FROM {CORE_SCHEMA}.generator_units_properties up "
                        f"JOIN {CORE_SCHEMA}.generator_properties p ON p.prop_id = up.prop_id "
                        f"WHERE up.unit_id = :uid AND p.name IN ({WHITELIST_SQL})"
                    ),
                    {"uid": core_unit_id},
                ).fetchall()
            )
            # Pick a whitelist (name, value) already in staging that the unit
            # does not yet carry.
            candidates = [
                (int(r[0]), str(r[1]), str(r[2]))
                for r in conn.execute(
                    text(
                        f"SELECT p.param_id, p.name, p.value "
                        f"FROM {STAGING_SCHEMA}.{energy_source}_properties p "
                        f"WHERE p.name IN ({WHITELIST_SQL})"
                    )
                ).fetchall()
                if (str(r[1]), str(r[2])) not in core_pairs
            ]
        assert candidates, "No unused whitelist pair available in staging"
        param_id, add_name, add_value = candidates[0]

        def _bump(ref_date: str):
            with ENGINE.begin() as conn:
                conn.execute(
                    text(
                        f"UPDATE {STAGING_SCHEMA}.{energy_source} "
                        f"SET reference_date = :d WHERE reference_id = :r"
                    ),
                    {"d": ref_date, "r": reference_id},
                )

        try:
            # Add a whitelist link to the staging row, reload, expect the link.
            with ENGINE.begin() as conn:
                conn.execute(
                    text(
                        f"INSERT INTO {STAGING_SCHEMA}.{energy_source}_units_properties "
                        f"(unit_id, param_id) VALUES (:u, :p) ON CONFLICT DO NOTHING"
                    ),
                    {"u": staging_unit, "p": param_id},
                )
            _bump("2999-01-01 00:00:00")
            report = load_generators()
            assert report.passed, report.errors
            added = _scalar(
                f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generator_units_properties up "
                f"JOIN {CORE_SCHEMA}.generator_properties p ON p.prop_id = up.prop_id "
                f"WHERE up.unit_id = {core_unit_id} "
                f"AND p.name = '{add_name}' AND p.value = '{add_value}'"
            )
            assert added >= 1

            # Remove the staging link, reload, expect the core link gone.
            with ENGINE.begin() as conn:
                conn.execute(
                    text(
                        f"DELETE FROM {STAGING_SCHEMA}.{energy_source}_units_properties "
                        f"WHERE unit_id = :u AND param_id = :p"
                    ),
                    {"u": staging_unit, "p": param_id},
                )
            _bump("3000-01-01 00:00:00")
            report = load_generators()
            assert report.passed, report.errors
            remaining = _scalar(
                f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generator_units_properties up "
                f"JOIN {CORE_SCHEMA}.generator_properties p ON p.prop_id = up.prop_id "
                f"WHERE up.unit_id = {core_unit_id} "
                f"AND p.name = '{add_name}' AND p.value = '{add_value}'"
            )
            assert remaining == 0
        finally:
            report = transform_sorces(energy_source)
            assert report.passed, report.errors
            load_generators()
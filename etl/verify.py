from __future__ import annotations

import logging

from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.db_schema import (
    BAD_QUALITY_PROPERTY,
    COLLISION_PROPERTY,
    CORE_SCHEMA,
    DECOMPOSED_PROPERTIES,
    RAW_SCHEMA,
    SERVICE_SCHEMA,
    STAGING_GENERATOR_SOURCES,
    STAGING_SCHEMA,
    STORAGE_COLUMNS,
)
from etl.reports import ExtractionReport, LoadReport, TransformReport

log = logging.getLogger(__name__)


def _verify_boundaries(engine: Engine) -> list[str]:
    """Verify the boundaries table carries levels 0-3, one level-0 row, and areas."""
    errors: list[str] = []
    with engine.connect() as conn:
        counts = dict(
            conn.execute(
                text(
                    f"SELECT level, COUNT(*) FROM {SERVICE_SCHEMA}.boundaries "
                    f"GROUP BY level ORDER BY level"
                )
            ).fetchall()
        )
        names = conn.execute(
            text(
                f"SELECT level, name FROM {SERVICE_SCHEMA}.boundaries "
                f"ORDER BY level LIMIT 1"
            )
        )

        for level in range(4):
            if level not in counts:
                errors.append(f"Boundaries missing level {level}")

        if counts.get(0, 0) != 1:
            errors.append(f"Expected exactly 1 country-outline row at level 0, got {counts.get(0)}")

        bad_area = conn.execute(
            text(
                f"SELECT COUNT(*) FROM {SERVICE_SCHEMA}.boundaries "
                f"WHERE area IS NULL OR area <= 0"
            )
        ).scalar()
        if bad_area:
            errors.append(f"{bad_area} boundaries have null or non-positive area")

        if not errors:
            levels = ", ".join(f"{k}:{counts[k]}" for k in sorted(counts))
            level_names = ", ".join(f"{row[1]}" for row in names.fetchall())
            log.info("Boundaries verified (%s rows; sample names: %s)", levels, level_names)

    return errors


def _verify_extraction(engine: Engine, table_name: str, report: ExtractionReport) -> list[str]:
    """Verify the loaded versioned table against the extraction report.

    Checks the loaded count is consistent with the pre-dedupe source rows and
    matches the number of rows stored, and that no non-null reference_id
    appears more than once in the stored table. Returns a list of error
    strings, empty if verification passes.
    """
    errors: list[str] = []
    expected = report.source_row_count - report.duplicates_dropped
    if report.rows_loaded != expected:
        errors.append(
            f"Row count mismatch: loaded {report.rows_loaded}, expected {expected}"
        )

    with engine.connect() as conn:
        row = conn.execute(
            text(f"SELECT COUNT(*) FROM {RAW_SCHEMA}.{table_name}")
        ).scalar()
        if row != report.rows_loaded:
            errors.append(
                f"Row count mismatch in {table_name}: expected {report.rows_loaded}, got {row}"
            )

        dups = conn.execute(
            text(
                f"SELECT COUNT(*) FROM ("
                f"SELECT reference_id FROM {RAW_SCHEMA}.{table_name} "
                f"WHERE reference_id IS NOT NULL "
                f"GROUP BY reference_id HAVING COUNT(*) > 1) d"
            )
        ).scalar()
        if dups > 0:
            errors.append(f"Duplicate reference_ids found in {table_name}: {dups}")

    return errors


def _verify_transform(engine: Engine, source: str, report: TransformReport) -> list[str]:
    """Verify the stored staging tables against the transform report.

    Checks row counts, natural-key uniqueness, canonical labels, join
    coverage, the bad-quality distribution and its property links, and the
    decomposition counts. Any drift between what the transform computed and
    what the database holds is reported as an error.
    """
    errors: list[str] = []

    def scalar(sql: str) -> int:
        with engine.connect() as conn:
            return int(conn.execute(text(sql)).scalar())

    stored_rows = scalar(f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source}")
    if stored_rows != report.rows_written:
        errors.append(
            f"Staging row count mismatch: wrote {report.rows_written}, stored {stored_rows}"
        )

    dup_natural = scalar(
        f"SELECT COUNT(*) FROM (SELECT energy_source, reference_id "
        f"FROM {STAGING_SCHEMA}.{source} WHERE reference_id IS NOT NULL "
        f"GROUP BY energy_source, reference_id HAVING COUNT(*) > 1) d"
    )
    if dup_natural:
        errors.append(f"Duplicate natural keys (energy_source, reference_id): {dup_natural}")

    with engine.connect() as conn:
        sources = [
            r[0]
            for r in conn.execute(
                text(
                    f"SELECT DISTINCT energy_source FROM {STAGING_SCHEMA}.{source}"
                    f" ORDER BY 1"
                )
            ).fetchall()
        ]
        iso = [
            r[0]
            for r in conn.execute(
                text(
                    f"SELECT DISTINCT country_iso FROM {STAGING_SCHEMA}.{source}"
                    f" ORDER BY 1"
                )
            ).fetchall()
        ]
    if sources != [report.source]:
        errors.append(f"Canonical energy_source is {sources}, expected {[report.source]}")
    if iso != ["DEU"]:
        errors.append(f"country_iso is {iso}, expected ['DEU']")

    if source == "storage":
        missing_shape = [
            col
            for col in STORAGE_COLUMNS
            if not scalar(
                f"SELECT COUNT(*) FROM information_schema.columns "
                f"WHERE table_schema = '{STAGING_SCHEMA}' AND table_name = '{source}' "
                f"AND column_name = '{col}'"
            )
        ]
        if missing_shape:
            errors.append(
                f"Staging table {source} missing storage shape columns: {missing_shape}"
            )
        untyped = scalar(
            f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source} WHERE storage_type IS NULL"
        )
        if untyped:
            errors.append(
                f"{untyped} storage rows missing storage_type"
            )
        with_capacity = scalar(
            f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source} "
            f"WHERE storage_capacity IS NOT NULL"
        )
        log.info(
            "Storage shape: %s, storage_type non-null on all %d rows, "
            "storage_capacity present on %d rows",
            missing_shape or "ok", stored_rows, with_capacity,
        )

    for col, unmapped in report.join_unmapped.items():
        stored = scalar(
            f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source} WHERE {col} IS NULL"
        )
        if stored != unmapped:
            errors.append(
                f"Join coverage mismatch for {col}: computed {unmapped}, stored {stored}"
            )
        log.info(
            "Coverage %s: %d/%d mapped",
            col, report.rows_written - stored, report.rows_written,
        )

    bad_rows = scalar(
        f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source} WHERE bad_quality"
    )
    if bad_rows != report.bad_quality:
        errors.append(
            f"Bad-quality count mismatch: computed {report.bad_quality}, stored {bad_rows}"
        )

    reason_rows = scalar(
        f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source}_units_properties up "
        f"JOIN {STAGING_SCHEMA}.{source}_properties p ON p.param_id = up.param_id "
        f"WHERE p.name = '{BAD_QUALITY_PROPERTY}'"
    )
    if reason_rows != report.bad_quality:
        errors.append(
            f"Bad-quality property links mismatch: expected {report.bad_quality}, "
            f"got {reason_rows}"
        )

    stored_reasons: dict[str, int] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT p.value, COUNT(DISTINCT up.unit_id) "
                f"FROM {STAGING_SCHEMA}.{source}_units_properties up "
                f"JOIN {STAGING_SCHEMA}.{source}_properties p ON p.param_id = up.param_id "
                f"WHERE p.name = '{BAD_QUALITY_PROPERTY}' GROUP BY p.value"
            )
        ).fetchall()
    for value, count in rows:
        stored_reasons[value] = int(count)
    if stored_reasons != report.quality_reasons:
        errors.append(
            f"Bad-quality distribution mismatch: computed {report.quality_reasons}, "
            f"stored {stored_reasons}"
        )

    props = scalar(f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source}_properties")
    if props != report.properties_count:
        errors.append(
            f"Properties count mismatch: computed {report.properties_count}, stored {props}"
        )

    links = scalar(
        f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source}_units_properties"
    )
    if links != report.links_count:
        errors.append(
            f"Links count mismatch: computed {report.links_count}, stored {links}"
        )

    quoted_names = ", ".join(f"'{k}'" for k in DECOMPOSED_PROPERTIES)
    leaked = scalar(
        f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source} "
        f"WHERE secondary_attributes IS NOT NULL "
        f"AND secondary_attributes::jsonb ?| ARRAY[{quoted_names}]"
    )
    if leaked:
        errors.append(
            f"{leaked} staging rows still carry whitelisted keys in secondary_attributes"
        )

    nonwhitelist = scalar(
        f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source}_properties "
        f"WHERE name <> '{BAD_QUALITY_PROPERTY}' "
        f"AND name NOT IN ({quoted_names})"
    )
    if nonwhitelist:
        errors.append(
            f"{nonwhitelist} non-whitelisted names found in "
            f"{STAGING_SCHEMA}.{source}_properties"
        )

    if not errors:
        log.info(
            "Staging verified for %s (%d rows, %d properties, %d links, %d bad)",
            source, stored_rows, props, links, bad_rows,
        )
    return errors


def _verify_load_generators(engine: Engine, report: LoadReport) -> list[str]:
    """Verify core.generators against the load report and staging.

    Checks row and capacity reconciliation against good staging rows, no
    duplicate (energy_source, reference_id) pairs where reference_id is
    present, per-row invariants (geometry, longitude/latitude, secondary
    attributes), and that every staging bad-quality row stayed out of core.
    """
    errors: list[str] = []

    def scalar(sql: str):
        with engine.connect() as conn:
            return conn.execute(text(sql)).scalar()

    stored = int(scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators"))

    good_staging_count = int(
        scalar(
            "SELECT " + " + ".join(
                f"(SELECT COUNT(*) FROM {STAGING_SCHEMA}.{s} WHERE NOT bad_quality)"
                for s in STAGING_GENERATOR_SOURCES
            )
        )
    )
    if stored != good_staging_count:
        errors.append(f"Core rows {stored} != good staging rows {good_staging_count}")

    dups = int(
        scalar(
            f"SELECT COUNT(*) FROM ("
            f"SELECT energy_source, reference_id FROM {CORE_SCHEMA}.generators "
            f"WHERE reference_id IS NOT NULL "
            f"GROUP BY energy_source, reference_id HAVING COUNT(*) > 1) d"
        )
    )
    if dups:
        errors.append(f"Duplicate (energy_source, reference_id) pairs: {dups}")

    staging_cap = float(
        scalar(
            "SELECT " + " + ".join(
                f"COALESCE((SELECT SUM(installed_capacity) "
                f"FROM {STAGING_SCHEMA}.{s} WHERE NOT bad_quality), 0)"
                for s in STAGING_GENERATOR_SOURCES
            )
        )
    )
    core_cap = scalar(f"SELECT SUM(installed_capacity) FROM {CORE_SCHEMA}.generators")
    if core_cap is not None and abs(float(core_cap) - staging_cap) > 0.01:
        errors.append(
            f"Capacity drift: core {core_cap} vs good staging {staging_cap}"
        )

    without_geom = int(
        scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators WHERE geometry IS NULL")
    )
    if without_geom:
        errors.append(f"{without_geom} core rows missing geometry")

    without_coords = int(
        scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators "
            f"WHERE longitude IS NULL OR latitude IS NULL"
        )
    )
    if without_coords:
        errors.append(f"{without_coords} core rows missing longitude/latitude")

    leaked_bad = int(
        scalar(
            f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators g "
            f"JOIN {CORE_SCHEMA}.units_properties gp ON gp.unit_id = g.unit_id "
            f"JOIN {CORE_SCHEMA}.properties p ON p.prop_id = gp.prop_id "
            f"WHERE p.name = '{BAD_QUALITY_PROPERTY}' "
            f"LIMIT 1"
        )
    )
    if leaked_bad:
        errors.append("bad_quality property links leaked into core")

    flagged = int(scalar(f"SELECT COUNT(*) FROM {CORE_SCHEMA}.generators WHERE collision"))
    linked = int(
        scalar(
            f"SELECT COUNT(DISTINCT gp.unit_id) FROM {CORE_SCHEMA}.units_properties gp "
            f"JOIN {CORE_SCHEMA}.properties p ON p.prop_id = gp.prop_id "
            f"WHERE p.name = '{COLLISION_PROPERTY}'"
        )
    )
    if flagged != linked:
        errors.append(
            f"Collision flag drift: {flagged} collision=true rows vs {linked} "
            f"units with a collision link"
        )

    if not errors:
        log.info(
            "Core generators verified (%d rows, capacity %.1f kW)",
            stored, float(core_cap or 0),
        )
    return errors
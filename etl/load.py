from __future__ import annotations

import hashlib
import logging
import time
from collections import defaultdict

import pandas
from psycopg2.extras import execute_values
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.config import get_engine
from etl.db_schema import (
    CLOSE_TO_PROPERTY,
    COLLISION_CLOSE_DISTANCE_M,
    COLLISION_PROPERTY,
    CORE_SCHEMA,
    SEA_REGIONS,
    STAGING_GENERATOR_SOURCES,
    STAGING_SCHEMA,
    SYNTHETIC_ID_PREFIX,
)
from etl.db_utils import _create_core_generators, _ensure_schema, _table_exists
from etl.reports import LoadReport
from etl.verify import _verify_load_generators

log = logging.getLogger(__name__)

ONSHORE_SOURCES = ("bio", "gas", "hydro", "solar")


def load_generators() -> LoadReport:
    """Load staging rows into core.generators with collision annotation.

    Reads the good (bad_quality=false) rows from all five generator staging
    tables and consolidates them into core.generators with a serial surrogate
    key.  The first load creates the table and INSERTs every good row; later
    loads are incremental: a staging row whose record identity matches an
    existing core row is UPDATEd in place only when its reference_date is
    fresher, a staler row is skipped, and an unmatched row is INSERTed.  Core
    unit_ids are never regenerated.

    After the upsert, collision checks run against the core geometry and are
    then refreshed (flags reset, generator collision links cleared, re-written
    from scratch so they never orphan):
    - close-location pairs (geo_accuracy=1, <10m apart)
    - region-null units
    - onshore sources in the sea
    Collision rows are annotated with property links and remain in core.
    """
    report = LoadReport(target="generators")
    start = time.perf_counter()
    try:
        engine = get_engine()
        _ensure_schema(engine, CORE_SCHEMA)

        first_load = not _table_exists(engine, "generators")
        if first_load:
            log.info("Creating core.generators (first load)...")
            _create_core_generators(engine)

        log.info("Reading staging rows for all generator sources...")
        t = time.perf_counter()
        staging_df = _read_staging(engine)
        report.rows_read = len(staging_df)
        log.info(
            "%d good staging rows, time %.3fs", report.rows_read, time.perf_counter() - t
        )

        log.info("Building core identity lookup...")
        t = time.perf_counter()
        core_lookup, existing_count = _build_core_lookup(engine)
        log.info(
            "%d existing core rows, time %.3fs", existing_count, time.perf_counter() - t
        )

        log.info("Partitioning staging into insert/update/skip...")
        t = time.perf_counter()
        insert_df, update_df, skip_df = _partition_staging(engine, staging_df, core_lookup)
        _apply_upsert(engine, insert_df, update_df)
        report.rows_inserted = len(insert_df)
        report.rows_updated = len(update_df)
        report.rows_skipped = len(skip_df)
        log.info(
            "Inserted %d, updated %d, skipped %d, time %.3fs",
            report.rows_inserted,
            report.rows_updated,
            report.rows_skipped,
            time.perf_counter() - t,
        )

        log.info("Running collision checks...")
        t = time.perf_counter()
        collision_df = _detect_collisions(engine)
        report.collisions = len(collision_df)
        report.collision_links = _write_collision_links(engine, collision_df)
        log.info(
            "%d collision rows, %d links, time %.3fs",
            report.collisions,
            report.collision_links,
            time.perf_counter() - t,
        )

        log.info("Verifying load...")
        t = time.perf_counter()
        report.errors = _verify_load_generators(engine, report)
        log.info("Verification done, time %.3fs", time.perf_counter() - t)

        # Idempotency check: run upsert again, counts should not change.
        log.info("Idempotency check...")
        t = time.perf_counter()
        core_lookup2, _ = _build_core_lookup(engine)
        insert2, update2, skip2 = _partition_staging(engine, staging_df, core_lookup2)
        report.idempotent = len(insert2) == 0 and len(update2) == 0
        if not report.idempotent:
            report.errors.append(
                f"Idempotency violation: second pass would insert {len(insert2)}, "
                f"update {len(update2)}"
            )
        log.info("Idempotency check done, time %.3fs", time.perf_counter() - t)

    except Exception as e:
        report.errors.append(f"Load failed: {e}")
        log.exception("Load failed for generators")

    report.total_time = time.perf_counter() - start
    if report.errors:
        for err in report.errors:
            log.error("Load failed: %s", err)
    else:
        log.info(
            "Load passed for generators (%d rows inserted, %d updated)",
            report.rows_inserted,
            report.rows_updated,
        )
    log.info("Total time: %.3fs", report.total_time)
    return report




# ------------------------------------------------------------------ #
#  Staging read                                                        #
# ------------------------------------------------------------------ #


def _read_staging(engine: Engine) -> pandas.DataFrame:
    """Read all good (bad_quality=false) rows from all generator staging tables."""
    union_parts = []
    for source in STAGING_GENERATOR_SOURCES:
        union_parts.append(f'SELECT * FROM {STAGING_SCHEMA}.{source} WHERE NOT bad_quality')
    sql = " UNION ALL ".join(union_parts)
    return pandas.read_sql(text(sql), engine)


# ------------------------------------------------------------------ #
#  Core identity lookup                                                #
# ------------------------------------------------------------------ #


def _build_core_lookup(
    engine: Engine,
) -> tuple[dict[str, int], int]:
    """Build a lookup dict mapping record identity → core unit_id.

    For rows with reference_id: key = reference_id.
    For rows without reference_id (synthetic): key = synthetic hash
    derived from the same attributes as the staging hash.
    Returns (lookup, existing_count).
    """
    lookup: dict[str, int] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT unit_id, reference_id, energy_source, "
                f"longitude, latitude, installed_capacity, commissioning_date "
                f"FROM {CORE_SCHEMA}.generators"
            )
        ).fetchall()
    for row in rows:
        unit_id, reference_id, energy_source, lon, lat, cap, comm_date = row
        if reference_id is not None:
            lookup[reference_id] = unit_id
        else:
            h = _synthetic_hash(energy_source, lon, lat, cap, comm_date)
            lookup[h] = unit_id
    return lookup, len(rows)


def _synthetic_hash(source: str, x, y, capacity, commissioning) -> str:
    """Recompute the synthetic hash from stored core values (ADR 0001).

    The inputs mirror the staging derivation so the hash is stable.
    """
    payload = "|".join(str(v) for v in (source, x, y, capacity, commissioning))
    return SYNTHETIC_ID_PREFIX + hashlib.sha256(payload.encode()).hexdigest()[:16]


# ------------------------------------------------------------------ #
#  Partition staging into insert / update / skip                       #
# ------------------------------------------------------------------ #


def _staging_identities(df: pandas.DataFrame) -> pandas.Series:
    """Record identity for every staging row: reference_id or synthetic hash."""
    ref_id = df["reference_id"]
    has_ref = ref_id.notna() & (ref_id.astype(str) != "nan")
    identity = pandas.Series(index=df.index, dtype="object")
    if has_ref.any():
        identity[has_ref] = ref_id[has_ref].astype(str)

    synthetic = ~has_ref
    if synthetic.any():
        payload = (
            df["energy_source"].map(str)
            + "|" + df["x_coordinates"].map(str)
            + "|" + df["y_coordinates"].map(str)
            + "|" + df["installed_capacity"].map(str)
            + "|" + df["commissioning_date"].map(str)
        )
        identity[synthetic] = payload[synthetic].map(
            lambda p: SYNTHETIC_ID_PREFIX
            + hashlib.sha256(p.encode()).hexdigest()[:16]
        )
    return identity


def _partition_staging(
    engine: Engine, staging_df: pandas.DataFrame, core_lookup: dict[str, int]
) -> tuple[pandas.DataFrame, pandas.DataFrame, pandas.DataFrame]:
    """Split staging rows into insert, update, and skip buckets.

    A row goes to UPDATE when a core match exists and the staging reference_date
    is strictly fresher than the core row's.  A row goes to SKIP when the core
    match exists but the staging date is not fresher.  A row goes to INSERT
    when no core match exists.
    """
    if staging_df.empty:
        return staging_df.copy(), staging_df.copy(), staging_df.copy()

    staging_df = staging_df.copy()
    staging_df["_identity"] = _staging_identities(staging_df)

    core_ref_dates: dict[int, object] = {}
    with engine.connect() as conn:
        rows = conn.execute(
            text(f"SELECT unit_id, reference_date FROM {CORE_SCHEMA}.generators")
        ).fetchall()
    for unit_id, ref_date in rows:
        core_ref_dates[unit_id] = ref_date

    matched = staging_df["_identity"].map(core_lookup)
    is_insert = matched.isna()
    is_update = pandas.Series(False, index=staging_df.index)
    is_skip = pandas.Series(False, index=staging_df.index)

    non_insert_idx = staging_df.index[~is_insert].to_numpy()
    if len(non_insert_idx):
        matched_uids = matched[~is_insert].astype("int64")
        core_dates = pandas.to_datetime(
            matched_uids.map(core_ref_dates), errors="coerce"
        )
        staging_dates = pandas.to_datetime(
            staging_df.loc[non_insert_idx, "reference_date"], errors="coerce"
        )
        staging_missing = staging_dates.isna()
        update_mask = (~staging_missing) & (
            core_dates.isna() | (staging_dates > core_dates)
        )
        is_update[non_insert_idx] = update_mask.to_numpy()
        is_skip[non_insert_idx] = (~update_mask).to_numpy()

    update_df = staging_df[is_update].copy()
    if not update_df.empty:
        update_df["_core_unit_id"] = (
            update_df["_identity"].map(core_lookup).astype("int64")
        )
    insert_df = staging_df[is_insert].copy()
    skip_df = staging_df[is_skip].copy()
    return insert_df, update_df, skip_df


def _is_fresher(staging_date, core_date) -> bool:
    """True when the staging reference_date is strictly fresher than core's."""
    if staging_date is None or pandas.isna(staging_date):
        return False
    if core_date is None or pandas.isna(core_date):
        return True
    return staging_date > core_date


# ------------------------------------------------------------------ #
#  Upsert into core.generators                                         #
# ------------------------------------------------------------------ #


# Staging column → core.generators column mapping for the write path.
_INSERT_COLUMN_MAP = {
    "energy_source": "energy_source",
    "installed_capacity": "installed_capacity",
    "commissioning_date": "commissioning_date",
    "decommissioning_date": "decommissioning_date",
    "geometry": "geometry",
    "x_coordinates": "longitude",
    "y_coordinates": "latitude",
    "geo_accuracy": "geo_accuracy",
    "reference_id": "reference_id",
    "reference_date": "reference_date",
    "secondary_attributes": "secondary_attributes",
    "country_iso": "country_iso",
    "region": "region",
    "district": "district",
    "municipality": "municipality",
}


def _apply_upsert(
    engine: Engine, insert_df: pandas.DataFrame, update_df: pandas.DataFrame
) -> None:
    """Insert new rows and update existing rows in core.generators."""
    with engine.begin() as conn:
        _insert_core_rows(conn, insert_df)
        for _, row in update_df.iterrows():
            _update_core_row(conn, row)


def _sql_value(v):
    """Convert numpy/pandas missing values to SQL NULL."""
    if v is None:
        return None
    try:
        if pandas.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _core_row_values(row: pandas.Series) -> dict:
    """Map a staging row's values to core.generators columns."""
    return {
        core_col: _sql_value(row.get(stg_col))
        for stg_col, core_col in _INSERT_COLUMN_MAP.items()
    }


def _insert_core_rows(conn, df: pandas.DataFrame) -> None:
    """Bulk-insert staging rows into core.generators via execute_values."""
    if df.empty:
        return
    sub = df[list(_INSERT_COLUMN_MAP)].rename(columns=_INSERT_COLUMN_MAP)
    sub = sub.astype("object").where(pandas.notna(sub), None)
    cols = ", ".join(sub.columns)
    records = [tuple(r[k] for k in sub.columns) for r in sub.to_dict("records")]
    execute_values(
        conn.connection.cursor(),
        f"INSERT INTO {CORE_SCHEMA}.generators ({cols}) VALUES %s",
        records,
        page_size=1000,
    )


def _update_core_row(conn, row: pandas.Series) -> None:
    """Update an existing core.generators row by its core unit_id.

    The unit_id comes from the identity-matched core row; the matching itself
    was done in _partition_staging, so the update is precise.
    """
    vals = _core_row_values(row)
    set_clause = ", ".join(f"{k} = :{k}" for k in vals)
    vals["core_unit_id"] = int(row["_core_unit_id"])
    conn.execute(
        text(
            f"UPDATE {CORE_SCHEMA}.generators SET {set_clause} "
            f"WHERE unit_id = :core_unit_id"
        ),
        vals,
    )


# ------------------------------------------------------------------ #
#  Collision detection                                                  #
# ------------------------------------------------------------------ #


def _detect_collisions(engine: Engine) -> pandas.DataFrame:
    """Detect all collision conditions and return a DataFrame of unit_ids with collision reasons.

    Conditions:
    1. Close-location pairs: geo_accuracy=1, distance < 10m apart
    2. Region null: unit has no region after the spatial join
    3. Onshore-in-sea: bio/gas/hydro/solar in a sea/EEZ region
    """
    collision_units: dict[int, list[str]] = {}  # unit_id → list of reasons

    _detect_close_location(engine, collision_units)
    _detect_region_null(engine, collision_units)
    _detect_onshore_in_sea(engine, collision_units)

    if not collision_units:
        return pandas.DataFrame(columns=["unit_id", "reasons"])

    rows = [
        (uid, "\n".join(reasons)) for uid, reasons in collision_units.items()
    ]
    return pandas.DataFrame(rows, columns=["unit_id", "reasons"])


def _detect_close_location(
    engine: Engine, collision_units: dict[int, list[str]]
) -> None:
    """Find pairs of geo_accuracy=1 units within 10m of each other."""
    with engine.connect() as conn:
        pairs = conn.execute(
            text(
                f"SELECT a.unit_id, b.unit_id "
                f"FROM {CORE_SCHEMA}.generators a "
                f"JOIN {CORE_SCHEMA}.generators b "
                f"ON ST_DWithin(a.geometry::geography, b.geometry::geography, "
                f"{COLLISION_CLOSE_DISTANCE_M}) "
                f"WHERE a.unit_id < b.unit_id "
                f"AND a.geo_accuracy = 1 AND b.geo_accuracy = 1 "
                f"AND a.geometry IS NOT NULL AND b.geometry IS NOT NULL"
            )
        ).fetchall()

    for uid_a, uid_b in pairs:
        collision_units.setdefault(uid_a, []).append(
            f"close_to {uid_b}"
        )
        collision_units.setdefault(uid_b, []).append(
            f"close_to {uid_a}"
        )


def _detect_region_null(engine: Engine, collision_units: dict[int, list[str]]) -> None:
    """Flag units whose region is NULL (outside every boundary)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT unit_id FROM {CORE_SCHEMA}.generators "
                f"WHERE region IS NULL"
            )
        ).fetchall()
    for (uid,) in rows:
        collision_units.setdefault(uid, []).append("region is null")


def _detect_onshore_in_sea(
    engine: Engine, collision_units: dict[int, list[str]]
) -> None:
    """Flag onshore-only sources (bio/gas/hydro/solar) in sea/EEZ regions."""
    sources = ", ".join(f"'{s}'" for s in ONSHORE_SOURCES)
    regions = ", ".join(f"'{r}'" for r in SEA_REGIONS)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                f"SELECT unit_id FROM {CORE_SCHEMA}.generators "
                f"WHERE energy_source IN ({sources}) "
                f"AND region IN ({regions})"
            )
        ).fetchall()
    for (uid,) in rows:
        collision_units.setdefault(uid, []).append("onshore unit in the sea")


# ------------------------------------------------------------------ #
#  Collision property links                                             #
# ------------------------------------------------------------------ #


def _write_collision_links(
    engine: Engine, collision_df: pandas.DataFrame
) -> int:
    """Write collision and close_to property links for all flagged units.

    Resets the generator collision annotation first (flags to false, existing
    generator collision/close_to links cleared), then writes a 'collision'
    link carrying the joined reasons and one 'close_to' link per neighbouring
    unit involved in a close-location pair for every unit with a detection.
    A unit with no detection keeps collision=false and no annotation links.
    Returns the total number of property links written.
    """
    _reset_collision_annotation(engine)

    if collision_df.empty:
        return 0

    flagged = [int(u) for u in collision_df["unit_id"]]

    # desired property keys and which units want each one
    prop_keys: set[tuple[str, str]] = set()
    wanted: dict[tuple[str, str], list[int]] = defaultdict(list)
    for _, row in collision_df.iterrows():
        uid = int(row["unit_id"])
        reasons = row["reasons"].split("\n")
        collision_key = (COLLISION_PROPERTY, "\n".join(reasons))
        prop_keys.add(collision_key)
        wanted[collision_key].append(uid)
        for reason in reasons:
            if reason.startswith("close_to "):
                close_key = (CLOSE_TO_PROPERTY, reason[len("close_to "):])
                prop_keys.add(close_key)
                wanted[close_key].append(uid)

    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE {CORE_SCHEMA}.generators SET collision = true "
                f"WHERE unit_id = ANY(:ids)"
            ),
            {"ids": flagged},
        )
        prop_map = _ensure_properties(conn, prop_keys)
        pairs = [
            (uid, prop_map[key])
            for key, uids in wanted.items()
            for uid in uids
        ]
        execute_values(
            conn.connection.cursor(),
            f"INSERT INTO {CORE_SCHEMA}.units_properties "
            f"(unit_id, prop_id) VALUES %s ON CONFLICT DO NOTHING",
            pairs,
            page_size=2000,
        )

    return len(pairs)


def _ensure_properties(
    conn, keys: set[tuple[str, str]]
) -> dict[tuple[str, str], int]:
    """Ensure every (name, value) property key exists; return key → prop_id."""
    names = sorted({name for name, _ in keys})
    names_sql = ", ".join(f"'{n}'" for n in names)
    select_sql = (
        f"SELECT name, value, prop_id FROM {CORE_SCHEMA}.properties "
        f"WHERE name IN ({names_sql})"
    )
    prop_map = {
        (name, value): prop_id
        for name, value, prop_id in conn.execute(text(select_sql)).fetchall()
    }
    missing = [key for key in keys if key not in prop_map]
    if missing:
        execute_values(
            conn.connection.cursor(),
            f"INSERT INTO {CORE_SCHEMA}.properties (name, value) "
            f"VALUES %s ON CONFLICT DO NOTHING",
            missing,
            page_size=1000,
        )
        prop_map.update(
            {
                (name, value): prop_id
                for name, value, prop_id in conn.execute(
                    text(select_sql)
                ).fetchall()
            }
        )
    return prop_map


def _reset_collision_annotation(engine: Engine) -> None:
    """Clear collision flags and generator collision/close_to links.

    Deleting annotation links first avoids orphaning generator rows.  The
    underlying properties rows are kept — they may be re-used by other units
    or by the storage load in a later ticket.
    """
    with engine.begin() as conn:
        conn.execute(
            text(
                f"UPDATE {CORE_SCHEMA}.generators SET collision = false"
            )
        )
        conn.execute(
            text(
                f"DELETE FROM {CORE_SCHEMA}.units_properties gp "
                f"USING {CORE_SCHEMA}.properties p "
                f"WHERE gp.prop_id = p.prop_id "
                f"AND p.name IN (:collision, :close_to)"
            ),
            {"collision": COLLISION_PROPERTY, "close_to": CLOSE_TO_PROPERTY},
        )

from __future__ import annotations

import hashlib
import json
import logging
import time

import geopandas as gpd
import numpy
import pandas
from sqlalchemy import text
from sqlalchemy.engine import Engine

from etl.config import RAW_SCHEMA, SERVICE_SCHEMA, STAGING_SCHEMA, get_engine
from etl.utils import TransformReport, _ensure_schema, _latest_version_table

log = logging.getLogger(__name__)

COORD_TOLERANCE_DEG = 1e-9

QUALITY_CAPACITY = "installed_capacity <= 0 or null"
QUALITY_DATES = "decommissioning_date <= commissioning_date"
QUALITY_COORDS = "x/y coordinates disagree with geometry"
QUALITY_REGION = "region is null"

BAD_QUALITY_PROPERTY = "bad_quality"

BOUNDARY_LEVEL_COLUMNS = {1: "region", 2: "district", 3: "municipality"}

STAGING_COLUMNS = (
    "unit_id",
    "energy_source",
    "installed_capacity",
    "commissioning_date",
    "decommissioning_date",
    "geometry",
    "geo_accuracy",
    "reference_id",
    "reference_date",
    "country_iso",
    "region",
    "district",
    "municipality",
    "bad_quality",
    "secondary_attributes",
)


def transform_source(source: str) -> TransformReport:
    """Transform the latest raw version of one source into its staging tables.

    Reads raw.<source>_<YYYYMMDD>_<n> (the latest version), assigns each unit
    its staging identity (natural key from reference_id, synthetic hash where
    absent), enriches with region/district/municipality via a spatial join
    against the boundary reference layers, applies the quality gate, and
    decomposes secondary_attributes into normalized property tables. A bad
    quality row stays in staging but is never a candidate for core.
    """
    report = TransformReport(source=source)
    start = time.perf_counter()
    try:
        engine = get_engine()
        _ensure_schema(engine, STAGING_SCHEMA)

        raw_table = _latest_version_table(engine, source)
        if raw_table is None:
            raise ValueError(f"No raw version table found for source {source!r}")
        report.raw_table = raw_table

        log.info("Transforming %s from %s.%s", source, RAW_SCHEMA, raw_table)
        t = time.perf_counter()
        # Boundaries (and loaded_files) live in the service schema, not raw;
        # see the extract implementation and the review of extract v2.
        df = gpd.read_postgis(
            f'SELECT * FROM {RAW_SCHEMA}."{raw_table}"', engine, geom_col="geometry"
        )
        report.rows_read = len(df)
        log.info(
            "%d rows read, time %.3fs", report.rows_read, time.perf_counter() - t
        )

        boundaries = gpd.read_postgis(
            f"SELECT level, name, geometry FROM {SERVICE_SCHEMA}.boundaries",
            engine,
            geom_col="geometry",
        )

        df["unit_id"] = _unit_ids(df, source)
        df["energy_source"] = source
        df["country_iso"] = "DEU"
        df["geo_accuracy"] = df["geo_accuracy"].astype("Int64")

        log.info("Spatial join against boundary levels 1/2/3...")
        t = time.perf_counter()
        for level, col in BOUNDARY_LEVEL_COLUMNS.items():
            name_by_unit = _join_boundary_level(df, boundaries, level)
            df[col] = df["unit_id"].map(name_by_unit)
            report.join_unmapped[col] = int(df[col].isna().sum())
        log.info(
            "Join coverage %s, time %.3fs",
            report.join_unmapped, time.perf_counter() - t,
        )

        reasons = _quality_reasons(df)
        df["bad_quality"] = reasons.apply(bool)
        report.bad_quality = int(df["bad_quality"].sum())
        report.quality_reasons = _reason_histogram(reasons)
        log.info(
            "Quality gate: %d bad rows (%s)",
            report.bad_quality, report.quality_reasons,
        )

        report.attributes_empty = int(df["secondary_attributes"].isna().sum())
        props, links = _decompose_attributes(df, reasons)
        report.properties_count = len(props)
        report.links_count = len(links)
        log.info(
            "Decomposed into %d properties / %d links",
            report.properties_count, report.links_count,
        )

        log.info("Writing staging tables...")
        t = time.perf_counter()
        _create_staging_tables(engine, source)
        out = df[[c for c in STAGING_COLUMNS if c in df.columns]]
        out.to_postgis(
            source, engine, schema=STAGING_SCHEMA, if_exists="append", index=False
        )
        props.to_sql(
            f"{source}_properties", engine, schema=STAGING_SCHEMA,
            if_exists="append", index=False,
        )
        links.to_sql(
            f"{source}_units_properties", engine, schema=STAGING_SCHEMA,
            if_exists="append", index=False,
        )
        report.rows_written = len(df)
        log.info("Staging written, time %.3fs", time.perf_counter() - t)

        log.info("Verifying transform...")
        t = time.perf_counter()
        report.errors = _verify_transform(engine, source, report)
        log.info("Verification done, time %.3fs", time.perf_counter() - t)

    except Exception as e:
        report.errors.append(f"Transform failed: {e}")
        log.exception("Transform failed for %s", source)

    report.total_time = time.perf_counter() - start
    if report.errors:
        for err in report.errors:
            log.error("Transform failed for %s: %s", report.source, err)
    else:
        log.info("Transform passed for %s (%d rows)", report.source, report.rows_read)
    log.info("Total time: %.3fs", report.total_time)

    return report


def _unit_ids(df: pandas.DataFrame, source: str) -> pandas.Series:
    """Build the staging natural key per row.

    Rows carrying a reference_id get '<source>_<reference_id>'; rows without
    one (none in bio) get a synthetic hash identity derived from the row's own
    attributes and recognized by the 'syn_' prefix (ADR 0001, staging-only).
    """
    ids = (source + "_" + df["reference_id"].astype("string")).astype("string")
    missing = df["reference_id"].isna()
    if missing.any():
        rows = df.loc[missing]
        synthetic = rows.apply(
            lambda r: _synthetic_unit_id(
                source,
                r["x_coordinates"],
                r["y_coordinates"],
                r["installed_capacity"],
                r["commissioning_date"],
            ),
            axis=1,
        )
        ids.loc[missing] = synthetic.to_numpy()
    return ids


def _synthetic_unit_id(source: str, x, y, capacity, commissioning) -> str:
    """Stable synthetic identity from a unit's own attributes (ADR 0001)."""
    payload = "|".join(str(v) for v in (source, x, y, capacity, commissioning))
    return "syn_" + hashlib.sha256(payload.encode()).hexdigest()[:16]


def _join_boundary_level(
    df: pandas.DataFrame, boundaries: gpd.GeoDataFrame, level: int
) -> pandas.Series:
    """Map each unit_id to the name of the boundary polygon it intersects.

    Level determines the joined attribute (1=region, 2=district,
    3=municipality). A unit intersecting several polygons of the same level
    keeps the first match; an unmapped unit maps to NaN.
    """
    layer = boundaries[boundaries["level"] == level][["name", "geometry"]]
    joined = df[["unit_id", "geometry"]].sjoin(
        layer, how="left", predicate="intersects"
    ).drop_duplicates(subset="unit_id", keep="first")
    return joined.set_index("unit_id")["name"]


def _quality_reasons(df: pandas.DataFrame) -> pandas.Series:
    """Return one list of failed-check descriptions per row.

    Checks follow the spec order: capacity, dates, coordinates, region. A row
    nested in several polygons, nulls, and geometry/coordinate disagreements
    all resolve to boolean masks here; the order of the joined list is stable.
    """
    cap_bad = (
        df["installed_capacity"].isna() | (df["installed_capacity"] <= 0)
    ).to_numpy(dtype=bool)
    dates_bad = (
        df["decommissioning_date"].notna()
        & df["commissioning_date"].notna()
        & (df["decommissioning_date"] <= df["commissioning_date"])
    ).to_numpy(dtype=bool)
    coords_bad = _coordinates_mismatch(df)
    region_bad = df["region"].isna().to_numpy(dtype=bool)

    rows: list[list[str]] = []
    for cap, dates, coords, region in zip(
        cap_bad, dates_bad, coords_bad, region_bad
    ):
        failed = []
        if cap:
            failed.append(QUALITY_CAPACITY)
        if dates:
            failed.append(QUALITY_DATES)
        if coords:
            failed.append(QUALITY_COORDS)
        if region:
            failed.append(QUALITY_REGION)
        rows.append(failed)
    return pandas.Series(rows, index=df.index, dtype=object)


def _coordinates_mismatch(df: pandas.DataFrame) -> numpy.ndarray:
    """True where a row's x/y coordinates disagree with its geometry.

    Flags rows whose (x_coordinates, y_coordinates) point differs from the
    geometry beyond the coordinate tolerance. Null coordinates or geometry
    produce NaN differences, which compare as False, so this check only fires
    on a provable disagreement (a missing geometry is caught by the region
    gate instead). Bio is fully aligned in the source data.
    """
    x = pandas.to_numeric(df["x_coordinates"], errors="coerce").to_numpy(dtype=float)
    y = pandas.to_numeric(df["y_coordinates"], errors="coerce").to_numpy(dtype=float)
    gx = df.geometry.x.to_numpy(dtype=float)
    gy = df.geometry.y.to_numpy(dtype=float)
    return (numpy.abs(gx - x) > COORD_TOLERANCE_DEG) | (
        numpy.abs(gy - y) > COORD_TOLERANCE_DEG
    )


def _reason_histogram(reasons: pandas.Series) -> dict[str, int]:
    """Count units per newline-joined description list (the property value)."""
    hist: dict[str, int] = {}
    for failed in reasons:
        if not failed:
            continue
        value = "\n".join(failed)
        hist[value] = hist.get(value, 0) + 1
    return hist


def _decompose_attributes(
    df: pandas.DataFrame, reasons: pandas.Series
) -> tuple[pandas.DataFrame, pandas.DataFrame]:
    """Split secondary_attributes into normalized properties and link rows.

    Distinct (name, value) pairs become properties rows with a deterministic
    param_id in (name, value) order; each unit links to its pairs through
    units_properties. A bad quality row additionally links a 'bad_quality'
    property holding the newline-joined failed-check descriptions.
    """
    unique: set[tuple[str, str]] = set()
    per_unit: list[tuple[str, list[tuple[str, str]]]] = []
    for unit_id, attrs_json, failed in zip(
        df["unit_id"], df["secondary_attributes"], reasons
    ):
        pairs: list[tuple[str, str]] = []
        if attrs_json and str(attrs_json).strip() not in ("", "{}"):
            for name, value in json.loads(attrs_json).items():
                pairs.append((str(name), str(value)))
        if failed:
            pairs.append((BAD_QUALITY_PROPERTY, "\n".join(failed)))
        unique.update(pairs)
        per_unit.append((unit_id, pairs))

    ordered = sorted(unique)
    param_id = {pair: i + 1 for i, pair in enumerate(ordered)}
    props = pandas.DataFrame(
        [(i, name, value) for (name, value), i in param_id.items()],
        columns=["param_id", "name", "value"],
    )
    links = pandas.DataFrame(
        [(unit_id, param_id[pair]) for unit_id, pairs in per_unit for pair in pairs],
        columns=["unit_id", "param_id"],
    )
    return props, links


def _create_staging_tables(engine: Engine, source: str) -> None:
    """Drop and recreate the source's three staging tables with constraints."""
    with engine.begin() as conn:
        conn.execute(
            text(f"DROP TABLE IF EXISTS {STAGING_SCHEMA}.{source}_units_properties CASCADE")
        )
        conn.execute(text(f"DROP TABLE IF EXISTS {STAGING_SCHEMA}.{source}_properties CASCADE"))
        conn.execute(text(f"DROP TABLE IF EXISTS {STAGING_SCHEMA}.{source} CASCADE"))
        conn.execute(
            text(
                f"""
                CREATE TABLE {STAGING_SCHEMA}.{source} (
                    unit_id              TEXT PRIMARY KEY,
                    energy_source        TEXT NOT NULL,
                    installed_capacity   DOUBLE PRECISION,
                    commissioning_date   DATE,
                    decommissioning_date DATE,
                    geometry             geometry(Point, 4326),
                    geo_accuracy         BIGINT,
                    reference_id         TEXT,
                    reference_date       TIMESTAMP,
                    country_iso          TEXT,
                    region               TEXT,
                    district             TEXT,
                    municipality         TEXT,
                    bad_quality          BOOLEAN NOT NULL,
                    secondary_attributes TEXT
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE {STAGING_SCHEMA}.{source}_properties (
                    param_id BIGINT PRIMARY KEY,
                    name     TEXT NOT NULL,
                    value    TEXT NOT NULL,
                    UNIQUE (name, value)
                )
                """
            )
        )
        conn.execute(
            text(
                f"""
                CREATE TABLE {STAGING_SCHEMA}.{source}_units_properties (
                    unit_id  TEXT NOT NULL REFERENCES {STAGING_SCHEMA}.{source}(unit_id),
                    param_id BIGINT NOT NULL REFERENCES {STAGING_SCHEMA}.{source}_properties(param_id),
                    PRIMARY KEY (unit_id, param_id)
                )
                """
            )
        )
        conn.execute(
            text(
                f"CREATE INDEX {source}_geometry_gist "
                f"ON {STAGING_SCHEMA}.{source} USING gist (geometry)"
            )
        )


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

    empty_attrs = scalar(
        f"SELECT COUNT(*) FROM {STAGING_SCHEMA}.{source} WHERE secondary_attributes IS NULL"
    )
    if empty_attrs != report.attributes_empty:
        errors.append(
            f"Empty-attribute count mismatch: computed {report.attributes_empty}, "
            f"stored {empty_attrs}"
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

    if not errors:
        log.info(
            "Staging verified for %s (%d rows, %d properties, %d links, %d bad)",
            source, stored_rows, props, links, bad_rows,
        )
    return errors
from __future__ import annotations

import hashlib
import json
import logging
import time

import geopandas as gpd
import numpy
import pandas

from etl.config import (
    BAD_QUALITY_PROPERTY,
    RAW_SCHEMA,
    SERVICE_SCHEMA,
    STAGING_SCHEMA,
    get_engine,
)
from etl.db_utils import _create_staging_tables, _ensure_schema
from etl.reports import TransformReport
from etl.utils import _latest_table_version
from etl.verify import _verify_transform

log = logging.getLogger(__name__)

COORD_TOLERANCE_DEG = 1e-9

QUALITY_CAPACITY = "wrong installed_capacity"
QUALITY_DATES = "bad pair commissioning_date/decommissioning_date"
QUALITY_COORDS = "x/y coordinates disagree with geometry"
QUALITY_REGION = "region is null (outside the boundaries)"

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

        raw_table = _latest_table_version(engine, source)
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
            layer = boundaries[boundaries["level"] == level][["name", "geometry"]]
            joined = (
                df[["unit_id", "geometry"]]
                .sjoin(layer, how="left", predicate="intersects")
                .drop_duplicates(subset="unit_id", keep="first")
            )
            df[col] = df["unit_id"].map(joined.set_index("unit_id")["name"])
            report.join_unmapped[col] = int(df[col].isna().sum())
        log.info(
            "Join coverage %s, time %.3fs",
            report.join_unmapped, time.perf_counter() - t,
        )

        log.info("Running quality gate...")
        t = time.perf_counter()
        reasons = _quality_reasons(df)
        df["bad_quality"] = reasons.apply(bool)
        report.bad_quality = int(df["bad_quality"].sum())
        report.quality_reasons = _reason_histogram(reasons)
        log.info(
            "Quality gate: %d bad rows (%s), time %.3fs",
            report.bad_quality, report.quality_reasons, time.perf_counter() - t,
        )

        log.info("Decomposing attributes...")
        t = time.perf_counter()
        props, links = _decompose_attributes(df, reasons)
        report.properties_count = len(props)
        report.links_count = len(links)
        log.info(
            "Decomposed into %d properties / %d links, time %.3fs",
            report.properties_count, report.links_count, time.perf_counter() - t,
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
    unique: set[tuple[str, str]] = set()  # distinct (name, value) pairs across all units
    per_unit: list[tuple[str, list[tuple[str, str]]]] = []  # (unit_id, its pairs) per row
    for unit_id, attrs_json, failed in zip(
        df["unit_id"], df["secondary_attributes"], reasons
    ):
        pairs: list[tuple[str, str]] = []  # this unit's (name, value) pairs + bad_quality link
        if attrs_json and str(attrs_json).strip() not in ("", "{}"):
            for name, value in json.loads(attrs_json).items():
                pairs.append((str(name), str(value)))
        if failed:
            pairs.append((BAD_QUALITY_PROPERTY, "\n".join(failed)))
        unique.update(pairs)
        per_unit.append((unit_id, pairs))

    ordered = sorted(unique)  # sorted pairs -> deterministic param_id assignment
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
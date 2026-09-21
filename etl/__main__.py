import logging
from pathlib import Path

import click
import time

from etl.config import SOURCE_NAMES, boundaries_manifest, sources_data_dir
from etl.extract import extract_boundaries, extract_source
from etl.load import load_generators, load_storages
from etl.marts import build_marts
from etl.transform import transform_sources
from etl.utils import _source_from_filename


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
def cli(verbose: bool):
    """Energy DE ETL pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=level)


@cli.command()
@click.argument("target", required=False)
@click.option("-f", "--force", is_flag=True, help="Reload boundaries whose load signature is already logged.")
def boundaries(target: str | None, force: bool):
    """Load boundary reference files listed in a manifest into service.boundaries.

    TARGET is the manifest file path (defaults to the configured boundaries
    manifest). Each file name on its own line is resolved against the
    manifest's directory; the first file replaces the table and the rest
    append, the level being read from each file's data. Files already logged
    in loaded_files are skipped unless --force is given. Area is then computed
    in km² via PostGIS.
    """
    manifest = Path(target) if target else boundaries_manifest()
    click.echo(f"\nLoading boundaries from {manifest}")
    start = time.perf_counter()

    if not manifest.is_file():
        raise click.BadParameter("Manifest not found!")

    report = extract_boundaries(manifest, force=force)

    click.echo("\nBoundaries report:")
    click.echo(report.summary())
    click.echo(f"\nLoading boundaries complete. Total time: {(time.perf_counter() - start):.2f} seconds.")

    if not report.passed:
        raise SystemExit(1)


@cli.command()
@click.argument("target", required=False)
@click.option("-f", "--force", is_flag=True, help="Reload files whose load signature is already logged.")
def extract(target: str | None, force: bool):
    """Extract unit sources found in a folder into versioned raw tables.

    TARGET is the sources folder (defaults to the configured sources folder).
    Each *_V<YYYYMMDD>.gpkg matching one of the six unit sources is extracted
    in SOURCE_NAMES order; look-alikes such as Solar_Energy_Polygons and
    Cogeneration_Units, and any other files, are logged and skipped. Files
    already logged in loaded_files are skipped unless --force is given.
    """
    log = logging.getLogger(__name__)

    click.echo("\nStart Extraction...")
    start = time.perf_counter()

    data_dir = Path(target) if target else sources_data_dir()
    if not data_dir.is_dir():
        raise click.BadParameter(f"Sources folder not found: {data_dir}")

    log.info("Extracting energy sources from %s", data_dir.name)
    by_source: dict[str, Path] = {}
    skipped: list[str] = []
    for f in sorted(data_dir.glob("*.gpkg")):
        source = _source_from_filename(f.name)
        if not source:
            skipped.append(f.name)
            continue
        if source in by_source:
            log.warning(
                "Multiple files map to source %s: keeping %s, ignoring %s",
                source, by_source[source].name, f.name,
            )
            continue
        by_source[source] = f
    if skipped:
        log.info("Skipping unrecognised file(s): %s", ", ".join(skipped))

    filenames = [by_source[s] for s in SOURCE_NAMES if s in by_source]
    log.info("Extracting %d source file(s) from %s", len(filenames), data_dir)

    reports = [extract_source(f, force=force) for f in filenames]

    for r in reports:
        click.echo(f"\nExtraction report ({r.source}):")
        click.echo(r.summary())
    click.echo(f"\nExtraction complete. Total time: {(time.perf_counter() - start):.2f} seconds.")

    if any(not r.passed for r in reports):
        raise SystemExit(1)


@cli.command()
@click.argument(
    "sources",
    nargs=-1,
    type=click.Choice(SOURCE_NAMES + ("all",)),
)
def transform(sources):
    """Transform SOURCES into their staging tables (default: all).

    SOURCES is one or more of the six unit sources, or "all" to transform
    every source.  With no arguments, all sources are transformed.  Builds
    the staging row (unit_id — natural from reference_id or synthetic where
    absent, canonical energy_source, geo_accuracy, country_iso, geometry),
    spatially joins boundaries to assign state/region/district, runs
    the quality gate, and decomposes the whitelisted secondary attributes
    into normalized properties (the rest staying in the reduced
    secondary_attributes json). A state-null row is not bad quality
    (spec v2.2). Storage staging additionally carries its storage shape
    (storage_type, storage_capacity).
    """

    if sources:
        click.echo(f"\nStart transforming for {' '.join(sources)}.")
    else:
        click.echo("\nRunning transform stage for all sources...")
    start = time.perf_counter()

    report = transform_sources(*sources) if sources else transform_sources()

    click.echo(f"\nTransform report ({report.source}):")
    click.echo(report.summary())
    click.echo(f"\nTransform complete. Total time: {(time.perf_counter() - start):.2f} seconds.")

    if not report.passed:
        raise SystemExit(1)


@cli.command()
def load():
    """Load consolidated generators and storages into core.

    Reads the good staging rows from all six sources and upserts generators
    into core.generators and storages into core.storages, each with a serial
    surrogate key, collision checks, and property-link annotation.  The load
    is incremental and idempotent.
    """
    click.echo("\nRunning load stage for generators and storages...")
    start = time.perf_counter()

    reports = [
        load_generators(),
        load_storages(),
    ]

    for report in reports:
        click.echo(f"\nLoad report ({report.target}):")
        click.echo(report.summary())
    click.echo(f"\nLoad complete. Total time: {(time.perf_counter() - start):.2f} seconds.")

    if any(not report.passed for report in reports):
        raise SystemExit(1)


@cli.command()
def marts():
    """Create, refresh, and verify the marts materialized views.

    Ensures the marts schema and the three stored pivots exist
    (installation_counts, generation_capacity, storage_capacity), refreshes
    them from core at state grain (active units only, state-null units
    under the "outside" bucket), and verifies the stored pivots reconcile to
    the live core aggregates — failing loudly and exiting non-zero on drift.
    """
    click.echo("\nStart creating marts materialized views...")
    report = build_marts()

    click.echo(f"\nMarts report:")
    click.echo(report.summary())

    if not report.passed:
        raise SystemExit(1)


@cli.command()
@click.option("-f", "--force", is_flag=True, help="Reload files whose load signature is already logged.")
def run_all(force: bool):
    """Run all ETL stages"""
    click.echo("\n==== Run all ETL stages ====")
    start = time.perf_counter()
    ctx = click.get_current_context()

    ctx.invoke(boundaries, force=force)

    ctx.invoke(extract, force=force)

    ctx.invoke(transform)

    ctx.invoke(load)

    ctx.invoke(marts)

    click.echo(f"\n==== All stages complete. Total time: {(time.perf_counter() - start):.2f} seconds.")


if __name__ == "__main__":
    cli()
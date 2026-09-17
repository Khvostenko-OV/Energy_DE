import logging
from pathlib import Path

import click

from etl.config import SOURCE_NAMES
from etl.extract import extract_boundaries, extract_source
from etl.load import load_generators, load_storages
from etl.marts import build_marts
from etl.transform import transform_sources
from etl.utils import _read_manifest
from etl.viz_prep import generate_boundaries_geojson


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
def cli(verbose: bool):
    """Energy DE ETL pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=level)


@cli.command()
@click.argument("target")
@click.option("-f", "--force", is_flag=True, help="Reload files whose load signature is already logged.")
def extract(target: str, force: bool):
    """Extract unit sources listed in a manifest file.

    TARGET is the manifest file path. Each file name on its own line is
    resolved against the manifest's directory. Files already logged in
    loaded_files are skipped unless --force is given.
    """
    log = logging.getLogger(__name__)

    manifest = Path(target)
    if not manifest.is_file():
        raise click.BadParameter(f"Manifest not found: {target}")

    data_dir = manifest.parent
    filenames = _read_manifest(manifest)

    log.info("Extracting %d source file(s) from %s", len(filenames), manifest)
    reports = [
        extract_source(data_dir / f, force=force) for f in filenames
    ]

    for r in reports:
        click.echo(f"\nExtraction report ({r.source}):")
        click.echo(r.summary())

    if any(not r.passed for r in reports):
        raise SystemExit(1)


@cli.command()
@click.argument("target")
@click.option("-f", "--force", is_flag=True, help="Reload boundaries whose load signature is already logged.")
def boundaries(target: str, force: bool):
    """Load boundary reference files listed in a manifest into service.boundaries.

    TARGET is the manifest file path. Each file name on its own line is
    resolved against the manifest's directory; the first file replaces the
    table and the rest append. Files already logged in loaded_files are
    skipped unless --force is given. Area is then computed in km² via PostGIS.
    """
    manifest = Path(target)
    if not manifest.is_file():
        raise click.BadParameter(f"Manifest not found: {target}")

    report = extract_boundaries(manifest, force=force)

    click.echo("\nBoundaries report:")
    click.echo(report.summary())

    if not report.passed:
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
    spatially joins boundaries to assign region/district/municipality, runs
    the quality gate, and decomposes the whitelisted secondary attributes
    into normalized properties (the rest staying in the reduced
    secondary_attributes json). A region-null row is not bad quality
    (spec v2.2). Storage staging additionally carries its storage shape
    (storage_type, storage_capacity).
    """
    report = transform_sources(*sources) if sources else transform_sources()

    click.echo(f"\nTransform report ({report.source}):")
    click.echo(report.summary())

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
    reports = [
        load_generators(),
        load_storages(),
    ]

    for report in reports:
        click.echo(f"\nLoad report ({report.target}):")
        click.echo(report.summary())

    if any(not report.passed for report in reports):
        raise SystemExit(1)


@cli.command()
@click.argument("outdir", type=click.Path(file_okay=False, path_type=Path))
def boundaries_geojson(outdir: Path):
    """Write simplified boundary GeoJSON per level for the choropleth layer.

    Reads the boundary reference layer (service.boundaries, levels 1-3) via
    GeoPandas, simplifies each polygon (Douglas-Peucker) and rounds its
    coordinates to ~6 decimals, then writes one GeoJSON file per level
    (level_1.geojson, level_2.geojson, level_3.geojson) into OUTDIR.  The
    generated files are verified against the stored feature counts, failing
    loudly on drift.
    """
    report = generate_boundaries_geojson(outdir)

    click.echo("\nBoundary GeoJSON report:")
    click.echo(report.summary())

    if not report.passed:
        raise SystemExit(1)


@cli.command()
def marts():
    """Create, refresh, and verify the marts materialized views.

    Ensures the marts schema and the three stored pivots exist
    (installation_counts, generation_capacity, storage_capacity), refreshes
    them from core at region grain (active units only, region-null units
    under the "outside" bucket), and verifies the stored pivots reconcile to
    the live core aggregates — failing loudly and exiting non-zero on drift.
    """
    report = build_marts()

    click.echo(f"\nMarts report:")
    click.echo(report.summary())

    if not report.passed:
        raise SystemExit(1)


@cli.command()
@click.option("-f", "--force", is_flag=True, help="Reload files whose load signature is already logged.")
def run_all(force: bool):
    """Run all ETL stages, including the boundary GeoJSON for the choropleth.

    Besides the full extract → transform → load → marts chain, writes the
    per-level boundary GeoJSON assets consumed by the Dash choropleth layer
    (the `data/viz_assets` default the app resolves through
    ``VIZ_BOUNDARY_ASSET_DIR``).
    """
    ctx = click.get_current_context()

    click.echo("Loading boundaries...")
    ctx.invoke(boundaries, target="data/boundaries/boundaries.txt", force=force)

    click.echo("\nRunning extract stage...")
    ctx.invoke(extract, target="data/sources/sources.txt", force=force)

    click.echo("\nRunning transform stage for all sources...")
    ctx.invoke(transform)

    click.echo("\nRunning load stage for generators and storages...")
    ctx.invoke(load)

    click.echo("\nRunning marts stage...")
    ctx.invoke(marts)

    click.echo("\nWriting boundary GeoJSON for the choropleth layer...")
    ctx.invoke(boundaries_geojson, outdir="data/viz_assets")

    click.echo("\nAll stages complete.")


if __name__ == "__main__":
    cli()
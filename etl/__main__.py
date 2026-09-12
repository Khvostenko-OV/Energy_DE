import logging
from pathlib import Path

import click

from etl.extract import extract_boundaries, extract_source
from etl.transform import transform_source
from etl.utils import _read_manifest


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
def boundaries(target: str):
    """Load boundary reference files listed in a manifest into serv.boundaries.

    TARGET is the manifest file path. Each file name on its own line is
    resolved against the manifest's directory; the first file replaces the
    table and the rest append. Area is then computed in km² via PostGIS.
    """
    manifest = Path(target)
    if not manifest.is_file():
        raise click.BadParameter(f"Manifest not found: {target}")

    report = extract_boundaries(manifest)

    click.echo("\nBoundaries report:")
    click.echo(report.summary())

    if not report.passed:
        raise SystemExit(1)


@cli.command()
@click.argument("source", type=click.Choice(["bio"]))
def transform(source: str):
    """Transform the latest raw version of SOURCE into its staging tables.

    Builds the staging row (unit_id, canonical energy_source, geo_accuracy,
    country_iso, geometry), spatially joins boundaries
    to assign region/district/municipality, runs the quality gate, and
    decomposes secondary_attributes into normalized properties. Bio is the
    first source to have the full transform path; the remaining sources land
    with the all-sources transform ticket.
    """
    report = transform_source(source)

    click.echo(f"\nTransform report ({report.source}):")
    click.echo(report.summary())

    if not report.passed:
        raise SystemExit(1)


@cli.command()
def run_all():
    """Run all ETL stages."""
    ctx = click.get_current_context()

    click.echo("Loading boundaries...")
    ctx.invoke(boundaries, target="data/geo/boundaries.txt")

    click.echo("\nRunning extract stage...")
    ctx.invoke(extract, target="data/geo/sources.txt", force=False)

    click.echo("\nAll stages complete.")


if __name__ == "__main__":
    cli()
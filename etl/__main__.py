import logging
from pathlib import Path

import click

from etl.config import get_engine
from etl.extract import extract_boundaries, extract_source


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
    engine = get_engine()
    log = logging.getLogger(__name__)

    manifest = Path(target)
    if not manifest.is_file():
        raise click.BadParameter(f"Manifest not found: {target}")

    data_dir = manifest.parent
    filenames = [
        line.strip()
        for line in manifest.read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    log.info("Extracting %d source file(s) from %s", len(filenames), manifest)
    reports = [
        extract_source(data_dir / f, engine, force=force) for f in filenames
    ]

    for r in reports:
        click.echo(f"\nExtraction report ({r.source}):")
        click.echo(r.summary())

    if any(not r.passed for r in reports):
        raise SystemExit(1)


@cli.command()
@click.option(
    "--data-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default="data/geo",
    show_default=True,
    help="Directory containing germany_*.gpkg boundary files.",
)
def boundaries(data_dir: Path):
    """Load boundary reference files into raw.boundaries if it is empty.

    Files are mapped by name to levels 0-3 and area is computed in km² via
    PostGIS. The table is never versioned and not tracked in loaded_files.
    """
    engine = get_engine()
    report = extract_boundaries(data_dir, engine)

    click.echo("\nBoundaries report:")
    click.echo(report.summary())

    if not report.passed:
        raise SystemExit(1)


@cli.command()
def run_all():
    """Run all ETL stages."""
    ctx = click.get_current_context()

    click.echo("Loading boundaries...")
    ctx.invoke(boundaries, data_dir=Path("data/geo"))

    click.echo("\nRunning extract stage...")
    ctx.invoke(extract, target="data/geo/sources.txt", force=False)

    click.echo("\nAll stages complete.")


if __name__ == "__main__":
    cli()
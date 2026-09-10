import logging
from pathlib import Path

import click

from etl.config import get_engine
from etl.extract import extract_source


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
def cli(verbose: bool):
    """Energy DE ETL pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=level)


@cli.command()
@click.argument("target")
def extract(target: str):
    """Extract unit sources listed in a manifest file.

    TARGET is the manifest file path. Each file name on its own line is
    resolved against the manifest's directory.
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
    reports = [extract_source(data_dir / f, engine) for f in filenames]

    for r in reports:
        click.echo(f"\nExtraction report ({r.source}):")
        click.echo(r.summary())

    if any(not r.passed for r in reports):
        raise SystemExit(1)


@cli.command()
def run_all():
    """Run all ETL stages."""
    click.echo("Running extract stage...")
    ctx = click.get_current_context()
    ctx.invoke(extract, target="data/geo/sources.txt")
    click.echo("\nAll stages complete.")


if __name__ == "__main__":
    cli()
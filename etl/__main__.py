import logging

import click

from etl.config import get_engine
from etl.extract import DEFAULT_MANIFEST, extract_source, resolve_extract_targets


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
def cli(verbose: bool):
    """Energy DE ETL pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=level)


@cli.command()
@click.argument("target", default=str(DEFAULT_MANIFEST))
def extract(target: str):
    """Extract unit sources from a manifest of file names.

    TARGET is the manifest file path (file names resolve against the
    manifest's directory), or a single source key (bio, gas, hydro, solar,
    wind, storage).
    """
    engine = get_engine()
    log = logging.getLogger(__name__)

    try:
        paths = resolve_extract_targets(target)
    except Exception as e:
        raise click.BadParameter(str(e))

    log.info("Extracting %d source file(s)", len(paths))
    reports = [extract_source(p, engine) for p in paths]

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
    ctx.invoke(extract)
    click.echo("\nAll stages complete.")


if __name__ == "__main__":
    cli()
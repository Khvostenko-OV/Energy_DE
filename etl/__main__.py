import logging

import click

from etl.config import get_engine
from etl.extract import SOURCES, extract_source


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
def cli(verbose: bool):
    """Energy DE ETL pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="%(message)s", level=level)


@cli.command()
@click.argument("source", default="all")
def extract(source: str):
    """Extract unit sources into the raw schema. Defaults to all six sources."""
    engine = get_engine()

    if source == "all":
        sources = list(SOURCES)
    elif source in SOURCES:
        sources = [source]
    else:
        choices = ", ".join(list(SOURCES) + ["all"])
        raise click.BadParameter(f"Unknown source: {source}. Choose from {choices}.")

    reports = [extract_source(src, engine) for src in sources]

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

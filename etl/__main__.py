import logging

import click

from etl.config import get_engine


@click.group()
@click.option("-v", "--verbose", is_flag=True, help="Enable verbose logging.")
def cli(verbose: bool):
    """Energy DE ETL pipeline."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(format="%(message)s", level=level)


@cli.command()
@click.argument("source", default="bioenergy")
def extract(source: str):
    """Extract source data into the raw schema."""
    engine = get_engine()

    if source == "bioenergy":
        from etl.extract import extract_bioenergy

        report = extract_bioenergy(engine)
    else:
        raise click.BadParameter(f"Unknown source: {source}")

    click.echo(f"\nExtraction report ({report.source}):")
    click.echo(report.summary())

    if not report.passed:
        raise SystemExit(1)


@cli.command()
def run_all():
    """Run all ETL stages."""
    click.echo("Running extract stage...")
    ctx = click.get_current_context()
    ctx.invoke(extract, source="bioenergy")
    click.echo("\nAll stages complete.")


if __name__ == "__main__":
    cli()

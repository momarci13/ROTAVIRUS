"""CLI: ``python -m scraper.process panel --resolution county|district``."""

from __future__ import annotations

import typer

from scraper.cli_common import build_runtime, command_string
from scraper.core.errors import ConfigError
from scraper.core.manifest import write_manifest
from scraper.processing.panel import build_county_weekly_epi, build_district_panel

app = typer.Typer(add_completion=False, help="Assemble the published panels")


@app.callback()
def _main() -> None:
    """Panel assembly."""


@app.command()
def panel(
    resolution: str = typer.Option("county", "--resolution", help="county | district"),
    ci_fraction: float = typer.Option(0.5, "--ci-fraction", help="+/- fraction for the modelled CI"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    rt = build_runtime(log_level=log_level, with_http=False)

    county = build_county_weekly_epi(rt.config)
    extra: dict = {"county_weekly_rows": len(county)}

    if resolution == "district":
        try:
            dp = build_district_panel(rt.config, county_weekly=county, ci_fraction=ci_fraction)
        except ConfigError as exc:
            typer.echo(f"ERROR: {exc}")
            raise typer.Exit(code=2) from exc
        extra["district_panel_rows"] = len(dp)
        extra["district_panel_cols"] = list(dp.columns)
        typer.echo(f"district_panel: {len(dp)} rows, {len(dp.columns)} cols -> data/processed/district_panel.parquet")
    else:
        typer.echo(f"county_weekly_epi: {len(county)} rows -> data/processed/county_weekly_epi.parquet")

    write_manifest(command=command_string(), config_hashes=rt.config.config_hashes(), extra=extra)


if __name__ == "__main__":
    app()

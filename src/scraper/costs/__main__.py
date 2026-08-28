"""CLI: ``python -m scraper.costs resolve``."""

from __future__ import annotations

import typer

from scraper.cli_common import build_runtime, command_string
from scraper.core.errors import MissingParameterError
from scraper.core.manifest import write_manifest
from scraper.costs.parameters import resolve_all, write_resolved

app = typer.Typer(add_completion=False, help="Cost parameter resolution / cost model")


@app.callback()
def _main() -> None:
    """Cost commands."""


@app.command()
def resolve(
    year: int = typer.Option(None, "--year", help="price/effective year to resolve for"),
    strict: bool = typer.Option(True, "--strict/--no-strict", help="halt on missing required params"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    """Resolve every cost parameter; write cost_parameters_resolved.parquet.

    With --strict (default), a required parameter that is still null halts with an
    informative error naming the parameter and its source URL — never a default.
    """
    rt = build_runtime(log_level=log_level, with_http=False)
    try:
        resolved = resolve_all(rt.config, year=year, strict=strict)
    except MissingParameterError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from exc

    df = write_resolved(resolved)
    n_missing = int(df["missing"].sum())
    typer.echo(
        f"resolved {len(df)} parameters "
        f"({int((~df['missing']).sum())} filled, {n_missing} still missing) "
        f"-> data/processed/cost_parameters_resolved.parquet"
    )
    for row in df[df["missing"]].itertuples():
        url = str(row.source_url) if row.source_url else "see cost_parameters.yaml"
        typer.echo(f"  MISSING {row.parameter_id} - {url}")

    write_manifest(
        command=command_string(),
        config_hashes=rt.config.config_hashes(),
        extra={"parameters": len(df), "missing": n_missing},
    )


if __name__ == "__main__":
    app()

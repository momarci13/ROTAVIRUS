"""CLI: ``python -m scraper.geography build``."""

from __future__ import annotations

import typer

from scraper.cli_common import build_runtime, command_string
from scraper.core.errors import ManualExportMissingError
from scraper.core.manifest import write_manifest
from scraper.geography.build_registry import build_registry, write_registry

app = typer.Typer(add_completion=False, help="Canonical geography registry")


@app.callback()
def _main() -> None:
    """Geography registry commands."""


@app.command()
def build(
    log_level: str = typer.Option("INFO", "--log-level"),
    strict: bool = typer.Option(False, "--strict", help="Exit non-zero on any consistency error"),
) -> None:
    """Build data/processed/geo_districts.parquet + geo_settlements.parquet."""
    rt = build_runtime(log_level=log_level, with_http=False)
    try:
        result = build_registry(rt.config)
    except ManualExportMissingError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=2) from exc

    write_registry(result)
    write_manifest(
        command=command_string(),
        config_hashes=rt.config.config_hashes(),
        extra={
            "districts": len(result.districts),
            "settlements": len(result.settlements),
            "boundary_changes": len(result.boundary_changes),
            "consistency_errors": result.consistency_errors,
        },
    )
    typer.echo(
        f"districts={len(result.districts)} settlements={len(result.settlements)} "
        f"boundary_changes={len(result.boundary_changes)} "
        f"consistency_errors={len(result.consistency_errors)}"
    )
    if result.consistency_errors:
        for e in result.consistency_errors:
            typer.echo(f"  ! {e}")
        if strict:
            raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

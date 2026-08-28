"""CLI: ``python -m scraper.validate --all`` (validation only, no downloads)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import typer

from scraper import INTERMEDIATE_DIR, PROCESSED_DIR
from scraper.cli_common import build_runtime, command_string
from scraper.core.logging_setup import get_logger
from scraper.core.manifest import write_manifest
from scraper.validation.checks import ValidationContext, run_all
from scraper.validation.drift import check_and_update

app = typer.Typer(add_completion=False, help="Run the validation rule-set")
log = get_logger("scraper.validate")


def _load_geo() -> tuple[pd.DataFrame | None, pd.DataFrame | None]:
    d = PROCESSED_DIR / "geo_districts.parquet"
    districts = pd.read_parquet(d) if d.exists() else None
    counties = None
    if districts is not None and "county_id" in districts.columns:
        counties = districts[["county_id", "county_name"]].drop_duplicates() if "county_name" in districts.columns else districts[["county_id"]].drop_duplicates()
    return districts, counties


@app.callback(invoke_without_command=True)
def main(
    all_tables: bool = typer.Option(False, "--all", help="validate every intermediate + processed table"),
    table: str = typer.Option(None, "--table", help="path to a single parquet/csv to validate"),
    resolution: str = typer.Option("county", "--resolution", help="county | district | panel"),
    strict: bool = typer.Option(False, "--strict", help="exit non-zero on any error-severity finding"),
    compare_modelled: bool = typer.Option(False, "--compare-modelled", help="compare modelled vs FOIA district values"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    rt = build_runtime(log_level=log_level, with_http=False)
    districts, counties = _load_geo()

    targets: list[Path] = []
    if table:
        targets = [Path(table)]
    elif all_tables:
        targets = sorted(INTERMEDIATE_DIR.glob("**/*.parquet")) + sorted(PROCESSED_DIR.glob("*.parquet"))
    else:
        raise typer.BadParameter("pass --all or --table <path> (or --compare-modelled)")

    if compare_modelled:
        _compare_modelled()
        return

    total_errors = 0
    for path in targets:
        if not path.exists():
            log.warning("validate.missing", path=str(path))
            continue
        df = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)
        source = path.stem.split("__")[0]
        drift = check_and_update(source, df)
        if drift.changed:
            log.warning("validate.schema_drift", source=source, added=drift.added, removed=drift.removed)
        ctx = ValidationContext(
            df=df,
            config=rt.config,
            geo_districts=districts,
            geo_counties=counties,
            resolution=resolution,
        )
        findings = run_all(ctx, raise_on_error=False, label=path.name)
        errs = [f for f in findings if f.severity == "error"]
        total_errors += len(errs)
        typer.echo(
            f"[{path.name}] rows={len(df)} "
            f"errors={len(errs)} warnings={sum(1 for f in findings if f.severity == 'warning')} "
            f"flags={sum(1 for f in findings if f.severity == 'flag')}"
        )
        for f in errs:
            typer.echo(f"   ERROR {f.rule}: {f.message}")

    write_manifest(command=command_string(), config_hashes=rt.config.config_hashes(),
                   extra={"validated": [str(p) for p in targets], "total_errors": total_errors})
    typer.echo(f"total errors: {total_errors}  (VALIDATION_REPORT.md written)")
    if strict and total_errors:
        raise typer.Exit(code=1)


def _compare_modelled() -> None:
    """§17: when FOIA district data arrives, compare it against the modelled panel
    and write MODEL_VALIDATION_REPORT.md."""
    panel_p = PROCESSED_DIR / "district_panel.parquet"
    foia_p = INTERMEDIATE_DIR / "nngyk_foia" / "nngyk_foia.parquet"
    if not (panel_p.exists() and foia_p.exists()):
        typer.echo("need both district_panel.parquet and the nngyk_foia intermediate; nothing to compare")
        return
    panel = pd.read_parquet(panel_p)
    foia = pd.read_parquet(foia_p)
    key = ["district_id"] + (["period_start"] if "period_start" in foia.columns and "period_start" in panel.columns else ["year"])
    merged = panel.merge(foia, on=key, suffixes=("_modelled", "_observed"), how="inner")
    if merged.empty:
        typer.echo("no overlapping keys between modelled panel and FOIA data")
        return
    mcol = "rotavirus_cases_district_modelled"
    ocol = "value" if "value" in merged.columns else "value_observed"
    merged["abs_err"] = (merged[mcol] - merged[ocol]).abs()
    merged["in_ci"] = (merged[ocol] >= merged.get("rotavirus_cases_district_modelled_lo", merged[mcol])) & (
        merged[ocol] <= merged.get("rotavirus_cases_district_modelled_hi", merged[mcol])
    )
    mae = merged["abs_err"].mean()
    coverage = merged["in_ci"].mean()
    Path("MODEL_VALIDATION_REPORT.md").write_text(
        "# Modellvalidációs jelentés\n\n"
        f"- Összevetett rekordok: {len(merged)}\n"
        f"- Átlagos abszolút hiba (MAE): {mae:.2f}\n"
        f"- 95% CI-lefedettség: {coverage:.1%}\n",
        encoding="utf-8",
    )
    typer.echo(json.dumps({"n": len(merged), "mae": round(mae, 2), "ci_coverage": round(coverage, 3)}))


if __name__ == "__main__":
    app()

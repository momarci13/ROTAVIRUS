"""CLI: ``python -m scraper.allocate --scenario 5 --budget 2500000000``
       ``python -m scraper.allocate --all-scenarios --compare``
"""

from __future__ import annotations

import json

import pandas as pd
import typer

from scraper import PROCESSED_DIR
from scraper.allocation.equity import equity_summary, spearman_between_scenarios
from scraper.allocation.scenarios import run_all_scenarios, run_scenario
from scraper.cli_common import build_runtime, command_string
from scraper.core.logging_setup import get_logger
from scraper.core.manifest import write_manifest

app = typer.Typer(add_completion=False, help="Need-based allocation scenarios")
log = get_logger("scraper.allocate")

ALLOC_OUT = PROCESSED_DIR / "allocation_scenarios.parquet"


def _load_panel() -> pd.DataFrame:
    p = PROCESSED_DIR / "district_panel.parquet"
    if not p.exists():
        raise typer.BadParameter(
            "data/processed/district_panel.parquet missing — run "
            "`python -m scraper.process panel --resolution district` first."
        )
    return pd.read_parquet(p)


@app.command()
def main(
    scenario: int = typer.Option(None, "--scenario", help="scenario id 0-7"),
    all_scenarios: bool = typer.Option(False, "--all-scenarios"),
    compare: bool = typer.Option(False, "--compare", help="write equity + Spearman comparison"),
    budget: float = typer.Option(None, "--budget", help="total budget B (HUF)"),
    year: int = typer.Option(None, "--year"),
    log_level: str = typer.Option("INFO", "--log-level"),
) -> None:
    if scenario is None and not all_scenarios:
        raise typer.BadParameter("pass --scenario <id> or --all-scenarios")

    rt = build_runtime(log_level=log_level, with_http=False)
    panel = _load_panel()

    if all_scenarios:
        alloc = run_all_scenarios(rt.config, panel, budget=budget, year=year)
    else:
        alloc = run_scenario(rt.config, panel, scenario, budget=budget, year=year)

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    alloc.to_parquet(ALLOC_OUT, index=False)
    alloc.to_csv(ALLOC_OUT.with_suffix(".csv"), index=False)
    typer.echo(f"{len(alloc)} allocation rows -> {ALLOC_OUT}")
    for sid, grp in alloc.groupby("scenario_id"):
        typer.echo(f"  scenario {sid}: Σaid = {grp['aid_amount_huf'].sum():,.0f} HUF over {len(grp)} districts")

    comparison = None
    if compare:
        comparison = {}
        for sid, grp in alloc.groupby("scenario_id"):
            comparison[str(sid)] = equity_summary(grp, group_col="county_id" if "county_id" in grp.columns else None)
        sp = spearman_between_scenarios(alloc)
        comparison["spearman_between_scenarios"] = json.loads(sp.to_json())
        (PROCESSED_DIR / "allocation_comparison.json").write_text(
            json.dumps(comparison, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        typer.echo(f"comparison -> {PROCESSED_DIR / 'allocation_comparison.json'}")

    write_manifest(
        command=command_string(),
        config_hashes=rt.config.config_hashes(),
        extra={"rows": len(alloc), "scenarios": sorted(map(int, alloc["scenario_id"].unique()))},
    )


if __name__ == "__main__":
    app()

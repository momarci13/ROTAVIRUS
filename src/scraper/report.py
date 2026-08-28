"""CLI: ``python -m scraper.report dictionary`` / ``... availability``.

Generates data/metadata/data_dictionary.md and docs/availability_matrix.md from
config/variables.yaml + config/sources.yaml, enriched with coverage / missing
share scanned from data/processed/*.parquet when present.
"""

from __future__ import annotations

import pandas as pd
import typer

from scraper import METADATA_DIR, PROCESSED_DIR, REPO_ROOT
from scraper.cli_common import build_runtime
from scraper.core.logging_setup import get_logger

app = typer.Typer(add_completion=False, help="Generate documentation artifacts")
log = get_logger("scraper.report")

DICTIONARY_OUT = METADATA_DIR / "data_dictionary.md"
AVAILABILITY_OUT = REPO_ROOT / "docs" / "availability_matrix.md"


@app.callback()
def _main() -> None:
    """Reporting."""


def _scan_processed() -> dict[str, dict]:
    """column -> {present_in: [...], missing_share: float, years: (min,max)}"""
    info: dict[str, dict] = {}
    for path in sorted(PROCESSED_DIR.glob("*.parquet")):
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        for col in df.columns:
            rec = info.setdefault(col, {"present_in": [], "missing_share": None, "years": None})
            rec["present_in"].append(path.name)
            miss = float(df[col].isna().mean())
            rec["missing_share"] = miss if rec["missing_share"] is None else min(rec["missing_share"], miss)
            if "year" in df.columns and col != "year":
                yrs = pd.to_numeric(df["year"], errors="coerce").dropna()
                if len(yrs):
                    rec["years"] = (int(yrs.min()), int(yrs.max()))
    return info


@app.command()
def dictionary(log_level: str = typer.Option("INFO", "--log-level")) -> None:
    rt = build_runtime(log_level=log_level, with_http=False)
    scanned = _scan_processed()
    src = rt.config.sources

    lines = [
        "# Adatszótár",
        "",
        "Generált fájl (`python -m scraper.report dictionary`). Minden oszlop a "
        "`config/variables.yaml` alapján; a lefedettség a `data/processed/*.parquet` "
        "állományokból származik, ha elérhetők.",
        "",
        "| Oszlop | Blokk | Tier | geo_level | Időbeli felbontás | Egység | evidence_class | Forrás | Forrás-URL | Lefedett évek | Hiányzó arány | Megjelenik |",
        "| --- | --- | ---: | --- | --- | --- | --- | --- | --- | --- | ---: | --- |",
    ]
    for name, spec in rt.config.variables.variables.items():
        sc = scanned.get(name, {})
        try:
            source = src.get(spec.source_id)
            url = source.base_url or ""
        except Exception:
            url = ""
        years = sc.get("years")
        years_s = f"{years[0]}–{years[1]}" if years else "—"
        miss = sc.get("missing_share")
        miss_s = f"{miss:.0%}" if miss is not None else "—"
        present = ", ".join(sc.get("present_in", [])) or "—"
        lines.append(
            f"| {name} | {spec.block} | {spec.tier} | {spec.geo_level} | {spec.time_resolution} "
            f"| {spec.unit} | {spec.evidence_class} | {spec.source_id} | {url} | {years_s} | {miss_s} | {present} |"
        )

    DICTIONARY_OUT.parent.mkdir(parents=True, exist_ok=True)
    DICTIONARY_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo(f"{len(rt.config.variables.variables)} oszlop -> {DICTIONARY_OUT}")


@app.command()
def availability(log_level: str = typer.Option("INFO", "--log-level")) -> None:
    rt = build_runtime(log_level=log_level, with_http=False)
    by_source: dict[str, dict] = {}
    for spec in rt.config.variables.variables.values():
        b = by_source.setdefault(
            spec.source_id, {"blocks": set(), "geo_levels": set(), "n_vars": 0, "resolutions": set()}
        )
        b["blocks"].add(spec.block)
        b["geo_levels"].add(spec.geo_level)
        b["resolutions"].add(spec.time_resolution)
        b["n_vars"] += 1

    registry = METADATA_DIR / "source_registry.json"
    fetched_by_collector: dict[str, int] = {}
    if registry.exists():
        import json

        for rec in json.loads(registry.read_text(encoding="utf-8")).get("records", []):
            fetched_by_collector[rec["collector"]] = fetched_by_collector.get(rec["collector"], 0) + 1

    lines = [
        "# Adatelérhetőségi mátrix",
        "",
        "Generált fájl (`python -m scraper.report availability`).",
        "",
        "| Forrás | Változók | Blokkok | geo_level | Időbeli felbontás | Robots | Render | Letöltött fájlok |",
        "| --- | ---: | --- | --- | --- | --- | --- | ---: |",
    ]
    for sid, b in sorted(by_source.items()):
        try:
            s = rt.config.sources.get(sid)
            robots = "tiltott" if not s.robots_allowed else "ok"
            render = "igen" if s.render_required else "nem"
        except Exception:
            robots = render = "—"
        lines.append(
            f"| {sid} | {b['n_vars']} | {', '.join(sorted(b['blocks']))} "
            f"| {', '.join(sorted(b['geo_levels']))} | {', '.join(sorted(b['resolutions']))} "
            f"| {robots} | {render} | {fetched_by_collector.get(sid, 0)} |"
        )

    AVAILABILITY_OUT.parent.mkdir(parents=True, exist_ok=True)
    AVAILABILITY_OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    typer.echo(f"{len(by_source)} forrás -> {AVAILABILITY_OUT}")


if __name__ == "__main__":
    app()

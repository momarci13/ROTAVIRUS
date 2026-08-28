"""Primary CLI: ``python -m scraper.run`` / console script ``rotavirus-scraper``."""

from __future__ import annotations

import importlib
from datetime import date, datetime
from pathlib import Path

import typer

from scraper.cli_common import build_runtime, command_string
from scraper.core.logging_setup import get_logger
from scraper.core.manifest import write_manifest

app = typer.Typer(add_completion=False, help="Hungarian rotavirus data-collection pipeline")
log = get_logger("scraper.run")

# name -> "module:Class". Lazy so an optional dependency missing in one collector
# never blocks the others.
COLLECTORS: dict[str, str] = {
    "nngyk": "scraper.collectors.nngyk:NNGYKCollector",
    "ksh": "scraper.collectors.ksh:KSHCollector",
    "neak": "scraper.collectors.neak:NEAKCollector",
    "nfsz": "scraper.collectors.nfsz:NFSZCollector",
    "okfo": "scraper.collectors.okfo:OKFOCollector",
    "mak": "scraper.collectors.mak:MAKCollector",
    "jogtar": "scraper.collectors.jogtar:JogtarCollector",
    "hungaromet": "scraper.collectors.hungaromet:HungaroMetCollector",
    "geo": "scraper.collectors.geo:GeoCollector",
    "teir": "scraper.collectors.teir:TeIRCollector",
    "nngyk_foia": "scraper.collectors.nngyk_foia:NNGYKFOIACollector",
}


def _load_collector(name: str):
    mod_name, cls_name = COLLECTORS[name].split(":")
    module = importlib.import_module(mod_name)
    return getattr(module, cls_name)


def _parse_since(value: str | None) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


@app.command()
def main(
    source: str = typer.Option(None, "--source", help=f"one of: {', '.join(COLLECTORS)}"),
    all_sources: bool = typer.Option(False, "--all", help="run every collector"),
    since: str = typer.Option(None, "--since", help="ISO date lower bound (YYYY-MM-DD)"),
    force: bool = typer.Option(False, "--force", help="ignore cache, re-download"),
    dry_run: bool = typer.Option(False, "--dry-run", help="discover only, do not download"),
    list_sources: bool = typer.Option(False, "--list-sources", help="print the collector registry and exit"),
    log_level: str = typer.Option("INFO", "--log-level"),
    cache: bool = typer.Option(True, "--cache/--no-cache"),
    render: bool = typer.Option(False, "--render", help="use playwright for JS pages"),
    max_workers: int = typer.Option(4, "--max-workers"),
) -> None:
    if list_sources:
        for name, target in COLLECTORS.items():
            typer.echo(f"{name:12s} -> {target}")
        raise typer.Exit()
    if not source and not all_sources:
        raise typer.BadParameter("pass --source <name> or --all (or --list-sources)")

    rt = build_runtime(
        log_level=log_level, use_cache=cache, render=render, max_workers=max_workers, with_http=True
    )
    since_d = _parse_since(since)
    names = list(COLLECTORS) if all_sources else [source]
    if all_sources:
        names = [n for n in names if n != "nngyk_foia"]  # FOIA loaded on demand only

    reports = []
    resource_hashes: list[dict] = []
    for name in names:
        if name not in COLLECTORS:
            log.error("run.unknown_source", source=name)
            continue
        try:
            cls = _load_collector(name)
        except ImportError as exc:
            log.error("run.collector_import_failed", source=name, error=str(exc))
            continue
        collector = cls(rt.config, rt.http, render=rt.render)
        report = collector.run(force=force, since=since_d, dry_run=dry_run)
        reports.append(report.as_dict())
        resource_hashes.extend(getattr(report, "resource_hashes", []))
        _write_broken_links(report)

    manifest = write_manifest(
        command=command_string(),
        config_hashes=rt.config.config_hashes(),
        resources=resource_hashes,
        extra={"collector_reports": reports, "dry_run": dry_run},
    )
    typer.echo(f"manifest: {manifest}")
    for r in reports:
        typer.echo(
            f"[{r['name']}] discovered={r['discovered']} fetched={r['fetched']} "
            f"cache={r['from_cache']} broken={len(r['broken_links'])} "
            f"manual={len(r['manual_required'])} quarantined={len(r['quarantined'])} "
            f"errors={len(r['errors'])}"
        )


def _write_broken_links(report) -> None:
    if not report.broken_links:
        return
    path = Path("BROKEN_LINKS.md")
    with path.open("a", encoding="utf-8") as fh:
        if fh.tell() == 0:
            fh.write("# Broken links (404)\n\nURLs that returned 404. Not substituted with guesses.\n\n")
        for url in report.broken_links:
            fh.write(f"- [{report.name}] {url}\n")


if __name__ == "__main__":
    app()

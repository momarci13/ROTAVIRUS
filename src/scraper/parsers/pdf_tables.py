"""Multi-strategy PDF table extraction.

Every strategy is tried; the first result that passes the caller-supplied
structure check wins. For each source PDF we persist:
    data/intermediate/<source>/<file>__table<N>.parquet
    data/intermediate/<source>/<file>__extraction_report.json

Strategies, in order:
    camelot_lattice   ruled tables (needs Ghostscript)
    camelot_stream    whitespace-aligned tables
    pdfplumber_lines  pdfplumber with explicit line detection
    pdfplumber_text   pdfplumber text-position clustering (pure python, always available)
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scraper.core.errors import PDFExtractionError
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.parsers.pdf")

STRATEGY_ORDER = ("camelot_lattice", "camelot_stream", "pdfplumber_lines", "pdfplumber_text")

# A structure check: (df) -> (ok, detail). ``detail`` is recorded in the report.
StructureCheck = Callable[[pd.DataFrame], tuple[bool, dict[str, Any]]]


@dataclass(slots=True)
class ExtractedTable:
    df: pd.DataFrame
    strategy: str
    page: int | str
    index: int
    structure_ok: bool = False
    checks: dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# strategy runners
# --------------------------------------------------------------------------- #


def _run_camelot(path: Path, pages: str, flavor: str) -> list[ExtractedTable]:
    try:
        import camelot
    except Exception as exc:  # pragma: no cover
        log.info("pdf.camelot_unavailable", error=str(exc))
        return []
    try:
        tables = camelot.read_pdf(str(path), pages=pages, flavor=flavor)
    except Exception as exc:
        log.info("pdf.camelot_failed", flavor=flavor, error=str(exc))
        return []
    out: list[ExtractedTable] = []
    for i, t in enumerate(tables):
        out.append(
            ExtractedTable(
                df=t.df.copy(),
                strategy=f"camelot_{flavor}",
                page=getattr(t, "page", pages),
                index=i,
            )
        )
    return out


def _run_pdfplumber(path: Path, pages: str, mode: str) -> list[ExtractedTable]:
    try:
        import pdfplumber
    except Exception as exc:  # pragma: no cover
        log.info("pdf.pdfplumber_unavailable", error=str(exc))
        return []

    settings_by_mode = {
        "pdfplumber_lines": {
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 4,
        },
        "pdfplumber_text": {
            "vertical_strategy": "text",
            "horizontal_strategy": "text",
            "text_tolerance": 3,
        },
    }
    settings = settings_by_mode[mode]
    page_filter = _parse_pages(pages)

    out: list[ExtractedTable] = []
    with pdfplumber.open(str(path)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            if page_filter is not None and pno not in page_filter:
                continue
            try:
                tables = page.extract_tables(settings)
            except Exception as exc:
                log.debug("pdf.pdfplumber_page_failed", page=pno, mode=mode, error=str(exc))
                continue
            for i, raw in enumerate(tables or []):
                if not raw or len(raw) < 2:
                    continue
                df = pd.DataFrame(raw[1:], columns=raw[0])
                out.append(ExtractedTable(df=df, strategy=mode, page=pno, index=i))
    return out


def _parse_pages(pages: str) -> set[int] | None:
    if pages in ("all", "", None):
        return None
    result: set[int] = set()
    for part in str(pages).split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-")
            result.update(range(int(a), int(b) + 1))
        elif part.isdigit():
            result.add(int(part))
    return result or None


_RUNNERS: dict[str, Callable[[Path, str], list[ExtractedTable]]] = {
    "camelot_lattice": lambda p, pg: _run_camelot(p, pg, "lattice"),
    "camelot_stream": lambda p, pg: _run_camelot(p, pg, "stream"),
    "pdfplumber_lines": lambda p, pg: _run_pdfplumber(p, pg, "pdfplumber_lines"),
    "pdfplumber_text": lambda p, pg: _run_pdfplumber(p, pg, "pdfplumber_text"),
}


# --------------------------------------------------------------------------- #
# public API
# --------------------------------------------------------------------------- #


def extract_tables(
    path: Path,
    *,
    pages: str = "all",
    strategies: tuple[str, ...] = STRATEGY_ORDER,
    structure_check: StructureCheck | None = None,
) -> list[ExtractedTable]:
    """Return every candidate table across ``strategies``. If ``structure_check``
    is given, each candidate's ``structure_ok`` / ``checks`` are populated."""
    candidates: list[ExtractedTable] = []
    for strat in strategies:
        runner = _RUNNERS.get(strat)
        if runner is None:
            continue
        found = runner(path, pages)
        log.debug("pdf.strategy_result", strategy=strat, tables=len(found))
        for t in found:
            if structure_check is not None:
                ok, detail = structure_check(t.df)
                t.structure_ok = ok
                t.checks = detail
            candidates.append(t)
    return candidates


def pick_from_candidates(
    candidates: list[ExtractedTable],
    *,
    strategies: tuple[str, ...] = STRATEGY_ORDER,
    filename: str = "",
) -> ExtractedTable:
    for strat in strategies:
        for t in candidates:
            if t.strategy == strat and t.structure_ok:
                log.info("pdf.picked", file=filename, strategy=strat, page=t.page)
                return t
    tried = sorted({c.strategy for c in candidates})
    raise PDFExtractionError(
        f"No strategy produced a valid table for {filename or 'pdf'} "
        f"(tried {tried or list(strategies)}); queue for manual extraction."
    )


def extract_and_pick(
    path: Path,
    *,
    structure_check: StructureCheck,
    pages: str = "all",
    strategies: tuple[str, ...] = STRATEGY_ORDER,
) -> tuple[ExtractedTable, list[ExtractedTable]]:
    """Extract once, then pick. Returns (winner, all_candidates) so callers never
    run extraction twice."""
    candidates = extract_tables(
        path, pages=pages, strategies=strategies, structure_check=structure_check
    )
    return pick_from_candidates(candidates, strategies=strategies, filename=path.name), candidates


def pick_best(
    path: Path,
    *,
    structure_check: StructureCheck,
    pages: str = "all",
    strategies: tuple[str, ...] = STRATEGY_ORDER,
) -> ExtractedTable:
    """First candidate that passes ``structure_check`` (kept for convenience)."""
    return extract_and_pick(
        path, structure_check=structure_check, pages=pages, strategies=strategies
    )[0]


def write_extraction_artifacts(
    out_dir: Path,
    source_pdf: Path,
    picked: ExtractedTable,
    all_candidates: list[ExtractedTable],
) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source_pdf.stem
    table_path = out_dir / f"{stem}__table{picked.index}.parquet"
    picked.df.to_parquet(table_path, index=False)

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source_pdf": source_pdf.name,
        "winning_strategy": picked.strategy,
        "winning_page": picked.page,
        "winning_checks": picked.checks,
        "candidates": [
            {
                "strategy": c.strategy,
                "page": c.page,
                "index": c.index,
                "rows": len(c.df),
                "cols": c.df.shape[1],
                "structure_ok": c.structure_ok,
                "checks": c.checks,
            }
            for c in all_candidates
        ],
    }
    report_path = out_dir / f"{stem}__extraction_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return table_path, report_path

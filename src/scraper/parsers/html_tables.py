"""HTML table extraction for OKFŐ vacant-practice pages and NEAK listings."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scraper.core.logging_setup import get_logger

log = get_logger("scraper.parsers.html")


def read_tables(html: str | Path, *, min_rows: int = 3) -> list[pd.DataFrame]:
    """Return every HTML <table> with at least ``min_rows`` rows."""
    text = Path(html).read_text(encoding="utf-8", errors="replace") if isinstance(html, Path) else html
    try:
        tables = pd.read_html(text, flavor="lxml")
    except ValueError:
        try:
            tables = pd.read_html(text, flavor="bs4")
        except ValueError:
            return []
    return [t for t in tables if len(t) >= min_rows]


def pick_table(tables: list[pd.DataFrame], *, must_contain_cols: tuple[str, ...]) -> pd.DataFrame | None:
    """First table whose (lowercased) column labels contain every token."""
    for t in tables:
        cols = " ".join(str(c).lower() for c in t.columns)
        if all(tok.lower() in cols for tok in must_contain_cols):
            return t
    return None


def normalise_columns(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Rename columns by case-insensitive substring match against ``mapping`` keys."""
    rename: dict[str, str] = {}
    for col in df.columns:
        low = str(col).strip().lower()
        for token, target in mapping.items():
            if token.lower() in low:
                rename[col] = target
                break
    return df.rename(columns=rename)

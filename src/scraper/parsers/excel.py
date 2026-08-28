"""Excel / CSV helpers for STADAT, TSZJ, NFSZ and MÁK workbooks."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from scraper.core.logging_setup import get_logger

log = get_logger("scraper.parsers.excel")


def read_any_table(path: Path, *, sheet: str | int | None = None, header: int | None = 0) -> pd.DataFrame:
    """Read xlsx/xls/csv into a DataFrame, tolerating messy STADAT headers."""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, header=header, dtype=object)
    if suffix == ".xls":
        return pd.read_excel(path, sheet_name=sheet if sheet is not None else 0, header=header, dtype=object, engine="xlrd")
    if suffix == ".csv":
        for enc in ("utf-8", "cp1250", "latin-1"):
            for sep in (";", ",", "\t"):
                try:
                    df = pd.read_csv(path, sep=sep, encoding=enc, header=header, dtype=object)
                    if df.shape[1] > 1:
                        return df
                except Exception:
                    continue
        return pd.read_csv(path, dtype=object)
    raise ValueError(f"unsupported spreadsheet type: {path.suffix}")


def list_sheets(path: Path) -> list[str]:
    try:
        xls = pd.ExcelFile(path)
        return [str(s) for s in xls.sheet_names]
    except Exception as exc:
        log.warning("excel.list_sheets_failed", path=str(path), error=str(exc))
        return []


def find_header_row(raw: pd.DataFrame, *, must_contain: tuple[str, ...], max_scan: int = 15) -> int | None:
    """Locate the row index that looks like a header (contains all tokens)."""
    lowered = raw.astype(str).apply(lambda s: s.str.lower())
    for i in range(min(max_scan, len(lowered))):
        joined = " ".join(lowered.iloc[i].tolist())
        if all(tok.lower() in joined for tok in must_contain):
            return i
    return None

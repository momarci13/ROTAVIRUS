"""Source schema-drift detection (spec §7.1 / rule 12).

For every parsed table we fingerprint the column names + dtypes into
``data/metadata/schema_snapshots/<source>.json``. On a later run a changed
fingerprint does NOT crash the pipeline: the difference is reported, affected
rows are marked ``quality_flag='schema_drift'`` and ``SCHEMA_DRIFT_REPORT.md``
is (re)written.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from scraper import METADATA_DIR
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.validation.drift")

SNAPSHOT_DIR = METADATA_DIR / "schema_snapshots"
DRIFT_MD = Path("SCHEMA_DRIFT_REPORT.md")


def fingerprint(df: pd.DataFrame) -> dict:
    cols = [{"name": str(c), "dtype": str(t)} for c, t in zip(df.columns, df.dtypes)]
    blob = json.dumps(cols, sort_keys=True, ensure_ascii=False)
    return {"columns": cols, "hash": hashlib.sha256(blob.encode("utf-8")).hexdigest()}


@dataclass
class DriftResult:
    source: str
    changed: bool
    added: list[str]
    removed: list[str]
    dtype_changed: list[str]
    first_seen: bool = False


def check_and_update(source: str, df: pd.DataFrame) -> DriftResult:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{source}.json"
    new_fp = fingerprint(df)

    if not path.exists():
        path.write_text(
            json.dumps({"updated_at": datetime.now(UTC).isoformat(), **new_fp}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return DriftResult(source, changed=False, added=[], removed=[], dtype_changed=[], first_seen=True)

    old = json.loads(path.read_text(encoding="utf-8"))
    if old.get("hash") == new_fp["hash"]:
        return DriftResult(source, changed=False, added=[], removed=[], dtype_changed=[])

    old_cols = {c["name"]: c["dtype"] for c in old.get("columns", [])}
    new_cols = {c["name"]: c["dtype"] for c in new_fp["columns"]}
    added = sorted(set(new_cols) - set(old_cols))
    removed = sorted(set(old_cols) - set(new_cols))
    dtype_changed = sorted(k for k in set(old_cols) & set(new_cols) if old_cols[k] != new_cols[k])

    result = DriftResult(source, True, added, removed, dtype_changed)
    _append_report(result)
    log.warning("drift.detected", source=source, added=added, removed=removed, dtype_changed=dtype_changed)

    # move the snapshot forward so the drift is reported once, not every run
    path.write_text(
        json.dumps(
            {"updated_at": datetime.now(UTC).isoformat(), "previous_hash": old.get("hash"), **new_fp},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return result


def mark_frame(df: pd.DataFrame, result: DriftResult) -> pd.DataFrame:
    if not result.changed:
        return df
    if "quality_flag" not in df.columns:
        df = df.assign(quality_flag="")
    df["quality_flag"] = df["quality_flag"].mask(df["quality_flag"].eq("") | df["quality_flag"].isna(), "schema_drift")
    return df


def _append_report(r: DriftResult) -> None:
    header = not DRIFT_MD.exists()
    with DRIFT_MD.open("a", encoding="utf-8") as fh:
        if header:
            fh.write("# Séma-drift jelentés\n\nForrássémák megváltozása. A futás nem állt le.\n\n")
        fh.write(
            f"## {r.source} — {datetime.now(UTC).isoformat()}\n\n"
            f"- Új oszlopok: {r.added or '—'}\n"
            f"- Eltűnt oszlopok: {r.removed or '—'}\n"
            f"- Megváltozott dtype: {r.dtype_changed or '—'}\n\n"
        )

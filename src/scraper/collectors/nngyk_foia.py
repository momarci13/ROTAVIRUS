"""nngyk_foia collector.

When NNGYK delivers real district-level rotavirus data in response to a data
request, drop the file(s) into ``data/raw/nngyk_foia/``. This collector loads
them into the SAME schema as the modelled panel, but with
``geo_level='district'`` and ``evidence_class='observed'`` — the ONLY path by
which an observed district-level rotavirus record is allowed (spec 2.1, 8.9).

Expected columns (any spelling; mapped case-insensitively):
    district_id | district code, period_start (or year+week/month), cases
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pandas as pd

from scraper import RAW_DIR
from scraper.collectors.base import Collector, Resource, ValidationReport
from scraper.core.errors import ManualExportMissingError
from scraper.parsers.excel import read_any_table

FOIA_DIR = RAW_DIR / "nngyk_foia"


class NNGYKFOIACollector(Collector):
    name = "nngyk_foia"
    source_config_key = "nngyk_foia"

    def discover(self, *, since: date | None = None) -> list[Resource]:
        FOIA_DIR.mkdir(parents=True, exist_ok=True)
        files = [p for p in FOIA_DIR.glob("**/*") if p.suffix.lower() in {".xlsx", ".xls", ".csv"}]
        if not files:
            raise ManualExportMissingError(
                f"No FOIA delivery found. Place NNGYK district-level files in {FOIA_DIR}."
            )
        return [
            Resource(key=p.stem, url=p.as_uri(), resource_type="foia", filename=p.name)
            for p in files
        ]

    def fetch(self, resource: Resource, *, force: bool = False):
        return FOIA_DIR / resource.target_name()

    def parse(self, path: Path) -> pd.DataFrame:
        raw = read_any_table(path)
        raw.columns = [str(c).strip().lower() for c in raw.columns]
        did = next((c for c in raw.columns if "district" in c or "járás" in c or "ksh" in c), None)
        cases = next((c for c in raw.columns if "case" in c or "eset" in c or "szám" in c), None)
        if did is None or cases is None:
            self.log.error("foia.unrecognised_columns", cols=list(raw.columns))
            return pd.DataFrame()
        out = pd.DataFrame(
            {
                "district_id": raw[did].astype(str).str.strip(),
                "value": pd.to_numeric(raw[cases], errors="coerce"),
            }
        )
        year_col = next((c for c in raw.columns if c in {"year", "év", "ev"}), None)
        week_col = next((c for c in raw.columns if "week" in c or "hét" in c or "het" in c), None)
        start_col = next((c for c in raw.columns if "start" in c or "date" in c or "dátum" in c), None)
        if start_col:
            out["period_start"] = pd.to_datetime(raw[start_col], errors="coerce").dt.date
        elif year_col and week_col:
            out["period_start"] = [
                _iso_monday(y, w) for y, w in zip(raw[year_col], raw[week_col])
            ]
        else:
            out["period_start"] = None
        out["geo_level"] = "district"
        out["variable"] = "rotavirus_cases"
        out["evidence_class"] = "observed"
        out["source_id"] = "nngyk_foia"
        out["source_file"] = path.name
        return out.dropna(subset=["value"])

    def validate(self, df: pd.DataFrame) -> ValidationReport:
        rep = ValidationReport(rows=len(df))
        if df.empty:
            rep.warn("no FOIA rows parsed")
            return rep
        if (df["value"] < 0).any():
            rep.error("negative case counts")
        return rep


def _iso_monday(year, week):
    try:
        return date.fromisocalendar(int(year), int(re.sub(r"\D", "", str(week))), 1)
    except (ValueError, TypeError):
        return None

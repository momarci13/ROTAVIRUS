"""TeIR collector - stub.

TeIR is registration-gated and its robots policy disallows crawling, so this
collector only ingests a manual export. It never scrapes.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from scraper import RAW_DIR
from scraper.collectors.base import Collector, Resource
from scraper.core.errors import ManualExportMissingError
from scraper.parsers.excel import read_any_table

MANUAL_DIR = RAW_DIR / "other" / "teir"

_HELP = f"""\
TeIR requires a manual export (registration-gated, crawling disallowed).

Steps:
  1. Log in at https://www.teir.hu (or the TeIR Ágazati/Helyzet-Tér-Kép module).
  2. Select the district-level indicators you need and export to XLSX/CSV.
  3. Save the files unchanged into:
       {MANUAL_DIR}
  4. Re-run `python -m scraper.run --source teir`.
"""


class TeIRCollector(Collector):
    name = "teir"
    source_config_key = "teir"

    def discover(self, *, since: date | None = None) -> list[Resource]:
        MANUAL_DIR.mkdir(parents=True, exist_ok=True)
        files = [p for p in MANUAL_DIR.glob("*") if p.suffix.lower() in {".xlsx", ".xls", ".csv"}]
        if not files:
            self.log.warning("teir.manual_missing")
            raise ManualExportMissingError(_HELP)
        return [
            Resource(key=p.stem, url=p.as_uri(), resource_type="manual_export", filename=p.name, manual=False)
            for p in files
        ]

    def fetch(self, resource: Resource, *, force: bool = False):
        # manual exports already sit in the raw store
        return MANUAL_DIR / resource.target_name()

    def parse(self, path: Path) -> pd.DataFrame:
        try:
            df = read_any_table(path)
        except Exception as exc:
            self.log.warning("teir.parse_failed", file=path.name, error=str(exc))
            return pd.DataFrame()
        df.columns = [str(c).strip().lower() for c in df.columns]
        df["source_id"] = "teir"
        df["source_file"] = path.name
        df["evidence_class"] = "observed"
        return df

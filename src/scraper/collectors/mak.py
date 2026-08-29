"""Magyar Államkincstár collector: municipal annual budget reports (own revenue
and expenditure per capita -> the fiscal-capacity block)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from scraper.collectors._discovery import extract_links
from scraper.collectors.base import Collector, Resource
from scraper.parsers.excel import read_any_table


class MAKCollector(Collector):
    name = "mak"
    source_config_key = "mak"

    def discover(self, *, since: date | None = None) -> list[Resource]:
        r = self.source.resource("onkormanyzati_beszamolok")
        out: list[Resource] = []
        try:
            res = self.http_client.fetch(r.url, rate_limit=self.rate_limit())
            links = extract_links(
                res.content.decode("utf-8", "replace"), r.url, suffixes=(".xlsx", ".xls", ".csv", ".zip")
            )
        except Exception as exc:
            self.log.warning("mak.discover_failed", error=str(exc))
            links = []
        for link in links:
            out.append(
                Resource(
                    key=f"mak_{Path(link).stem[:50]}",
                    url=link,
                    resource_type="budget_report",
                    filename=Path(link).name,
                )
            )
        if not out:
            self.log.warning(
                "mak.no_files",
                hint="portal may require interactive report selection; place exports in data/raw/mak/manual/",
            )
            # surface it in MANUAL_EXTRACTION_QUEUE.md via the run reporter
            out.append(
                Resource(
                    key="mak_onkormanyzati_beszamolok_manual",
                    url=r.url,
                    resource_type="manual_export",
                    manual=True,
                    meta={
                        "notes": "ÁKD közpénzügyi portál: interaktív riportépítő, nincs tömeges "
                        "letöltés. Építs 'Éves költségvetési beszámoló' riportot települési "
                        "bontásban (saját bevétel, kiadás), és mentsd XLSX-ként ide: "
                        "data/raw/mak/manual/"
                    },
                )
            )
        return out

    def parse(self, path: Path) -> pd.DataFrame:
        if path.suffix.lower() not in {".xlsx", ".xls", ".csv"}:
            self.log.info("mak.archived_only", file=path.name)
            return pd.DataFrame()
        try:
            raw = read_any_table(path)
        except Exception as exc:
            self.log.warning("mak.parse_failed", file=path.name, error=str(exc))
            return pd.DataFrame()
        raw.columns = [str(c).strip().lower() for c in raw.columns]
        id_col = next((c for c in raw.columns if "törzs" in c or "ksh" in c or "önkormányzat" in c), None)
        rev_col = next((c for c in raw.columns if "saját" in c and "bevétel" in c), None)
        exp_col = next((c for c in raw.columns if "kiadás" in c), None)
        if id_col is None or (rev_col is None and exp_col is None):
            self.log.info("mak.unrecognised", file=path.name, cols=list(raw.columns)[:12])
            return pd.DataFrame()
        out = pd.DataFrame({"settlement_id": raw[id_col].astype(str)})
        if rev_col:
            out["municipal_own_revenue"] = pd.to_numeric(raw[rev_col], errors="coerce")
        if exp_col:
            out["municipal_expenditure"] = pd.to_numeric(raw[exp_col], errors="coerce")
        out["evidence_class"] = "observed"
        out["source_id"] = "mak"
        out["source_file"] = path.name
        out["geo_level"] = "settlement"
        return out

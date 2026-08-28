"""NFSZ collector: settlement-level monthly registered-jobseeker data and
county earnings. Settlement rows are later aggregated to districts via the
geography registry."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from scraper.collectors._discovery import extract_links
from scraper.collectors.base import Collector, Resource
from scraper.parsers.excel import find_header_row, read_any_table


class NFSZCollector(Collector):
    name = "nfsz"
    source_config_key = "nfsz"

    def discover(self, *, since: date | None = None) -> list[Resource]:
        src = self.source
        out: list[Resource] = []
        for key in ("telepulessoros", "teruleti_bontas", "egyeni_berek"):
            r = src.resource(key)
            try:
                res = self.http_client.fetch(r.url, rate_limit=self.rate_limit())
                links = extract_links(
                    res.content.decode("utf-8", "replace"), r.url, suffixes=(".xlsx", ".xls", ".csv", ".zip")
                )
            except Exception as exc:
                self.log.warning("nfsz.discover_failed", key=key, error=str(exc))
                continue
            for link in links:
                out.append(
                    Resource(
                        key=f"{key}_{Path(link).stem}",
                        url=link,
                        resource_type=key,
                        filename=Path(link).name,
                    )
                )
        if not out:
            self.log.warning("nfsz.no_files_discovered", hint="file list may be JS-rendered; use --render or manual export")
        return out

    def parse(self, path: Path) -> pd.DataFrame:
        if path.suffix.lower() not in {".xlsx", ".xls", ".csv"}:
            self.log.info("nfsz.archived_only", file=path.name)
            return pd.DataFrame()
        try:
            raw = read_any_table(path, header=None)
        except Exception as exc:
            self.log.warning("nfsz.parse_failed", file=path.name, error=str(exc))
            return pd.DataFrame()
        hdr = find_header_row(raw, must_contain=("nyilvántartott",)) or find_header_row(
            raw, must_contain=("álláskeres",)
        )
        if hdr is None:
            self.log.info("nfsz.header_not_found", file=path.name)
            return pd.DataFrame()
        df = raw.iloc[hdr + 1 :].copy()
        df.columns = [str(c).strip().lower() for c in raw.iloc[hdr].tolist()]
        df = df.rename(
            columns={
                next((c for c in df.columns if "ksh" in c or "törzs" in c), "settlement_id"): "settlement_id",
                next((c for c in df.columns if "telep" in c), "settlement_name"): "settlement_name",
                next((c for c in df.columns if "álláskeres" in c or "nyilvántartott" in c), "registered_jobseekers"): "registered_jobseekers",
            }
        )
        keep = [c for c in ("settlement_id", "settlement_name", "registered_jobseekers") if c in df.columns]
        if "registered_jobseekers" not in keep:
            return pd.DataFrame()
        df = df[keep].dropna(subset=["registered_jobseekers"])
        df["registered_jobseekers"] = pd.to_numeric(df["registered_jobseekers"], errors="coerce")
        df["evidence_class"] = "observed"
        df["source_id"] = "nfsz"
        df["source_file"] = path.name
        df["geo_level"] = "settlement"
        return df.dropna(subset=["registered_jobseekers"])

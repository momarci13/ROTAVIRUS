"""NFSZ collector: settlement-level monthly registered-jobseeker data and
county earnings. Settlement rows are later aggregated to districts via the
geography registry.

The public pages carry no static links: a page-load XHR
(``POST /common/service/requestparser``) returns the document list as JSON.
The endpoint, form name and per-page category id live in ``config/sources.yaml``
(resolved 2026-08-28) — nothing about the site is hard-coded here.
"""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd

from scraper.collectors._discovery import extract_links
from scraper.collectors.base import Collector, Resource
from scraper.parsers.excel import find_header_row, list_sheets, read_any_table

# yyyymm embedded in a filename (T01202607.xlsx, ..._202606_uj.xls, T01_202604.xlsx)
_YM_RE = re.compile(r"(20\d{2})[._]?(0[1-9]|1[012])(?:\D|$)")
_YEAR_RE = re.compile(r"\b(20\d{2})\b")
_HU_MONTHS = {
    "január": 1, "február": 2, "március": 3, "április": 4, "május": 5, "június": 6,
    "július": 7, "augusztus": 8, "szeptember": 9, "október": 10, "november": 11, "december": 12,
}


def _find_col(labels: list[str], *tokens: str) -> int | None:
    """Index of the first header label containing every token (all lower-case)."""
    for j, lab in enumerate(labels):
        if all(t in lab for t in tokens):
            return j
    return None


def _period_from(title: str, filename: str) -> date | None:
    m = _YM_RE.search(filename) or _YM_RE.search(title)
    if m:
        return date(int(m.group(1)), int(m.group(2)), 1)
    low = title.lower()
    ym = _YEAR_RE.search(low)
    if ym:
        for name, mon in _HU_MONTHS.items():
            if name in low:
                return date(int(ym.group(1)), mon, 1)
        return date(int(ym.group(1)), 1, 1)
    return None


class NFSZCollector(Collector):
    name = "nfsz"
    source_config_key = "nfsz"

    def discover(self, *, since: date | None = None) -> list[Resource]:
        src = self.source
        endpoint = getattr(src, "xhr_endpoint", None)
        form_name = getattr(src, "xhr_form_name", "statistics_filter_documents")
        base = src.base_url or "https://nfsz.munka.hu"
        out: list[Resource] = []

        for r in src.resources:
            cat_id = getattr(r, "doc_category_id", None)
            if endpoint and cat_id is not None:
                out.extend(self._discover_via_xhr(endpoint, form_name, base, r, cat_id, since))
            else:
                out.extend(self._discover_via_links(base, r))

        if not out:
            self.log.warning(
                "nfsz.no_files_discovered",
                hint="XHR endpoint returned nothing; check config/sources.yaml or use a manual export",
            )
        return out

    def _discover_via_xhr(
        self, endpoint: str, form_name: str, base: str, r, cat_id: int, since: date | None
    ) -> list[Resource]:
        form = {
            "documentTitle": "",
            "dateFrom": "",
            "dateTo": "",
            "id": str(cat_id),
            "name": form_name,
            "type": "all",
        }
        try:
            res = self.http_client.fetch(
                endpoint,
                method="POST",
                rate_limit=self.rate_limit(),
                data=form,
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            records = json.loads(res.content.decode("utf-8", "replace") or "[]")
        except Exception as exc:
            self.log.warning("nfsz.xhr_failed", key=r.key, error=str(exc))
            return [Resource(key=r.key, url=r.url, resource_type="listing")]

        out: list[Resource] = []
        for rec in records:
            doc = rec.get("DOC_URL_PUB") or ""
            if not doc:
                continue
            url = urljoin(base + "/", doc.lstrip("/"))
            fname = Path(doc.split("?")[0]).name
            title = str(rec.get("TITLE") or "").strip()
            period = _period_from(title, fname)
            if since and period and period < since:
                continue
            out.append(
                Resource(
                    key=f"{r.key}_{fname}",
                    url=url,
                    resource_type=r.key,
                    filename=fname,
                    period=period,
                    meta={"title": title, "category_id": cat_id},
                )
            )
        self.log.info("nfsz.xhr_discovered", key=r.key, count=len(out))
        return out

    def _discover_via_links(self, base: str, r) -> list[Resource]:
        try:
            res = self.http_client.fetch(r.url, rate_limit=self.rate_limit())
            links = extract_links(
                res.content.decode("utf-8", "replace"), r.url, suffixes=(".xlsx", ".xls", ".csv", ".zip")
            )
        except Exception as exc:
            self.log.warning("nfsz.discover_failed", key=r.key, error=str(exc))
            return []
        return [
            Resource(key=f"{r.key}_{Path(link).stem}", url=link, resource_type=r.key, filename=Path(link).name)
            for link in links
        ]

    def parse(self, path: Path) -> pd.DataFrame:
        low = path.name.lower()
        if path.suffix.lower() not in {".xlsx", ".xls", ".csv"}:
            self.log.info("nfsz.archived_only", file=path.name)
            return pd.DataFrame()
        if low.startswith("t01"):
            return self._parse_settlement_workbook(path)
        # the "…idősorai…" time-series workbooks are multi-block county/national
        # aggregates with no settlement rows — not used for the district panel.
        self.log.info("nfsz.timeseries_skipped", file=path.name)
        return pd.DataFrame()

    def _parse_settlement_workbook(self, path: Path) -> pd.DataFrame:
        """T01 'nyilvántartott álláskeresők településenként' — one sheet per
        vármegye, a two-line column header, settlement rows keyed by name only
        (mapped to districts by the geography crosswalk downstream)."""
        sheets: list[str | int] = list(list_sheets(path)) or [0]
        period = _period_from("", path.name)
        frames: list[pd.DataFrame] = []
        for sh in sheets:
            try:
                raw = read_any_table(path, sheet=sh, header=None)
            except Exception as exc:
                self.log.warning("nfsz.sheet_failed", file=path.name, sheet=str(sh), error=str(exc))
                continue
            hdr = find_header_row(raw, must_contain=("relatív",)) or find_header_row(
                raw, must_contain=("nyilvántar",)
            )
            if hdr is None:
                continue
            labels = [str(x).lower().replace("\n", " ") for x in raw.iloc[hdr].tolist()]
            c_total = _find_col(labels, "össz")
            if c_total is None:
                continue
            c_wap = _find_col(labels, "korú")
            c_rel = _find_col(labels, "relatív")
            body = raw.iloc[hdr + 1 :]
            name = body.iloc[:, 0].astype(str).str.strip()
            reg = pd.to_numeric(body.iloc[:, c_total], errors="coerce")
            out = pd.DataFrame(
                {
                    "settlement_name": name,
                    "registered_jobseekers": reg,
                    "working_age_population": (
                        pd.to_numeric(body.iloc[:, c_wap], errors="coerce") if c_wap is not None else pd.NA
                    ),
                    "relative_indicator_pct": (
                        pd.to_numeric(body.iloc[:, c_rel], errors="coerce") if c_rel is not None else pd.NA
                    ),
                }
            )
            out = out[
                out["settlement_name"].str.len().gt(0)
                & ~out["settlement_name"].str.lower().str.contains("össz|nan|\\*|forrás|megjegyz", regex=True)
                & out["registered_jobseekers"].notna()
            ]
            out["county_sheet"] = str(sh)
            frames.append(out)

        if not frames:
            self.log.info("nfsz.header_not_found", file=path.name)
            return pd.DataFrame()
        df = pd.concat(frames, ignore_index=True)
        df["period_start"] = period.isoformat() if period else None
        df["evidence_class"] = "observed"
        df["source_id"] = "nfsz"
        df["source_file"] = path.name
        df["geo_level"] = "settlement"
        return df

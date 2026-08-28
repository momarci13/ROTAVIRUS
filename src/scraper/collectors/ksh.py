"""KSH collector: STADAT infectious-disease tables, the Területi Számjelrendszer
(TSZJ), the gazetteer, the 2022 census, price indices (for the deflator), and
manual-only databases (Tájékoztatási adatbázis, TIMEA).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import ClassVar

import pandas as pd

from scraper.collectors._discovery import extract_links
from scraper.collectors.base import Collector, Resource
from scraper.parsers.excel import read_any_table

_YEAR_RE = re.compile(r"(20\d{2})")


class KSHCollector(Collector):
    name = "ksh"
    source_config_key = "ksh"

    ROBOTS_DISALLOWED_KEYS: ClassVar[set[str]] = {"tajekoztatasi_adatbazis"}
    MANUAL_KEYS: ClassVar[set[str]] = {"timea", "tajekoztatasi_adatbazis"}

    def discover(self, *, since: date | None = None) -> list[Resource]:
        src = self.source
        out: list[Resource] = []

        for key in ("stadat_ege0028", "stadat_ege0060"):
            r = src.resource(key)
            out.append(
                Resource(key=key, url=r.url, resource_type="stadat_xlsx", filename=f"{key}.xlsx")
            )

        # TSZJ listing -> yearly workbooks
        tszj = src.resource("tszj_structure")
        try:
            res = self.http_client.fetch(tszj.url, rate_limit=self.rate_limit())
            links = extract_links(res.content.decode("utf-8", "replace"), tszj.url, suffixes=(".xlsx", ".pdf"))
            for link in links:
                if "szamjel" in link.lower():
                    out.append(
                        Resource(
                            key=f"tszj_{Path(link).stem}",
                            url=link,
                            resource_type="tszj",
                            filename=Path(link).name,
                        )
                    )
        except Exception as exc:
            self.log.warning("ksh.tszj_discover_failed", error=str(exc))

        # gazetteer (hnk) yearly pattern
        hnk = src.resource("hnk_pattern")
        years = self.config.geography.sources_years.get("hnk", [])
        for yr in years:
            if since and yr < since.year:
                continue
            out.append(
                Resource(
                    key=f"hnk_{yr}",
                    url=hnk.url.format(year=yr),
                    resource_type="gazetteer_pdf",
                    filename=f"hnk_{yr}.pdf",
                    year=yr,
                )
            )

        # price index (to_discover) -> try to locate on STADAT 'ar' theme
        out.extend(self._discover_price_index())

        # manual-only sources: emit as manual resources (fetch() will note them)
        for key in self.MANUAL_KEYS:
            r = src.resource(key)
            out.append(
                Resource(
                    key=key,
                    url=r.url or "",
                    resource_type="manual",
                    manual=True,
                    meta={"notes": r.notes},
                )
            )
        return out

    def _discover_price_index(self) -> list[Resource]:
        """Resolve the STADAT price-index tables used by the deflator.

        Known STADAT ids: qsf001 (headline CPI, yearly), qsf003 (CPI by group),
        qli / earnings. We probe a small candidate set and register whichever
        resolves; unresolved stays flagged for BROKEN_LINKS.md.
        """
        candidates = {
            "price_headline_cpi": "https://www.ksh.hu/stadat_files/ara/hu/ara0001.xlsx",
            "price_cpi_by_group": "https://www.ksh.hu/stadat_files/ara/hu/ara0003.xlsx",
            "price_earnings_index": "https://www.ksh.hu/stadat_files/mun/hu/mun0080.xlsx",
        }
        out: list[Resource] = []
        for key, url in candidates.items():
            try:
                res = self.http_client.fetch(url, method="GET", rate_limit=self.rate_limit(), allow_404=True)
                if res.status_code == 200 and res.content[:2] in (b"PK", b"\xd0\xcf"):
                    out.append(Resource(key=key, url=url, resource_type="stadat_xlsx", filename=f"{key}.xlsx"))
                else:
                    self.report.broken_links.append(url)
            except Exception as exc:
                self.log.warning("ksh.price_index_probe_failed", url=url, error=str(exc))
        return out

    def parse(self, path: Path) -> pd.DataFrame:
        name = path.name.lower()
        if name.startswith(("stadat_ege0028", "stadat_ege0060")):
            return self._parse_stadat_disease(path)
        if name.startswith("price_"):
            return self._parse_price_index(path)
        # TSZJ workbooks feed the geography module, not the epi panel; archive only.
        self.log.info("ksh.archived_only", file=path.name)
        return pd.DataFrame()

    def _parse_stadat_disease(self, path: Path) -> pd.DataFrame:
        try:
            raw = read_any_table(path, header=None)
        except Exception as exc:
            self.log.warning("ksh.stadat_parse_failed", file=path.name, error=str(exc))
            return pd.DataFrame()
        # STADAT layout: first column = period/label, wide years across columns.
        raw = raw.dropna(how="all").reset_index(drop=True)
        mask = raw.apply(lambda r: r.astype(str).str.contains("otavírus", case=False).any(), axis=1)
        if not mask.any():
            self.log.info("ksh.stadat_no_rotavirus_row", file=path.name)
            return pd.DataFrame()
        row = raw[mask].iloc[0]
        values = pd.to_numeric(row[1:], errors="coerce").dropna()
        rec = [
            {
                "geo_level": "country",
                "geo_name": "Magyarország",
                "variable": "rotavirus_cases_stadat",
                "value": float(v),
                "evidence_class": "observed",
                "source_id": "ksh",
                "source_file": path.name,
                "col_index": int(i),
            }
            for i, v in enumerate(values)
        ]
        return pd.DataFrame(rec)

    def _parse_price_index(self, path: Path) -> pd.DataFrame:
        try:
            raw = read_any_table(path, header=None)
        except Exception as exc:
            self.log.warning("ksh.price_parse_failed", file=path.name, error=str(exc))
            return pd.DataFrame()
        long = raw.dropna(how="all").reset_index(drop=True)
        rec: list[dict] = []
        for _, r in long.iterrows():
            cells = r.tolist()
            ym = _YEAR_RE.search(str(cells[0]))
            if not ym:
                continue
            val = pd.to_numeric(pd.Series(cells[1:]), errors="coerce").dropna()
            if len(val):
                rec.append(
                    {
                        "deflator_source_file": path.name,
                        "year": int(ym.group(1)),
                        "index_value": float(val.iloc[0]),
                        "evidence_class": "observed",
                        "source_id": "ksh",
                    }
                )
        return pd.DataFrame(rec)

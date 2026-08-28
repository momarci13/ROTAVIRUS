"""OKFŐ collector: chronically vacant GP / paediatric / dental practice lists.

The pages are snapshots with no downloadable file, so:
  * raw HTML is saved with a datestamp,
  * a time series is built from repeated runs,
  * historical snapshots are seeded from the Wayback Machine CDX API.
Practices are matched to districts by settlement name / postal code
(crosswalk.py) downstream — fuzzy hits never enter the panel automatically.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import quote

import pandas as pd

from scraper.collectors.base import Collector, Resource
from scraper.parsers.html_tables import normalise_columns, read_tables

_TYPE_MAP = {"v": "gp_adult", "f": "paediatric", "g": "mixed"}


class OKFOCollector(Collector):
    name = "okfo"
    source_config_key = "okfo"

    def discover(self, *, since: date | None = None) -> list[Resource]:
        src = self.source
        stamp = datetime.now(UTC).strftime("%Y%m%d")
        out: list[Resource] = []
        for key in ("vacant_gp", "vacant_dental"):
            r = src.resource(key)
            out.append(
                Resource(
                    key=f"{key}_{stamp}",
                    url=r.url,
                    resource_type="html_snapshot",
                    filename=f"{key}_{stamp}.html",
                    meta={"kind": key},
                )
            )
        out.extend(self._discover_wayback(src.resource("vacant_gp").url, since))
        return out

    def _discover_wayback(self, target: str, since: date | None) -> list[Resource]:
        cdx = self.source.resource("wayback_cdx").url
        url = cdx.format(target=quote(target, safe=""))
        try:
            res = self.http_client.fetch(url, rate_limit=self.rate_limit())
            rows = json.loads(res.content.decode("utf-8", "replace"))
        except Exception as exc:
            self.log.warning("okfo.wayback_failed", error=str(exc))
            return []
        if not rows or len(rows) < 2:
            return []
        header, *data = rows
        idx_ts, idx_orig = header.index("timestamp"), header.index("original")
        out: list[Resource] = []
        seen_months: set[str] = set()
        for row in data:
            ts = row[idx_ts]
            month = ts[:6]
            if month in seen_months:
                continue
            seen_months.add(month)
            snap_date = datetime.strptime(ts[:8], "%Y%m%d").date()
            if since and snap_date < since:
                continue
            out.append(
                Resource(
                    key=f"wayback_{ts}",
                    url=f"https://web.archive.org/web/{ts}/{row[idx_orig]}",
                    resource_type="html_snapshot_wayback",
                    filename=f"vacant_gp_wayback_{ts[:8]}.html",
                    meta={"kind": "vacant_gp", "snapshot": ts},
                )
            )
        return out

    def parse(self, path: Path) -> pd.DataFrame:
        try:
            tables = read_tables(path, min_rows=3)
        except Exception as exc:
            self.log.warning("okfo.parse_failed", file=path.name, error=str(exc))
            return pd.DataFrame()
        if not tables:
            self.log.info("okfo.no_tables", file=path.name)
            return pd.DataFrame()
        df = max(tables, key=len)
        df = normalise_columns(
            df,
            {
                "vármegye": "county_name",
                "megye": "county_name",
                "típus": "practice_type_raw",
                "irányítószám": "postal_code",
                "irsz": "postal_code",
                "település": "settlement_name",
                "betöltetlen": "vacant_since",
            },
        )
        if "settlement_name" not in df.columns and "postal_code" not in df.columns:
            self.log.info("okfo.unrecognised_table", file=path.name, cols=list(df.columns)[:10])
            return pd.DataFrame()
        df["practice_type"] = (
            df.get("practice_type_raw", pd.Series(index=df.index, dtype=object))
            .astype(str).str.strip().str.lower().map(_TYPE_MAP)
        )
        stamp = _stamp_from_name(path.name)
        df["snapshot_date"] = stamp
        df["evidence_class"] = "observed"
        df["source_id"] = "okfo"
        df["source_file"] = path.name
        df["geo_level"] = "settlement"
        keep = [
            c
            for c in ("county_name", "settlement_name", "postal_code", "practice_type", "vacant_since", "snapshot_date", "evidence_class", "source_id", "source_file", "geo_level")
            if c in df.columns
        ]
        return df[keep]


def _stamp_from_name(name: str) -> str | None:
    import re

    m = re.search(r"(\d{8})", name)
    if not m:
        return None
    return datetime.strptime(m.group(1), "%Y%m%d").date().isoformat()

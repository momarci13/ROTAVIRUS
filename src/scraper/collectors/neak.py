"""NEAK collector: base-rate communiqués (Ft/súlyszám, Ft/német pont), the
inpatient/outpatient rule-books, PUPHA drug register, and hospital bed counts.
These feed config/cost_parameters.yaml — the collector extracts *candidate*
values with citations; a human confirms them into the YAML.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import ClassVar

import pandas as pd

from scraper.collectors._discovery import extract_links
from scraper.collectors.base import Collector, Resource
from scraper.parsers.html_tables import read_tables

_FT_RE = re.compile(r"(\d[\d\s]{2,})\s*(?:Ft|forint)", re.IGNORECASE)
CANDIDATES_OUT = Path("data/intermediate/neak/cost_parameter_candidates.json")


class NEAKCollector(Collector):
    name = "neak"
    source_config_key = "neak"

    RENDER_KEYS: ClassVar[set[str]] = {"alapdij_kozlemeny"}

    def discover(self, *, since: date | None = None) -> list[Resource]:
        src = self.source
        out: list[Resource] = []
        for r in src.resources:
            if r.type != "listing":
                continue
            render = r.key in self.RENDER_KEYS
            try:
                res = self.http_client.fetch(r.url, rate_limit=self.rate_limit())
            except Exception as exc:
                self.log.warning("neak.listing_failed", key=r.key, error=str(exc))
                out.append(Resource(key=r.key, url=r.url, resource_type="listing", render_required=render))
                continue
            html = res.content.decode("utf-8", "replace")
            out.append(
                Resource(
                    key=f"{r.key}_index",
                    url=r.url,
                    resource_type="html",
                    filename=f"{r.key}_index.html",
                    render_required=render,
                    meta={"notes": r.notes},
                )
            )
            for link in extract_links(html, r.url, suffixes=(".pdf", ".xlsx", ".xls", ".doc", ".docx")):
                out.append(
                    Resource(
                        key=f"{r.key}_{Path(link).stem[:40]}",
                        url=link,
                        resource_type="document",
                        filename=Path(link).name,
                    )
                )
        return out

    def parse(self, path: Path) -> pd.DataFrame:
        if path.suffix.lower() in {".html", ".htm"}:
            return self._parse_html(path)
        self.log.info("neak.archived_only", file=path.name)
        return pd.DataFrame()

    def _parse_html(self, path: Path) -> pd.DataFrame:
        text = path.read_text(encoding="utf-8", errors="replace")
        candidates: list[dict] = []
        for m in _FT_RE.finditer(text):
            raw = m.group(1).replace(" ", "").replace("\xa0", "")
            if not raw.isdigit():
                continue
            value = int(raw)
            ctx = re.sub(r"\s+", " ", text[max(0, m.start() - 120) : m.end() + 40])
            low = ctx.lower()
            if "súlyszám" in low:
                pid = "hbcs_base_rate"
            elif "német pont" in low or "németpont" in low:
                pid = "outpatient_point_value"
            else:
                continue
            candidates.append(
                {
                    "parameter_id": pid,
                    "value_huf_nominal": value,
                    "context": ctx[:200],
                    "source_url": None,
                    "source_file": path.name,
                    "evidence_class": "observed",
                    "confidence": "medium",
                    "extracted_at": datetime.now(UTC).isoformat(),
                }
            )
        for t in read_tables(path, min_rows=2):
            cols = " ".join(str(c).lower() for c in t.columns)
            if "súlyszám" in cols or "német pont" in cols:
                candidates.append(
                    {"parameter_id": "rate_table", "table_preview": t.head(5).to_dict("records"), "source_file": path.name}
                )
        if candidates:
            CANDIDATES_OUT.parent.mkdir(parents=True, exist_ok=True)
            existing = []
            if CANDIDATES_OUT.exists():
                existing = json.loads(CANDIDATES_OUT.read_text(encoding="utf-8"))
            CANDIDATES_OUT.write_text(
                json.dumps(existing + candidates, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
            )
            self.log.info("neak.cost_candidates", file=path.name, count=len(candidates))
        return pd.DataFrame([c for c in candidates if "value_huf_nominal" in c])

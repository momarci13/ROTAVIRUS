"""Legal-text collector: HBCs / financing decrees, the 290/2014 beneficiary
district list + complex indicator, the 218/2012 district partition, and the
municipal rotavirus vaccination-support decrees that populate
``existing_local_funding`` (scenario 0 / cost-gap baseline).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd

from scraper.collectors.base import Collector, Resource

_AMOUNT_RE = re.compile(r"(\d[\d\s.]{2,})\s*(?:Ft|forint)", re.IGNORECASE)
BENEFICIARY_OUT = Path("data/intermediate/jogtar/kedvezmenyezett_jarasok_290_2014.json")
LOCAL_FUNDING_OUT = Path("data/intermediate/jogtar/municipal_vaccination_support.json")


class JogtarCollector(Collector):
    name = "jogtar"
    source_config_key = "jogtar"

    def discover(self, *, since: date | None = None) -> list[Resource]:
        src = self.source
        out: list[Resource] = []
        for r in src.resources:
            if r.type in {"legal_text", "pdf"} and r.url:
                out.append(
                    Resource(
                        key=r.key,
                        url=r.url,
                        resource_type=r.type,
                        filename=f"{r.key}{'.pdf' if r.type == 'pdf' else '.html'}",
                        meta={"notes": r.notes},
                    )
                )
            if r.type == "legal_text_set":
                for muni, url in (r.items or {}).items():
                    out.append(
                        Resource(
                            key=f"municipal_{muni}",
                            url=url,
                            resource_type="municipal_decree",
                            filename=f"municipal_{muni}.html",
                            meta={"municipality": muni},
                        )
                    )
        return out

    def parse(self, path: Path) -> pd.DataFrame:
        stem = path.stem
        if stem.startswith("municipal_"):
            return self._parse_municipal(path)
        if stem == "korm_290_2014":
            return self._parse_290_2014(path)
        self.log.info("jogtar.archived_only", file=path.name)
        return pd.DataFrame()

    # -- 290/2014: beneficiary districts + complex indicator ---------
    def _parse_290_2014(self, path: Path) -> pd.DataFrame:
        text = _text(path)
        rows: list[dict] = []
        # lines like "Encsi járás 0,834" or "Encsi járás kedvezményezett"
        for line in text.splitlines():
            m = re.match(r"\s*([A-ZÁÉÍÓÖŐÚÜŰ][\wáéíóöőúüű .-]+?járás)\b(.*)$", line)
            if not m:
                continue
            name = m.group(1).strip()
            rest = m.group(2)
            num = re.search(r"(\d+[.,]\d+)", rest)
            rows.append(
                {
                    "district_name": name,
                    "komplex_mutato_2014": float(num.group(1).replace(",", ".")) if num else None,
                    "kedvezmenyezett_status": True,
                    "evidence_class": "observed",
                    "source_id": "jogtar",
                    "source_file": path.name,
                }
            )
        if rows:
            BENEFICIARY_OUT.parent.mkdir(parents=True, exist_ok=True)
            BENEFICIARY_OUT.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
            self.log.info("jogtar.beneficiaries", count=len(rows))
        return pd.DataFrame(rows)

    # -- municipal vaccination-support decrees ----------------------
    def _parse_municipal(self, path: Path) -> pd.DataFrame:
        text = _text(path)
        low = text.lower()
        is_rota = "rotav" in low
        amounts = [
            int(m.group(1).replace(" ", "").replace(".", "").replace("\xa0", ""))
            for m in _AMOUNT_RE.finditer(text)
        ]
        amounts = [a for a in amounts if 1000 <= a <= 200000]
        rec = {
            "municipality_key": path.stem.replace("municipal_", ""),
            "mentions_rotavirus": is_rota,
            "support_amount_huf_candidates": sorted(set(amounts)),
            "support_amount_huf": max(amounts) if amounts else None,
            "evidence_class": "observed",
            "source_id": "jogtar",
            "source_file": path.name,
            "extracted_at": datetime.now(UTC).isoformat(),
        }
        LOCAL_FUNDING_OUT.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if LOCAL_FUNDING_OUT.exists():
            existing = json.loads(LOCAL_FUNDING_OUT.read_text(encoding="utf-8"))
        existing = [e for e in existing if e.get("municipality_key") != rec["municipality_key"]]
        LOCAL_FUNDING_OUT.write_text(
            json.dumps([*existing, rec], indent=2, ensure_ascii=False, default=str), encoding="utf-8"
        )
        self.log.info(
            "jogtar.municipal", municipality=rec["municipality_key"], rotavirus=is_rota, amount=rec["support_amount_huf"]
        )
        return pd.DataFrame([rec]) if is_rota else pd.DataFrame()


def _text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            import pdfplumber

            with pdfplumber.open(str(path)) as pdf:
                return "\n".join(p.extract_text() or "" for p in pdf.pages)
        except Exception:
            return ""
    html = path.read_text(encoding="utf-8", errors="replace")
    try:
        from bs4 import BeautifulSoup

        return BeautifulSoup(html, "lxml").get_text("\n")
    except Exception:
        return re.sub(r"<[^>]+>", " ", html)

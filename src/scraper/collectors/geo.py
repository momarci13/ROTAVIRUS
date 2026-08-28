"""Geometry collector: OSM district (admin=7j) and settlement (admin=8)
boundaries, plus Eurostat GISCO NUTS3. The paid Lechner layer is opt-in via
``config/sources.yaml :: sources.geo.boundary_provider``.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from scraper.collectors.base import Collector, Resource


class GeoCollector(Collector):
    name = "geo"
    source_config_key = "geo"

    def discover(self, *, since: date | None = None) -> list[Resource]:
        src = self.source
        provider = (src.model_extra or {}).get("boundary_provider", "osm")
        out: list[Resource] = []
        if provider == "lechner":
            r = src.resource("lechner_boundaries")
            out.append(Resource(key="lechner", url=r.url or "", resource_type="manual", manual=True,
                                meta={"notes": r.notes}))
            return out
        for key in ("osm_districts", "osm_settlements"):
            r = src.resource(key)
            out.append(
                Resource(
                    key=key,
                    url=r.url,
                    resource_type="geojson",
                    filename=f"{key}.geojson",
                    meta={"notes": r.notes},
                )
            )
        return out

    def parse(self, path: Path) -> pd.DataFrame:
        if path.suffix.lower() not in {".geojson", ".json"}:
            self.log.info("geo.archived_only", file=path.name)
            return pd.DataFrame()
        try:
            gj = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception as exc:
            self.log.warning("geo.parse_failed", file=path.name, error=str(exc))
            return pd.DataFrame()
        feats = gj.get("features", []) if isinstance(gj, dict) else []
        rows = [
            {
                "layer": path.stem,
                "name": (f.get("properties") or {}).get("name"),
                "osm_id": (f.get("properties") or {}).get("osm_id") or (f.get("properties") or {}).get("@id"),
                "geometry_type": (f.get("geometry") or {}).get("type"),
                "source_id": "geo",
                "source_file": path.name,
            }
            for f in feats
        ]
        self.log.info("geo.parsed", file=path.name, features=len(rows))
        # persist the geometry file location for the spatial modules
        (self.intermediate_dir / f"{path.stem}__path.txt").write_text(str(path), encoding="utf-8")
        return pd.DataFrame(rows)

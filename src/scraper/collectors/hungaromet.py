"""HungaroMet collector: daily / monthly station observations + station
metadata from the ODP open-data portal. Station series are aggregated to
districts (area weighting) in processing/."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from scraper.collectors._discovery import walk_dir_index
from scraper.collectors.base import Collector, Resource
from scraper.parsers.excel import read_any_table


class HungaroMetCollector(Collector):
    name = "hungaromet"
    source_config_key = "hungaromet"

    # subdirs relevant to the panel's monthly environment block
    SUBDIRS = ("meta/", "monthly/", "daily/")

    def discover(self, *, since: date | None = None) -> list[Resource]:
        root = self.source.resource("climate_observations").url
        out: list[Resource] = []
        for sub in self.SUBDIRS:
            try:
                files = walk_dir_index(
                    self.http_client,
                    root + sub,
                    suffixes=(".csv", ".zip", ".txt"),
                    max_depth=2,
                    rate_limit=self.rate_limit(),
                )
            except Exception as exc:
                self.log.warning("hungaromet.walk_failed", sub=sub, error=str(exc))
                continue
            for f in files:
                out.append(
                    Resource(
                        key=f"{sub.strip('/')}_{Path(f).name}",
                        url=f,
                        resource_type=f"odp_{sub.strip('/')}",
                        filename=f"{sub.strip('/')}__{Path(f).name}",
                    )
                )
        if not out:
            self.log.warning("hungaromet.nothing_discovered", root=root)
        return out

    def parse(self, path: Path) -> pd.DataFrame:
        if "meta" in path.name.lower() and path.suffix.lower() in {".csv", ".txt"}:
            try:
                meta = read_any_table(path, header=0)
                meta.columns = [str(c).strip().lower() for c in meta.columns]
                meta["source_id"] = "hungaromet"
                meta["source_file"] = path.name
                meta["record_kind"] = "station_meta"
                return meta
            except Exception as exc:
                self.log.warning("hungaromet.meta_parse_failed", file=path.name, error=str(exc))
                return pd.DataFrame()
        # Observation archives are large and station-keyed; they are archived raw
        # and consumed lazily by processing/ rather than concatenated here.
        self.log.info("hungaromet.archived_only", file=path.name)
        return pd.DataFrame()

"""Abstract collector contract.

Lifecycle (``Collector.run``):
    discover() -> [Resource]           enumerate what to download
    fetch(resource) -> Path            download to data/raw/<source>/ UNCHANGED
    parse(path) -> DataFrame           raw -> intermediate (no harmonisation)
    validate(df) -> ValidationReport   pandera schema + source-specific checks

``discover`` must parse a listing / directory index where one exists and only
fall back to URL patterns when there is none.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scraper import INTERMEDIATE_DIR, RAW_DIR
from scraper.core.cache import ContentCache, sha256_bytes
from scraper.core.config import Config
from scraper.core.errors import BrokenLinkError, CollectorError
from scraper.core.http import HTTPClient
from scraper.core.logging_setup import get_logger
from scraper.core.registry import RegistryRecord, SourceRegistry


@dataclass(slots=True)
class Resource:
    """One downloadable thing."""

    key: str
    url: str
    resource_type: str = "raw"
    filename: str | None = None
    period: date | None = None
    year: int | None = None
    week: int | None = None
    render_required: bool = False
    manual: bool = False
    #: fallback URLs tried on 404 before the resource is declared broken
    alt_urls: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    def target_name(self) -> str:
        if self.filename:
            return self.filename
        tail = self.url.split("/")[-1].split("?")[0] or f"{self.key}.bin"
        return tail


@dataclass(slots=True)
class ValidationReport:
    ok: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    rows: int = 0

    def error(self, msg: str) -> None:
        self.ok = False
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)


@dataclass(slots=True)
class CollectorReport:
    name: str
    discovered: int = 0
    fetched: int = 0
    from_cache: int = 0
    parsed_tables: int = 0
    broken_links: list[str] = field(default_factory=list)
    manual_required: list[str] = field(default_factory=list)
    render_required: list[str] = field(default_factory=list)
    quarantined: list[str] = field(default_factory=list)
    schema_drift: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    resource_hashes: list[dict] = field(default_factory=list)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    finished_at: str | None = None

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "discovered": self.discovered,
            "fetched": self.fetched,
            "from_cache": self.from_cache,
            "parsed_tables": self.parsed_tables,
            "broken_links": self.broken_links,
            "manual_required": self.manual_required,
            "render_required": self.render_required,
            "quarantined": self.quarantined,
            "schema_drift": self.schema_drift,
            "errors": self.errors,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


class Collector(ABC):
    #: name used in logs, registry records and CLI (``--source <name>``)
    name: str = "base"
    #: key into config/sources.yaml :: sources
    source_config_key: str = "base"

    def __init__(
        self,
        config: Config,
        http: HTTPClient | None = None,
        *,
        registry: SourceRegistry | None = None,
        cache: ContentCache | None = None,
        render: bool = False,
    ) -> None:
        self.config = config
        self.http = http
        # NB: an empty SourceRegistry is falsy (len 0) -> use an identity check
        self.registry = registry if registry is not None else SourceRegistry()
        self.cache = cache if cache is not None else ContentCache()
        self.render = render
        self.log = get_logger(f"scraper.collector.{self.name}")
        self.report = CollectorReport(name=self.name)

    # -- config helpers -------------------------------------------------
    @property
    def source(self):
        return self.config.sources.get(self.source_config_key)

    @property
    def http_client(self) -> HTTPClient:
        """The HTTP client, guaranteed non-None (raises otherwise). Use in
        discover()/fetch() paths that genuinely need the network."""
        if self.http is None:
            raise CollectorError(f"{self.name}: an HTTP client is required for this operation")
        return self.http

    @property
    def raw_dir(self) -> Path:
        d = RAW_DIR / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def intermediate_dir(self) -> Path:
        d = INTERMEDIATE_DIR / self.name
        d.mkdir(parents=True, exist_ok=True)
        return d

    def rate_limit(self) -> float:
        return self.config.sources.rate_limit(self.source_config_key)

    # -- abstract -----------------------------------------------------------
    @abstractmethod
    def discover(self, *, since: date | None = None) -> list[Resource]:
        ...

    @abstractmethod
    def parse(self, path: Path) -> pd.DataFrame:
        ...

    # -- default fetch ----------------------------------------------------
    def fetch(self, resource: Resource, *, force: bool = False) -> Path | None:
        """Download ``resource`` to the raw store unchanged; register metadata.

        Returns the local path, or ``None`` if the resource is unavailable
        (broken link, needs render, or needs a manual export) — the run
        continues in every such case (spec 17).
        """
        if resource.manual:
            self.report.manual_required.append(resource.url or resource.key)
            self.log.warning("fetch.manual_required", resource=resource.key)
            return None
        if resource.render_required and not self.render:
            self.report.render_required.append(resource.url or resource.key)
            self.log.warning(
                "fetch.render_required",
                resource=resource.key,
                hint="re-run with --render (playwright) or place a manual export",
            )
            return None
        dest = self.raw_dir / resource.target_name()

        # cache hit: an unchanged, already-registered file needs no network
        if dest.exists() and not force:
            digest = sha256_bytes(dest.read_bytes())
            if self.registry.has_url_with_hash(resource.url, digest):
                self.report.from_cache += 1
                self.log.info("fetch.cache_hit", resource=resource.key, path=str(dest))
                self.report.resource_hashes.append({"url": resource.url, "sha256": digest})
                return dest

        if self.http is None:
            raise CollectorError("HTTPClient not provided to collector")

        urls_to_try = [resource.url, *resource.alt_urls]
        res = None
        used_url = resource.url
        for i, url in enumerate(urls_to_try):
            try:
                res = self.http.download_to(url, dest, rate_limit=self.rate_limit())
                used_url = url
                break
            except BrokenLinkError:
                if i + 1 < len(urls_to_try):
                    self.log.info("fetch.alt_url", resource=resource.key, tried=url)
                    continue
                self.report.broken_links.append(url if not resource.alt_urls else resource.url)
                return None
        if res is None:  # pragma: no cover - defensive
            self.report.broken_links.append(resource.url)
            return None

        digest = sha256_bytes(res.content)
        self.registry.add(
            RegistryRecord(
                url=used_url,
                local_path=str(dest),
                sha256=digest,
                bytes=len(res.content),
                collector=self.name,
                resource_type=resource.resource_type,
                http_status=res.status_code,
                etag=res.etag,
                last_modified=res.last_modified,
                from_cache=res.from_cache,
                notes=resource.meta.get("notes"),
            )
        )
        self.report.fetched += 1
        self.report.resource_hashes.append({"url": resource.url, "sha256": digest})
        return dest

    # -- default validate (subclasses extend) -----------------------------
    def validate(self, df: pd.DataFrame) -> ValidationReport:
        rep = ValidationReport(rows=len(df))
        if df.empty:
            rep.warn("parsed frame is empty")
        return rep

    # -- orchestration --------------------------------------------------
    def run(self, *, force: bool = False, since: date | None = None, dry_run: bool = False) -> CollectorReport:
        self.log.info("collector.start", force=force, since=str(since), dry_run=dry_run)
        try:
            resources = self.discover(since=since)
        except BrokenLinkError as exc:
            self.report.broken_links.append(str(exc))
            resources = []
        self.report.discovered = len(resources)
        self.log.info("collector.discovered", count=len(resources))

        if dry_run:
            for r in resources:
                self.log.info("collector.dry_run.resource", key=r.key, url=r.url)
            self.report.finished_at = datetime.now(UTC).isoformat()
            return self.report

        frames: list[pd.DataFrame] = []
        for resource in resources:
            try:
                path = self.fetch(resource, force=force)
            except CollectorError as exc:
                self.report.errors.append(f"{resource.key}: {exc}")
                self.log.error("fetch.error", resource=resource.key, error=str(exc))
                continue
            if path is None:
                continue
            try:
                df = self.parse(path)
            except Exception as exc:
                self.report.errors.append(f"parse {path.name}: {exc}")
                self.log.error("parse.error", path=str(path), error=str(exc))
                continue
            if df is not None and not df.empty:
                frames.append(df)

        if frames:
            combined = pd.concat(frames, ignore_index=True)
            out = self.intermediate_dir / f"{self.name}.parquet"
            combined.to_parquet(out, index=False)
            self.report.parsed_tables += 1
            rep = self.validate(combined)
            if not rep.ok:
                for err in rep.errors:
                    self.report.errors.append(err)

        self.registry.save()
        self.report.finished_at = datetime.now(UTC).isoformat()
        self.log.info("collector.done", **self.report.as_dict())
        return self.report

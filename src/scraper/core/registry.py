"""Read/write ``data/metadata/source_registry.json``.

One record per downloaded file: url, local_path, sha256, bytes, downloaded_at,
http_status, etag, last_modified, collector, resource_type, notes. The registry
is version-controlled so raw files can be re-fetched and integrity-checked any
time, even though ``data/raw/`` itself is git-ignored.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from scraper import METADATA_DIR, REPO_ROOT

REGISTRY_PATH = METADATA_DIR / "source_registry.json"


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class RegistryRecord:
    url: str
    local_path: str
    sha256: str
    bytes: int
    collector: str
    resource_type: str = "raw"
    downloaded_at: str = field(default_factory=_utcnow)
    http_status: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    from_cache: bool = False
    notes: str | None = None

    @property
    def key(self) -> str:
        return f"{self.url}::{self.sha256}"


class SourceRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else REGISTRY_PATH
        self._records: dict[str, dict] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
            self._records = {r["url"] + "::" + r["sha256"]: r for r in raw.get("records", [])}
        else:
            self._records = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": 1,
            "updated_at": _utcnow(),
            "records": sorted(self._records.values(), key=lambda r: (r["collector"], r["url"])),
        }
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    def add(self, record: RegistryRecord) -> None:
        d = asdict(record)
        # store paths relative to the repo root for portability
        try:
            d["local_path"] = str(Path(record.local_path).resolve().relative_to(REPO_ROOT))
        except ValueError:
            d["local_path"] = record.local_path
        self._records[record.key] = d

    def has_url_with_hash(self, url: str, sha256: str) -> bool:
        return f"{url}::{sha256}" in self._records

    def latest_for_url(self, url: str) -> dict | None:
        matches = [r for r in self._records.values() if r["url"] == url]
        if not matches:
            return None
        return max(matches, key=lambda r: r["downloaded_at"])

    def known_etag(self, url: str) -> str | None:
        rec = self.latest_for_url(url)
        return rec.get("etag") if rec else None

    def records(self) -> list[dict]:
        return list(self._records.values())

    def __len__(self) -> int:
        return len(self._records)

"""Content-addressed cache for downloaded raw files.

Downloads are keyed by URL; the stored payload is verified by SHA-256. A resource
whose bytes are unchanged (matching sha256, or a matching ETag / Last-Modified
recorded in the registry) is not re-downloaded unless ``force=True``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from scraper import REPO_ROOT

CACHE_ROOT = REPO_ROOT / ".cache"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(slots=True)
class CacheEntry:
    url: str
    path: Path
    sha256: str
    bytes: int
    from_cache: bool


class ContentCache:
    """Filesystem cache under ``.cache/blobs`` addressed by content hash."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root else CACHE_ROOT
        self.blobs = self.root / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)

    def blob_path(self, digest: str) -> Path:
        return self.blobs / digest[:2] / digest

    def has(self, digest: str) -> bool:
        return self.blob_path(digest).exists()

    def put(self, data: bytes) -> str:
        digest = sha256_bytes(data)
        target = self.blob_path(digest)
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return digest

    def get(self, digest: str) -> bytes:
        return self.blob_path(digest).read_bytes()

    def materialise(self, digest: str, dest: Path) -> Path:
        """Copy a cached blob to a destination path (raw store)."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.get(digest))
        return dest

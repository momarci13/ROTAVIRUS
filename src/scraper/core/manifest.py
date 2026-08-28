"""Per-run reproducibility manifest -> ``data/metadata/run_manifest/<ts>.json``.

Records: git commit hash, ``git diff --stat`` when the tree is dirty, the SHA-256
of every config file used, ``pip freeze``, Python + OS version, the exact CLI
command, and the list of processed resources with their SHA-256.
"""

from __future__ import annotations

import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from scraper import METADATA_DIR, REPO_ROOT

MANIFEST_DIR = METADATA_DIR / "run_manifest"


def _git(*args: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return None


def _pip_freeze() -> list[str]:
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        return [ln for ln in out.stdout.splitlines() if ln.strip()]
    except (OSError, subprocess.SubprocessError):  # pragma: no cover
        return []


def write_manifest(
    *,
    command: str,
    config_hashes: dict[str, str],
    resources: list[dict] | None = None,
    extra: dict | None = None,
) -> Path:
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    commit = _git("rev-parse", "HEAD")
    status = _git("status", "--porcelain")
    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "command": command,
        "git": {
            "commit": commit,
            "dirty": bool(status),
            "diff_stat": _git("diff", "--stat") if status else None,
        },
        "python": {
            "version": sys.version,
            "executable": sys.executable,
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "config_hashes": config_hashes,
        "pip_freeze": _pip_freeze(),
        "resources": resources or [],
    }
    if extra:
        manifest["extra"] = extra

    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    path = MANIFEST_DIR / f"{ts}.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return path

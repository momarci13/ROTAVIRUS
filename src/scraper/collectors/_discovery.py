"""Shared discovery helpers: HTML link extraction, Apache-style directory
index walking, and URL-pattern expansion. Kept separate so every collector
discovers the same way.
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin, urlparse

from scraper.core.http import HTTPClient
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.discovery")

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"'#]+)["']""", re.IGNORECASE)


def extract_links(html: str, base_url: str, *, suffixes: tuple[str, ...] = ()) -> list[str]:
    """Return absolute links found in ``html``, optionally filtered by suffix."""
    out: list[str] = []
    seen: set[str] = set()
    for m in _HREF_RE.finditer(html):
        raw = m.group(1).strip()
        if raw.startswith(("mailto:", "javascript:", "tel:")):
            continue
        absolute = urljoin(base_url, raw)
        if suffixes and not absolute.lower().split("?")[0].endswith(suffixes):
            continue
        if absolute not in seen:
            seen.add(absolute)
            out.append(absolute)
    return out


def walk_dir_index(
    http: HTTPClient,
    root_url: str,
    *,
    suffixes: tuple[str, ...],
    max_depth: int = 3,
    rate_limit: float | None = None,
) -> list[str]:
    """Recursively walk an Apache/nginx autoindex, collecting file URLs."""
    found: list[str] = []
    queue: list[tuple[str, int]] = [(root_url, 0)]
    visited: set[str] = set()
    root_netloc = urlparse(root_url).netloc

    while queue:
        url, depth = queue.pop(0)
        if url in visited or depth > max_depth:
            continue
        visited.add(url)
        try:
            res = http.fetch(url, rate_limit=rate_limit)
        except Exception as exc:
            log.warning("discovery.dir_index.error", url=url, error=str(exc))
            continue
        html = res.content.decode("utf-8", errors="replace")
        for link in extract_links(html, url):
            if urlparse(link).netloc != root_netloc:
                continue
            if not link.startswith(root_url):
                continue
            low = link.lower().split("?")[0]
            if low.endswith(suffixes):
                if link not in found:
                    found.append(link)
            elif link.endswith("/") and link not in visited:
                queue.append((link, depth + 1))
    return found


def iso_weeks_since(start: date | None, *, until: date | None = None) -> list[tuple[int, int]]:
    """List of (iso_year, iso_week) from ``start`` to ``until`` (inclusive)."""
    from datetime import date as _date
    from datetime import timedelta

    until = until or _date.today()
    start = start or _date(2014, 1, 1)
    out: list[tuple[int, int]] = []
    cur = start - timedelta(days=start.weekday())
    while cur <= until:
        iso = cur.isocalendar()
        out.append((iso.year, iso.week))
        cur += timedelta(days=7)
    return out


def expand_pattern(pattern: str, **kwargs) -> str:
    """Fill a URL pattern like ``.../{year}/...{week:02d}...``."""
    return pattern.format(**kwargs)

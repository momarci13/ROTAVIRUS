"""HTTP layer: a shared ``requests.Session`` with a persistent HTTP cache,
polite rate limiting, a contact User-Agent, and tenacity-based retries.

Retry policy (spec 7.1): exponential backoff with jitter, max 5 attempts, retry
on 429 / 5xx and connection errors, do NOT retry other 4xx. 404 is not retried
but is logged distinctly and surfaced as :class:`BrokenLinkError`.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import requests
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from scraper import REPO_ROOT
from scraper.core.errors import BrokenLinkError, DownloadError
from scraper.core.logging_setup import get_logger

log = get_logger("scraper.http")

DEFAULT_TIMEOUT = 60
CACHE_DB = REPO_ROOT / ".cache" / "http_cache"


class RetryableHTTP(Exception):
    """Internal marker: this response/exception is worth retrying."""


@dataclass(slots=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    headers: dict[str, str]
    from_cache: bool
    elapsed_s: float

    @property
    def etag(self) -> str | None:
        return self.headers.get("ETag")

    @property
    def last_modified(self) -> str | None:
        return self.headers.get("Last-Modified")


class _RateLimiter:
    """Per-host minimum delay between requests."""

    def __init__(self) -> None:
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, host: str, min_interval: float) -> None:
        with self._lock:
            now = time.monotonic()
            last = self._last.get(host, 0.0)
            delta = now - last
            if delta < min_interval:
                time.sleep(min_interval - delta)
            self._last[host] = time.monotonic()


def _build_session(user_agent: str, use_cache: bool) -> requests.Session:
    session: requests.Session
    if use_cache:
        try:
            import requests_cache

            CACHE_DB.parent.mkdir(parents=True, exist_ok=True)
            session = requests_cache.CachedSession(
                cache_name=str(CACHE_DB),
                backend="sqlite",
                cache_control=True,
                expire_after=requests_cache.NEVER_EXPIRE,
                allowable_codes=(200,),
                stale_if_error=True,
            )
        except Exception:  # pragma: no cover - fallback when requests_cache missing
            log.warning("requests_cache unavailable; using uncached session")
            session = requests.Session()
    else:
        session = requests.Session()
    session.headers.update({"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"})
    for var in ("HTTP_PROXY", "HTTPS_PROXY"):
        val = os.environ.get(var)
        if val:
            session.proxies[var.split("_")[0].lower()] = val
    return session


def _log_retry(state: RetryCallState) -> None:
    log.warning(
        "http.retry",
        attempt=state.attempt_number,
        wait=getattr(state.next_action, "sleep", None),
        exc=repr(state.outcome.exception()) if state.outcome else None,
    )


class HTTPClient:
    """Thin wrapper the collectors use. One instance per pipeline run."""

    def __init__(
        self,
        *,
        user_agent: str,
        use_cache: bool = True,
        default_rate_limit: float = 1.0,
        max_retries: int = 5,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.user_agent = user_agent
        self.use_cache = use_cache
        self.default_rate_limit = default_rate_limit
        self.max_retries = max_retries
        self.timeout = timeout
        self.session = _build_session(user_agent, use_cache)
        self._limiter = _RateLimiter()

    # -- low level --------------------------------------------------------
    def _do_request(self, method: str, url: str, **kw) -> requests.Response:
        resp = self.session.request(method, url, timeout=self.timeout, **kw)
        if resp.status_code == 404:
            # not retried, but raised as a distinct type by the caller
            return resp
        if resp.status_code == 429 or 500 <= resp.status_code < 600:
            raise RetryableHTTP(f"{resp.status_code} for {url}")
        return resp

    def fetch(
        self,
        url: str,
        *,
        method: str = "GET",
        rate_limit: float | None = None,
        allow_404: bool = False,
        **kw,
    ) -> FetchResult:
        """Fetch a URL with retry + rate limiting. Raises on unrecoverable errors."""
        host = urlparse(url).netloc
        interval = self.default_rate_limit if rate_limit is None else rate_limit

        _retrying = retry(
            reraise=True,
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential_jitter(initial=1, max=60),
            retry=retry_if_exception_type((RetryableHTTP, requests.ConnectionError, requests.Timeout)),
            before_sleep=_log_retry,
        )

        @_retrying
        def _call() -> requests.Response:
            self._limiter.wait(host, interval)
            return self._do_request(method, url, **kw)

        started = time.monotonic()
        try:
            resp = _call()
        except RetryableHTTP as exc:
            raise DownloadError(f"Giving up on {url}: {exc}") from exc
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise DownloadError(f"Network error for {url}: {exc}") from exc
        elapsed = time.monotonic() - started

        from_cache = bool(getattr(resp, "from_cache", False))
        if resp.status_code == 404:
            log.error("http.404", url=url)
            if allow_404:
                return FetchResult(url, 404, b"", dict(resp.headers), from_cache, elapsed)
            raise BrokenLinkError(f"404 Not Found: {url}")
        if not resp.ok:
            raise DownloadError(f"HTTP {resp.status_code} for {url}")

        result = FetchResult(
            url=url,
            status_code=resp.status_code,
            content=resp.content,
            headers=dict(resp.headers),
            from_cache=from_cache,
            elapsed_s=elapsed,
        )
        log.info(
            "http.fetch",
            url=url,
            status=resp.status_code,
            bytes=len(result.content),
            cache_hit=from_cache,
            elapsed_s=round(elapsed, 3),
        )
        return result

    def download_to(
        self,
        url: str,
        dest: Path,
        *,
        rate_limit: float | None = None,
        **kw,
    ) -> FetchResult:
        """Fetch and write bytes to ``dest`` unchanged."""
        res = self.fetch(url, rate_limit=rate_limit, **kw)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(res.content)
        return res

    def close(self) -> None:
        self.session.close()

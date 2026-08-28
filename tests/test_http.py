"""HTTP core: retry policy and cache behaviour (spec §13)."""

from __future__ import annotations

import pytest
import responses

from scraper.core.errors import BrokenLinkError, DownloadError
from scraper.core.http import HTTPClient

UA = "rotavirus-research-pipeline/0.1 (+mailto:test@example.org)"


@pytest.fixture
def client():
    # no persistent cache in tests; fast retry waits
    c = HTTPClient(user_agent=UA, use_cache=False, default_rate_limit=0.0, max_retries=3, timeout=5)
    yield c
    c.close()


@responses.activate
def test_retries_on_500_then_succeeds(client):
    url = "https://example.org/flaky"
    responses.add(responses.GET, url, status=500)
    responses.add(responses.GET, url, status=500)
    responses.add(responses.GET, url, body=b"ok", status=200)

    res = client.fetch(url)
    assert res.status_code == 200
    assert res.content == b"ok"
    assert len(responses.calls) == 3


@responses.activate
def test_retries_on_429(client):
    url = "https://example.org/rate-limited"
    responses.add(responses.GET, url, status=429)
    responses.add(responses.GET, url, body=b"done", status=200)

    res = client.fetch(url)
    assert res.status_code == 200
    assert len(responses.calls) == 2


@responses.activate
def test_gives_up_after_max_retries(client):
    url = "https://example.org/always-500"
    for _ in range(5):
        responses.add(responses.GET, url, status=503)
    with pytest.raises(DownloadError):
        client.fetch(url)
    assert len(responses.calls) == 3  # max_retries


@responses.activate
def test_does_not_retry_on_400(client):
    url = "https://example.org/bad-request"
    responses.add(responses.GET, url, status=400)
    with pytest.raises(DownloadError):
        client.fetch(url)
    assert len(responses.calls) == 1  # 4xx (non-404) not retried


@responses.activate
def test_404_raises_broken_link_and_is_not_retried(client):
    url = "https://example.org/missing"
    responses.add(responses.GET, url, status=404)
    with pytest.raises(BrokenLinkError):
        client.fetch(url)
    assert len(responses.calls) == 1


@responses.activate
def test_404_allowed_returns_result(client):
    url = "https://example.org/maybe"
    responses.add(responses.GET, url, status=404)
    res = client.fetch(url, allow_404=True)
    assert res.status_code == 404
    assert res.content == b""


@responses.activate
def test_user_agent_header_sent(client):
    url = "https://example.org/echo"
    responses.add(responses.GET, url, body=b"x", status=200)
    client.fetch(url)
    assert responses.calls[0].request.headers["User-Agent"] == UA


def test_cache_hit_skips_network(tmp_path):
    """A cached (unchanged) resource is not re-downloaded: the base Collector
    checks the registry sha256 before calling HTTP."""
    from scraper.collectors.base import Collector, Resource
    from scraper.core.config import load_config
    from scraper.core.registry import RegistryRecord, SourceRegistry

    class _Dummy(Collector):
        name = "dummy"
        source_config_key = "nngyk"

        def discover(self, *, since=None):
            return []

        def parse(self, path):
            import pandas as pd

            return pd.DataFrame()

    reg = SourceRegistry(tmp_path / "registry.json")
    coll = _Dummy(load_config(), http=None, registry=reg)

    dest = coll.raw_dir / "cached.bin"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"payload")
    from scraper.core.cache import sha256_bytes

    digest = sha256_bytes(b"payload")
    reg.add(
        RegistryRecord(
            url="https://example.org/cached.bin",
            local_path=str(dest),
            sha256=digest,
            bytes=7,
            collector="dummy",
        )
    )

    # http is None -> if fetch tried the network it would raise; instead cache hits
    out = coll.fetch(Resource(key="c", url="https://example.org/cached.bin", filename="cached.bin"))
    assert out == dest
    assert coll.report.from_cache == 1

"""Adversarial-hardening tests: malformed/empty upstream input must degrade,
not crash.

Feeds are fetched live over flaky HTTP. A source can return an HTML error page,
a truncated body, or empty bytes; an article can carry a None body. None of
these should raise — the fetcher yields no articles and the analyser proceeds.
"""

from __future__ import annotations

import pytest

from situation_monitor.ingestion.crypto import CryptoRSSFetcher
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.models import Article
from situation_monitor.propaganda import enrich_article, flag_article


class _StubClient:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def get(self, url: str) -> bytes:
        return self._payload


@pytest.mark.parametrize(
    "payload",
    [b"", b"<html>503 Service Unavailable</html>", b"<rss><channel><item", b"not xml at all"],
)
def test_rss_fetcher_survives_malformed_xml(payload: bytes) -> None:
    fetcher = RSSFetcher(client=_StubClient(payload))
    assert fetcher.fetch("http://feed.example/rss") == []


@pytest.mark.parametrize("payload", [b"", b"<html>404</html>", b"<rss><channel"])
def test_crypto_fetcher_survives_malformed_xml(payload: bytes) -> None:
    fetcher = CryptoRSSFetcher(client=_StubClient(payload))
    assert fetcher.fetch("http://crypto.example/rss") == []


def test_propaganda_handles_none_body() -> None:
    art = Article(url="http://x", title="T", source="s")
    art.body = None  # upstream may leave body unset/None
    # Neither call should raise on a None body.
    assert flag_article(art, lambda _prompt: '{"flags": []}') == []
    enrich_article(art, lambda _prompt: '{"flags": [], "loaded_language": false}')

"""Adversarial-hardening tests: malformed/empty upstream input must degrade,
not crash.

Feeds are fetched live over flaky HTTP. A source can return an HTML error page,
a truncated body, or empty bytes; an article can carry a None body. None of
these should raise — the fetcher yields no articles and the analyser proceeds.
"""

from __future__ import annotations

import json

import pytest

from situation_monitor.ingestion.bluesky import BlueskyFetcher
from situation_monitor.ingestion.crypto import CryptoRSSFetcher
from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.ingestion.mastodon import MastodonFetcher
from situation_monitor.ingestion.reddit import RedditScraper
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.models import Article
from situation_monitor.polymarket import PolymarketMatcher
from situation_monitor.practical import _parse_rss_items
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


def test_polymarket_matcher_handles_none_body() -> None:
    # A body-less article must still match on its title, not crash with
    # "can only concatenate str (not NoneType) to str".
    art = Article(url="http://x", title="Trump wins the election", source="s")
    art.body = None
    odds = PolymarketMatcher().match(art, [{"keywords": ["election"], "odds": 0.6}])
    assert odds == 0.6


def test_polymarket_matcher_skips_market_with_missing_odds() -> None:
    # A malformed market record (no "odds", or non-numeric) must be skipped,
    # not raise — a later well-formed match should still win.
    art = Article(url="http://x", title="Fed cuts rates", source="s", body="rate news")
    markets = [
        {"keywords": ["rates"]},                       # missing "odds" → KeyError
        {"keywords": ["rates"], "odds": "not-a-number"},  # bad value → ValueError
        {"keywords": ["rates"], "odds": 0.42},          # good → wins
    ]
    assert PolymarketMatcher().match(art, markets) == 0.42


def test_polymarket_matcher_all_markets_malformed_returns_none() -> None:
    art = Article(url="http://x", title="Fed cuts rates", source="s", body=None)
    assert PolymarketMatcher().match(art, [{"keywords": ["rates"]}]) is None


# ---------------------------------------------------------------------------
# HNFetcher — three crash paths: empty bytes, HTML error page, truncated JSON
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"<html><body><p>503 Service Unavailable</p></body></html>",
        b'{"hits": [{"title": "truncated article without closing',
    ],
    ids=["empty", "html_error_page", "truncated_json"],
)
def test_hn_fetcher_survives_malformed_payload(payload: bytes) -> None:
    fetcher = HNFetcher(client=_StubClient(payload))
    result = fetcher.fetch("http://api.example/hn")
    assert result == []


def test_hn_fetcher_survives_null_bytes() -> None:
    fetcher = HNFetcher(client=_StubClient(b"\x00\x01\x02"))
    assert fetcher.fetch("http://api.example/hn") == []


def test_hn_fetcher_survives_json_object_missing_hits() -> None:
    fetcher = HNFetcher(client=_StubClient(b"{}"))
    assert fetcher.fetch("http://api.example/hn") == []


def test_hn_fetcher_survives_json_with_empty_hits_list() -> None:
    fetcher = HNFetcher(client=_StubClient(b'{"hits": []}'))
    assert fetcher.fetch("http://api.example/hn") == []


@pytest.mark.parametrize(
    "payload",
    [b"[]", b"[1, 2, 3]", b"42", b'"a string"', b"null"],
    ids=["empty_list", "list", "int", "string", "null"],
)
def test_hn_fetcher_survives_non_dict_toplevel_json(payload: bytes) -> None:
    # A hostile API may return a valid-but-non-dict top-level JSON value;
    # data.get(...) would raise AttributeError and crash the fetch.
    fetcher = HNFetcher(client=_StubClient(payload))
    assert fetcher.fetch("http://api.example/hn") == []


@pytest.mark.parametrize(
    "payload",
    [b"[]", b"[1, 2, 3]", b"42", b'"a string"', b"null"],
    ids=["empty_list", "list", "int", "string", "null"],
)
def test_bluesky_fetcher_survives_non_dict_toplevel_json(payload: bytes) -> None:
    fetcher = BlueskyFetcher("handle.bsky.social", client=_StubClient(payload))
    assert fetcher.fetch() == []


# ---------------------------------------------------------------------------
# MastodonFetcher — three crash paths: empty bytes, HTML error page, truncated XML
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"<html><body><p>503 Service Unavailable</p></body></html>",
        b"<rss><channel><item><title>truncated without close",
    ],
    ids=["empty", "html_error_page", "truncated_xml"],
)
def test_mastodon_fetcher_survives_malformed_payload(payload: bytes) -> None:
    fetcher = MastodonFetcher("user@mastodon.social", client=_StubClient(payload))
    result = fetcher.fetch()
    assert result == []


def test_mastodon_fetcher_survives_valid_xml_without_channel() -> None:
    payload = b"<?xml version='1.0'?><root><data>no channel here</data></root>"
    fetcher = MastodonFetcher("user@mastodon.social", client=_StubClient(payload))
    assert fetcher.fetch() == []


def test_mastodon_fetcher_survives_json_instead_of_xml() -> None:
    payload = b'{"error": "account not found"}'
    fetcher = MastodonFetcher("ghost@mastodon.social", client=_StubClient(payload))
    assert fetcher.fetch() == []


# ---------------------------------------------------------------------------
# _parse_rss_items — three crash paths: empty bytes, HTML error page, truncated XML
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"<html><body><p>503 Service Unavailable</p></body></html>",
        b"<rss><channel><item><title>cut off without closing tags",
    ],
    ids=["empty", "html_error_page", "truncated_xml"],
)
def test_parse_rss_items_survives_malformed_payload(payload: bytes) -> None:
    result = _parse_rss_items(payload)
    assert result == []


def test_parse_rss_items_survives_not_xml_at_all() -> None:
    assert _parse_rss_items(b"not xml at all") == []


def test_parse_rss_items_survives_binary_garbage() -> None:
    assert _parse_rss_items(b"\xff\xfe\x00\x01binary") == []


def test_parse_rss_items_channel_with_items_missing_title_all_skipped() -> None:
    payload = b"""<rss version="2.0"><channel>
      <item><link>http://x.com/1</link></item>
      <item><link>http://x.com/2</link></item>
    </channel></rss>"""
    assert _parse_rss_items(payload) == []


def test_parse_rss_items_channel_with_items_missing_link_all_skipped() -> None:
    payload = b"""<rss version="2.0"><channel>
      <item><title>No Link</title></item>
    </channel></rss>"""
    assert _parse_rss_items(payload) == []


# ---------------------------------------------------------------------------
# Hostile timestamps — a feed-supplied created/indexed field may be infinite,
# out-of-range, or a non-numeric/non-string type. The fetcher must drop the
# timestamp, not crash on OverflowError / TypeError / AttributeError.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("created_utc", [1e999, [1, 2], {"x": 1}, "not-a-number"])
def test_reddit_scraper_survives_hostile_created_utc(created_utc: object) -> None:
    payload = json.dumps(
        {"data": {"children": [{"data": {"title": "T", "url": "http://x", "created_utc": created_utc}}]}}
    ).encode()
    arts = RedditScraper(client=_StubClient(payload)).fetch("news")
    assert len(arts) == 1
    assert arts[0].published_at is None


@pytest.mark.parametrize("created_at", [12345, [1, 2], {"x": 1}, "garbage"])
def test_hn_fetcher_survives_hostile_created_at(created_at: object) -> None:
    payload = json.dumps(
        {"hits": [{"title": "T", "url": "http://x", "created_at": created_at}]}
    ).encode()
    arts = HNFetcher(client=_StubClient(payload)).fetch("http://api.example/hn")
    assert len(arts) == 1
    assert arts[0].published_at is None


@pytest.mark.parametrize("indexed_at", [12345, [1, 2], {"x": 1}, "garbage"])
def test_bluesky_fetcher_survives_hostile_indexed_at(indexed_at: object) -> None:
    payload = json.dumps(
        {"feed": [{"post": {"record": {"text": "T"}, "uri": "a/b/rkey", "indexedAt": indexed_at}}]}
    ).encode()
    arts = BlueskyFetcher("handle.test", client=_StubClient(payload)).fetch()
    assert len(arts) == 1
    assert arts[0].published_at is None


def test_parse_rss_items_mixed_valid_and_invalid_items_returns_only_valid() -> None:
    payload = b"""<rss version="2.0"><channel>
      <item><title></title><link>http://x.com/1</link></item>
      <item><title>Good Item</title><link>http://x.com/2</link></item>
      <item><title>Also Good</title><link></link></item>
    </channel></rss>"""
    result = _parse_rss_items(payload)
    assert len(result) == 1
    assert result[0][0] == "Good Item"
    assert result[0][1] == "http://x.com/2"

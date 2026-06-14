"""Adversarial tests for BlueskyFetcher."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from situation_monitor.ingestion.bluesky import BlueskyFetcher
from situation_monitor.models import Article


# ---------------------------------------------------------------------------
# Stub HTTP client
# ---------------------------------------------------------------------------

class StubHttpClient:
    """Returns a fixed bytes payload for any GET, or raises on demand."""

    def __init__(self, payload: bytes | None = None, raise_exc: Exception | None = None) -> None:
        self._payload = payload
        self._raise_exc = raise_exc
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._payload  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_feed_item(
    *,
    text: str | None = "Hello world",
    uri: str = "at://did:plc:abc123/app.bsky.feed.post/3abc",
    indexed_at: str | None = "2024-06-01T12:00:00.000Z",
) -> dict:
    record = {}
    if text is not None:
        record["text"] = text

    post: dict = {"uri": uri, "record": record}
    if indexed_at is not None:
        post["indexedAt"] = indexed_at

    return {"post": post}


def _feed_response(*items: dict) -> bytes:
    return json.dumps({"feed": list(items)}).encode()


# ---------------------------------------------------------------------------
# (a) well-formed XRPC response parses into correct Article fields
# ---------------------------------------------------------------------------

class TestWellFormedResponse:
    def test_url_contains_post_segment(self) -> None:
        item = _make_feed_item(uri="at://did:plc:abc123/app.bsky.feed.post/3abc")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert len(articles) == 1
        assert "/post/" in articles[0].url

    def test_url_contains_rkey(self) -> None:
        item = _make_feed_item(uri="at://did:plc:abc123/app.bsky.feed.post/3rkey999")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert articles[0].url.endswith("/post/3rkey999")

    def test_title_truncated_at_140_chars(self) -> None:
        long_text = "A" * 200
        item = _make_feed_item(text=long_text)
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert articles[0].title == "A" * 140
        # body is not truncated
        assert articles[0].body == long_text

    def test_title_exact_140_chars_is_not_truncated(self) -> None:
        text_140 = "B" * 140
        item = _make_feed_item(text=text_140)
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert articles[0].title == text_140

    def test_tags_include_bluesky(self) -> None:
        item = _make_feed_item()
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert "bluesky" in articles[0].tags

    def test_published_at_is_datetime(self) -> None:
        item = _make_feed_item(indexed_at="2024-06-01T12:00:00.000Z")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert isinstance(articles[0].published_at, datetime)

    def test_published_at_is_utc(self) -> None:
        item = _make_feed_item(indexed_at="2024-06-01T12:00:00.000Z")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        dt = articles[0].published_at
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt == datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    def test_source_set_to_handle(self) -> None:
        item = _make_feed_item()
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("myhandle.bsky.social", client=client)

        articles = fetcher.fetch()

        assert articles[0].source == "myhandle.bsky.social"

    def test_multiple_posts_all_parsed(self) -> None:
        items = [_make_feed_item(text=f"Post {i}") for i in range(5)]
        client = StubHttpClient(payload=_feed_response(*items))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert len(articles) == 5

    def test_returns_list_of_article_instances(self) -> None:
        item = _make_feed_item()
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert all(isinstance(a, Article) for a in articles)


# ---------------------------------------------------------------------------
# (b) empty feed list returns []
# ---------------------------------------------------------------------------

class TestEmptyFeed:
    def test_empty_feed_returns_empty_list(self) -> None:
        payload = json.dumps({"feed": []}).encode()
        client = StubHttpClient(payload=payload)
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []

    def test_missing_feed_key_returns_empty_list(self) -> None:
        payload = json.dumps({}).encode()
        client = StubHttpClient(payload=payload)
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []


# ---------------------------------------------------------------------------
# (c) non-200 HTTP simulated by exception returns []
# ---------------------------------------------------------------------------

class TestHttpErrors:
    def test_connection_error_returns_empty_list(self) -> None:
        client = StubHttpClient(raise_exc=OSError("connection refused"))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []

    def test_timeout_returns_empty_list(self) -> None:
        client = StubHttpClient(raise_exc=TimeoutError("timed out"))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []

    def test_invalid_json_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=b"not json at all {{{")
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []

    def test_empty_bytes_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=b"")
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []

    def test_http_error_exception_returns_empty_list(self) -> None:
        import urllib.error
        client = StubHttpClient(raise_exc=urllib.error.HTTPError(
            url="http://x", code=429, msg="Too Many Requests", hdrs=None, fp=None  # type: ignore[arg-type]
        ))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []


# ---------------------------------------------------------------------------
# (d) post with no text is skipped
# ---------------------------------------------------------------------------

class TestMissingText:
    def test_null_text_is_skipped(self) -> None:
        item = _make_feed_item(text=None)
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []

    def test_empty_string_text_is_skipped(self) -> None:
        item = _make_feed_item(text="")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []

    def test_whitespace_only_text_is_skipped(self) -> None:
        item = _make_feed_item(text="   \t\n  ")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []

    def test_missing_text_key_is_skipped(self) -> None:
        # record has no 'text' key at all
        item = {"post": {"uri": "at://did:plc:abc/app.bsky.feed.post/rk1", "record": {}}}
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert result == []

    def test_valid_post_after_empty_text_post_is_included(self) -> None:
        empty_item = _make_feed_item(text="")
        valid_item = _make_feed_item(text="This is fine")
        client = StubHttpClient(payload=_feed_response(empty_item, valid_item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        result = fetcher.fetch()

        assert len(result) == 1
        assert result[0].title == "This is fine"


# ---------------------------------------------------------------------------
# Edge cases: URL construction and published_at fallback
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_uri_without_slash_yields_empty_rkey(self) -> None:
        item = _make_feed_item(uri="noslashhere")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        # Should still produce an article (text is non-empty); rkey is empty string
        assert len(articles) == 1
        assert articles[0].url.endswith("/post/")

    def test_missing_indexed_at_leaves_published_at_none(self) -> None:
        item = _make_feed_item(indexed_at=None)
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert articles[0].published_at is None

    def test_invalid_indexed_at_leaves_published_at_none(self) -> None:
        item = _make_feed_item(indexed_at="not-a-date")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert articles[0].published_at is None

    def test_custom_url_passed_to_client(self) -> None:
        item = _make_feed_item()
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        fetcher.fetch(url="https://example.com/custom")

        assert client.calls == ["https://example.com/custom"]

    def test_default_url_uses_handle(self) -> None:
        item = _make_feed_item()
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("alice.bsky.social", client=client)

        fetcher.fetch()

        assert "actor=alice.bsky.social" in client.calls[0]

    def test_permalink_contains_handle(self) -> None:
        item = _make_feed_item(uri="at://did:plc:x/app.bsky.feed.post/rk42")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("alice.bsky.social", client=client)

        articles = fetcher.fetch()

        assert "alice.bsky.social" in articles[0].url

    def test_text_shorter_than_140_not_padded(self) -> None:
        item = _make_feed_item(text="Short text")
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert articles[0].title == "Short text"

    def test_only_bluesky_tag_present_by_default(self) -> None:
        item = _make_feed_item()
        client = StubHttpClient(payload=_feed_response(item))
        fetcher = BlueskyFetcher("user.bsky.social", client=client)

        articles = fetcher.fetch()

        assert articles[0].tags == ["bluesky"]

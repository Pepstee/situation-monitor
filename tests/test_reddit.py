"""Adversarial tests for RedditScraper — offline, no network calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from situation_monitor.ingestion.reddit import RedditScraper
from situation_monitor.models import Article, SourceReliability


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

def _make_child(
    *,
    title: str | None = "Test Post Title",
    url: str = "https://example.com/article",
    score: int = 42,
    created_utc: float | None = 1_717_228_800.0,  # 2024-06-01 00:00:00 UTC
    selftext: str = "",
) -> dict:
    data: dict = {"score": score, "selftext": selftext}
    if title is not None:
        data["title"] = title
    if url is not None:
        data["url"] = url
    if created_utc is not None:
        data["created_utc"] = created_utc
    return {"data": data}


def _listing_response(*children: dict) -> bytes:
    return json.dumps({"data": {"children": list(children)}}).encode()


# ---------------------------------------------------------------------------
# (a) Valid subreddit JSON → Articles with correct fields
# ---------------------------------------------------------------------------

class TestValidSubredditResponse:
    def test_returns_list_of_article_instances(self) -> None:
        child = _make_child()
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert len(articles) == 1
        assert isinstance(articles[0], Article)

    def test_title_is_correct(self) -> None:
        child = _make_child(title="Breaking: Something Important")
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].title == "Breaking: Something Important"

    def test_url_is_correct(self) -> None:
        child = _make_child(url="https://example.com/news/story")
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].url == "https://example.com/news/story"

    def test_source_is_reddit(self) -> None:
        child = _make_child()
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].source == "reddit"

    def test_tags_include_reddit(self) -> None:
        child = _make_child()
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert "reddit" in articles[0].tags

    def test_tags_include_subreddit_name(self) -> None:
        child = _make_child()
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("technology")

        assert "r/technology" in articles[0].tags

    def test_tags_include_score(self) -> None:
        child = _make_child(score=1234)
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert "score:1234" in articles[0].tags

    def test_score_zero_appears_in_tags(self) -> None:
        child = _make_child(score=0)
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert "score:0" in articles[0].tags

    def test_published_at_is_utc_datetime(self) -> None:
        # 1_717_228_800 == 2024-06-01 08:00:00 UTC
        child = _make_child(created_utc=1_717_228_800.0)
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        dt = articles[0].published_at
        assert isinstance(dt, datetime)
        assert dt.tzinfo is not None
        assert dt == datetime(2024, 6, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_body_from_selftext(self) -> None:
        child = _make_child(selftext="This is the body of the post.")
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].body == "This is the body of the post."

    def test_empty_selftext_gives_empty_body(self) -> None:
        child = _make_child(selftext="")
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].body == ""

    def test_reliability_is_low(self) -> None:
        child = _make_child()
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].reliability == SourceReliability.LOW

    def test_multiple_posts_all_parsed(self) -> None:
        children = [_make_child(title=f"Post {i}", url=f"https://example.com/{i}") for i in range(5)]
        client = StubHttpClient(payload=_listing_response(*children))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert len(articles) == 5

    def test_subreddit_tag_reflects_argument(self) -> None:
        child = _make_child()
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("science")

        assert "r/science" in articles[0].tags
        assert "r/worldnews" not in articles[0].tags

    def test_url_sent_to_client_uses_subreddit(self) -> None:
        child = _make_child()
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        scraper.fetch("AskReddit")

        assert len(client.calls) == 1
        assert "AskReddit" in client.calls[0]
        assert client.calls[0].endswith(".json")

    def test_url_sent_to_client_uses_old_reddit_base(self) -> None:
        child = _make_child()
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        scraper.fetch("worldnews")

        assert client.calls[0].startswith("https://old.reddit.com/r/")

    def test_title_whitespace_stripped(self) -> None:
        child = _make_child(title="  Padded Title  ")
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].title == "Padded Title"


# ---------------------------------------------------------------------------
# (b) Empty listing → []
# ---------------------------------------------------------------------------

class TestEmptyListing:
    def test_empty_children_returns_empty_list(self) -> None:
        payload = json.dumps({"data": {"children": []}}).encode()
        client = StubHttpClient(payload=payload)
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_missing_data_key_returns_empty_list(self) -> None:
        payload = json.dumps({}).encode()
        client = StubHttpClient(payload=payload)
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_missing_children_key_returns_empty_list(self) -> None:
        payload = json.dumps({"data": {}}).encode()
        client = StubHttpClient(payload=payload)
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_data_value_is_empty_dict_returns_empty_list(self) -> None:
        payload = json.dumps({"data": {}}).encode()
        client = StubHttpClient(payload=payload)
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []


# ---------------------------------------------------------------------------
# (c) Malformed JSON does not crash — returns []
# ---------------------------------------------------------------------------

class TestMalformedJSON:
    def test_garbage_bytes_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=b"not json at all {{{")
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_empty_bytes_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=b"")
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_truncated_json_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=b'{"data": {"children": [{"dat')
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_json_array_at_root_returns_empty_list(self) -> None:
        # Valid JSON but wrong shape — [] has no .get()
        client = StubHttpClient(payload=b"[]")
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_json_null_at_root_returns_empty_list(self) -> None:
        # null has no .get()
        client = StubHttpClient(payload=b"null")
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_json_string_at_root_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=b'"just a string"')
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []


# ---------------------------------------------------------------------------
# (d) Skipping incomplete posts
# ---------------------------------------------------------------------------

class TestSkipsIncompletePost:
    def test_post_with_no_title_is_skipped(self) -> None:
        child = _make_child(title=None)
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_post_with_empty_title_is_skipped(self) -> None:
        child = _make_child(title="")
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_post_with_whitespace_only_title_is_skipped(self) -> None:
        child = _make_child(title="   \t\n  ")
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_post_with_empty_url_is_skipped(self) -> None:
        child = _make_child(url="")
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_post_with_whitespace_only_url_is_skipped(self) -> None:
        child = _make_child(url="   ")
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert result == []

    def test_valid_post_after_skipped_post_is_included(self) -> None:
        bad = _make_child(title="")
        good = _make_child(title="Real Article", url="https://example.com/real")
        client = StubHttpClient(payload=_listing_response(bad, good))
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert len(result) == 1
        assert result[0].title == "Real Article"

    def test_skipped_no_title_does_not_block_later_posts(self) -> None:
        no_title = _make_child(title=None)
        valid1 = _make_child(title="First", url="https://example.com/1")
        valid2 = _make_child(title="Second", url="https://example.com/2")
        client = StubHttpClient(payload=_listing_response(no_title, valid1, valid2))
        scraper = RedditScraper(client=client)

        result = scraper.fetch("worldnews")

        assert len(result) == 2


# ---------------------------------------------------------------------------
# (e) Edge cases: published_at parsing
# ---------------------------------------------------------------------------

class TestPublishedAt:
    def test_missing_created_utc_gives_none(self) -> None:
        child = _make_child(created_utc=None)
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].published_at is None

    def test_invalid_created_utc_string_gives_none(self) -> None:
        raw_child = {"data": {"title": "Post", "url": "https://example.com/", "created_utc": "not-a-number"}}
        client = StubHttpClient(payload=json.dumps({"data": {"children": [raw_child]}}).encode())
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].published_at is None

    def test_created_utc_as_integer_parses_correctly(self) -> None:
        # Some posts return int instead of float; 1_717_228_800 == 2024-06-01 08:00:00 UTC
        raw_child = {"data": {"title": "Post", "url": "https://example.com/", "created_utc": 1_717_228_800}}
        client = StubHttpClient(payload=json.dumps({"data": {"children": [raw_child]}}).encode())
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].published_at == datetime(2024, 6, 1, 8, 0, 0, tzinfo=timezone.utc)

    def test_published_at_has_utc_timezone(self) -> None:
        child = _make_child(created_utc=1_717_228_800.0)
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert articles[0].published_at is not None
        assert articles[0].published_at.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# (f) No network calls — verify stub always used
# ---------------------------------------------------------------------------

class TestOffline:
    def test_no_real_network_call_made(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure the stub intercepts all HTTP — raises if real network attempted."""
        import urllib.request

        def _block(*args: object, **kwargs: object) -> None:
            raise RuntimeError("Real network call attempted!")

        monkeypatch.setattr(urllib.request, "urlopen", _block)

        child = _make_child()
        client = StubHttpClient(payload=_listing_response(child))
        scraper = RedditScraper(client=client)

        articles = scraper.fetch("worldnews")

        assert len(articles) == 1

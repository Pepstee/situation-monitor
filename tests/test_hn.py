"""Tests for HNFetcher using the bundled JSON fixture — zero network calls."""

from __future__ import annotations

import json
import pathlib

from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.models import Article, SourceReliability

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "hn_front_page.json"


class _FakeClient:
    """In-memory HTTP stub — returns pre-loaded bytes, never touches the network."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def get(self, url: str) -> bytes:  # noqa: ARG002
        return self._data


def _fetcher(data: bytes) -> HNFetcher:
    return HNFetcher(client=_FakeClient(data))


def _from_fixture() -> HNFetcher:
    return _fetcher(FIXTURE_PATH.read_bytes())


def _hits(*hits: dict) -> bytes:
    return json.dumps({"hits": list(hits)}).encode()


def _one_hit(**kwargs: object) -> bytes:
    base = {"title": "Test Story", "url": "https://example.com", "objectID": "1", "created_at": "2024-01-01T00:00:00Z"}
    base.update(kwargs)
    return _hits(base)


class TestHNFetcherHappyPath:
    def test_returns_nonempty_list(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        assert len(articles) > 0

    def test_all_items_are_articles(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert isinstance(article, Article)

    def test_all_tagged_hackernews(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert "hackernews" in article.tags

    def test_source_is_hackernews(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.source == "hackernews"

    def test_reliability_is_medium(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.reliability == SourceReliability.MEDIUM

    def test_titles_are_non_empty(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.title, f"Blank title slipped through: {article!r}"

    def test_urls_are_non_empty(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.url, f"Empty URL on article: {article.title!r}"

    def test_parses_title_from_fixture(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        titles = {a.title for a in articles}
        assert "Show HN: I built a real-time air quality monitor" in titles

    def test_parses_url_from_fixture(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        urls = {a.url for a in articles}
        assert "https://example.com/air-quality" in urls

    def test_parses_timestamps_from_fixture(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        dated = [a for a in articles if a.published_at is not None]
        assert len(dated) >= 2

    def test_published_at_is_timezone_aware(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        for article in articles:
            if article.published_at is not None:
                assert article.published_at.tzinfo is not None, (
                    f"published_at on {article.title!r} is naive datetime"
                )

    def test_fixture_skips_empty_title_hit(self) -> None:
        # Fixture hit #3 has empty title — must not appear in output
        articles = _from_fixture().fetch("http://fake")
        assert all(a.title for a in articles)
        urls = {a.url for a in articles}
        assert "https://example.com/no-title" not in urls

    def test_fixture_fallback_url_story_present(self) -> None:
        # Fixture hit #4 has no url field — must get the HN item fallback URL
        articles = _from_fixture().fetch("http://fake")
        hn_items = [a for a in articles if "news.ycombinator.com/item" in a.url]
        assert len(hn_items) >= 1
        assert hn_items[0].url == "https://news.ycombinator.com/item?id=38000004"

    def test_story_text_becomes_body(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        air_quality = next(a for a in articles if a.url == "https://example.com/air-quality")
        assert "air quality" in air_quality.body

    def test_null_story_text_yields_empty_body(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        terminal = next(a for a in articles if a.url == "https://example.com/terminal-discussion")
        assert terminal.body == ""


class TestHNFetcherEdgeCases:
    def test_empty_hits_returns_empty_list(self) -> None:
        data = json.dumps({"hits": []}).encode()
        assert _fetcher(data).fetch("http://fake") == []

    def test_missing_hits_key_returns_empty_list(self) -> None:
        data = json.dumps({}).encode()
        assert _fetcher(data).fetch("http://fake") == []

    def test_skips_empty_title(self) -> None:
        data = _hits(
            {"title": "", "url": "https://example.com/1", "objectID": "1", "created_at": "2024-01-01T00:00:00Z"},
            {"title": "Good Story", "url": "https://example.com/2", "objectID": "2", "created_at": "2024-01-01T00:00:00Z"},
        )
        articles = _fetcher(data).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].title == "Good Story"

    def test_skips_whitespace_only_title(self) -> None:
        data = _hits(
            {"title": "   ", "url": "https://example.com/1", "objectID": "1", "created_at": "2024-01-01T00:00:00Z"},
            {"title": "Valid", "url": "https://example.com/2", "objectID": "2", "created_at": "2024-01-01T00:00:00Z"},
        )
        articles = _fetcher(data).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].title == "Valid"

    def test_fallback_to_hn_url_when_url_absent(self) -> None:
        data = _hits({"title": "Discussion Post", "objectID": "99999", "created_at": "2024-01-01T00:00:00Z"})
        articles = _fetcher(data).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].url == "https://news.ycombinator.com/item?id=99999"

    def test_fallback_to_hn_url_when_url_is_null(self) -> None:
        data = _one_hit(url=None, objectID="77777")
        articles = _fetcher(data).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].url == "https://news.ycombinator.com/item?id=77777"

    def test_fallback_to_hn_url_when_url_is_empty_string(self) -> None:
        data = _one_hit(url="", objectID="55555")
        articles = _fetcher(data).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].url == "https://news.ycombinator.com/item?id=55555"

    def test_invalid_created_at_yields_none_published_at(self) -> None:
        data = _one_hit(created_at="not-a-date")
        articles = _fetcher(data).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].published_at is None

    def test_missing_created_at_yields_none_published_at(self) -> None:
        data = json.dumps({"hits": [{"title": "No Date", "url": "https://example.com", "objectID": "1"}]}).encode()
        articles = _fetcher(data).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].published_at is None

    def test_null_created_at_yields_none_published_at(self) -> None:
        data = _one_hit(created_at=None)
        articles = _fetcher(data).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].published_at is None

    def test_null_story_text_yields_empty_body(self) -> None:
        data = _one_hit(story_text=None)
        articles = _fetcher(data).fetch("http://fake")
        assert articles[0].body == ""

    def test_absent_story_text_yields_empty_body(self) -> None:
        data = json.dumps({"hits": [{"title": "T", "url": "https://example.com", "objectID": "1",
                                     "created_at": "2024-01-01T00:00:00Z"}]}).encode()
        articles = _fetcher(data).fetch("http://fake")
        assert articles[0].body == ""

    def test_story_text_present_in_body(self) -> None:
        data = _one_hit(story_text="Here is the body text.")
        articles = _fetcher(data).fetch("http://fake")
        assert articles[0].body == "Here is the body text."

    def test_tags_list_is_exactly_hackernews(self) -> None:
        data = _one_hit()
        articles = _fetcher(data).fetch("http://fake")
        assert articles[0].tags == ["hackernews"]

    def test_all_items_skipped_returns_empty_list(self) -> None:
        data = _hits(
            {"title": "", "url": "https://example.com/1", "objectID": "1", "created_at": "2024-01-01T00:00:00Z"},
            {"title": "  ", "url": "https://example.com/2", "objectID": "2", "created_at": "2024-01-01T00:00:00Z"},
        )
        assert _fetcher(data).fetch("http://fake") == []

    def test_multiple_valid_hits_all_returned(self) -> None:
        data = _hits(
            {"title": "Alpha", "url": "https://example.com/a", "objectID": "1", "created_at": "2024-01-01T00:00:00Z"},
            {"title": "Beta", "url": "https://example.com/b", "objectID": "2", "created_at": "2024-01-01T00:00:00Z"},
            {"title": "Gamma", "url": "https://example.com/c", "objectID": "3", "created_at": "2024-01-01T00:00:00Z"},
        )
        articles = _fetcher(data).fetch("http://fake")
        assert len(articles) == 3
        assert {a.title for a in articles} == {"Alpha", "Beta", "Gamma"}

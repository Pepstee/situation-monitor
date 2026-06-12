"""Tests for CryptoRSSFetcher using the bundled XML fixture — zero network calls."""

from __future__ import annotations

import pathlib


from situation_monitor.ingestion.crypto import CryptoRSSFetcher
from situation_monitor.models import Article, SourceReliability

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "crypto_rss.xml"


class _FakeClient:
    """In-memory HTTP stub — returns pre-loaded bytes, never touches the network."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def get(self, url: str) -> bytes:  # noqa: ARG002
        return self._data


def _fetcher(xml_bytes: bytes) -> CryptoRSSFetcher:
    return CryptoRSSFetcher(client=_FakeClient(xml_bytes))


def _from_fixture() -> CryptoRSSFetcher:
    return _fetcher(FIXTURE_PATH.read_bytes())


class TestCryptoRSSFetcherHappyPath:
    def test_returns_nonempty_list(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        assert isinstance(articles, list)
        assert len(articles) > 0

    def test_all_items_are_articles(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert isinstance(article, Article)

    def test_source_field_set_to_crypto_rss(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.source == "crypto_rss"

    def test_tags_include_crypto(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert "crypto" in article.tags

    def test_urls_are_non_empty(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.url, f"Empty URL on article: {article.title!r}"

    def test_titles_are_non_empty(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.title, "Blank title slipped through"

    def test_reliability_is_medium(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.reliability == SourceReliability.MEDIUM

    def test_item_count_matches_valid_items_in_fixture(self) -> None:
        # Fixture has 3 items, all with non-empty title and link
        articles = _from_fixture().fetch("http://fake")
        assert len(articles) == 3

    def test_published_at_parsed_for_items_with_pubdate(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        dated = [a for a in articles if a.published_at is not None]
        assert len(dated) >= 2, "Expected at least two articles with parsed published_at"

    def test_item_without_pubdate_has_none_published_at(self) -> None:
        # Third fixture item has no <pubDate>
        articles = _from_fixture().fetch("http://fake")
        undated = [a for a in articles if a.published_at is None]
        assert len(undated) >= 1

    def test_description_becomes_body(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        assert any(a.body for a in articles), "At least one article should have a non-empty body"


class TestCryptoRSSFetcherEdgeCases:
    def test_empty_channel_returns_empty_list(self) -> None:
        xml = b"<?xml version='1.0'?><rss version='2.0'><channel></channel></rss>"
        assert _fetcher(xml).fetch("http://fake") == []

    def test_missing_channel_element_returns_empty_list(self) -> None:
        xml = b"<?xml version='1.0'?><rss version='2.0'></rss>"
        assert _fetcher(xml).fetch("http://fake") == []

    def test_item_with_empty_title_is_skipped(self) -> None:
        xml = b"""<?xml version='1.0'?>
<rss version='2.0'><channel>
  <item><title></title><link>https://example.com/1</link></item>
  <item><title>Good Item</title><link>https://example.com/2</link></item>
</channel></rss>"""
        articles = _fetcher(xml).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].title == "Good Item"

    def test_item_with_empty_link_is_skipped(self) -> None:
        xml = b"""<?xml version='1.0'?>
<rss version='2.0'><channel>
  <item><title>No Link</title><link></link></item>
  <item><title>Has Link</title><link>https://example.com/2</link></item>
</channel></rss>"""
        articles = _fetcher(xml).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].url == "https://example.com/2"

    def test_item_with_whitespace_only_title_is_skipped(self) -> None:
        xml = b"""<?xml version='1.0'?>
<rss version='2.0'><channel>
  <item><title>   </title><link>https://example.com/1</link></item>
  <item><title>Real Title</title><link>https://example.com/2</link></item>
</channel></rss>"""
        articles = _fetcher(xml).fetch("http://fake")
        assert len(articles) == 1

    def test_invalid_pubdate_is_ignored_published_at_is_none(self) -> None:
        xml = b"""<?xml version='1.0'?>
<rss version='2.0'><channel>
  <item>
    <title>Bad Date Article</title>
    <link>https://example.com/bad-date</link>
    <pubDate>not-a-date-at-all</pubDate>
  </item>
</channel></rss>"""
        articles = _fetcher(xml).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].published_at is None

    def test_all_items_missing_title_and_link_returns_empty(self) -> None:
        xml = b"""<?xml version='1.0'?>
<rss version='2.0'><channel>
  <item><title></title><link></link></item>
  <item><title>  </title><link>  </link></item>
</channel></rss>"""
        assert _fetcher(xml).fetch("http://fake") == []

    def test_tags_list_contains_only_crypto(self) -> None:
        xml = b"""<?xml version='1.0'?>
<rss version='2.0'><channel>
  <item><title>Test</title><link>https://example.com/t</link></item>
</channel></rss>"""
        articles = _fetcher(xml).fetch("http://fake")
        assert articles[0].tags == ["crypto"]

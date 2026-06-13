"""Tests for RSSFetcher domain and lens stamping via SourceDef.

Verifies:
- With a SourceDef: returned Article objects carry the correct domain and lens.
- Without a SourceDef: domain stays None and source_lean stays None.
- Edge cases: empty channel, missing title/link, no <channel>, malformed pubDate.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from situation_monitor.config import SourceDef
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.models import Article, Domain

FIXTURE_RSS = Path(__file__).parent / "fixtures" / "rss_sample.xml"


class _StubClient:
    """HTTP stub that returns a fixed bytes payload without making network calls."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def get(self, url: str) -> bytes:
        return self._content


def _rss_bytes() -> bytes:
    return FIXTURE_RSS.read_bytes()


def _source_def(domain: Domain = Domain.WORLD, lens: str = "centre") -> SourceDef:
    return SourceDef(
        url="https://feeds.bbci.co.uk/news/world/rss.xml",
        name="BBC World",
        domain=domain,
        lens=lens,
    )


class TestRSSFetcherWithSourceDef:
    def test_stamps_world_domain_on_articles(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=_source_def(domain=Domain.WORLD))
        assert len(articles) > 0
        for a in articles:
            assert a.domain is Domain.WORLD

    def test_stamps_markets_domain_on_articles(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=_source_def(domain=Domain.MARKETS))
        assert len(articles) > 0
        for a in articles:
            assert a.domain is Domain.MARKETS

    def test_stamps_ai_domain_on_articles(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=_source_def(domain=Domain.AI))
        assert len(articles) > 0
        for a in articles:
            assert a.domain is Domain.AI

    def test_stamps_left_lens_as_source_lean(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=_source_def(lens="left"))
        assert len(articles) > 0
        for a in articles:
            assert a.source_lean == "left"

    def test_stamps_right_lens_as_source_lean(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=_source_def(lens="right"))
        assert len(articles) > 0
        for a in articles:
            assert a.source_lean == "right"

    def test_stamps_centre_lens_as_source_lean(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=_source_def(lens="centre"))
        assert len(articles) > 0
        for a in articles:
            assert a.source_lean == "centre"

    def test_stamps_state_lens_as_source_lean(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=_source_def(lens="state"))
        assert len(articles) > 0
        for a in articles:
            assert a.source_lean == "state"

    def test_domain_and_lens_both_stamped_together(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        sd = _source_def(domain=Domain.AI, lens="right")
        articles = fetcher.fetch("http://irrelevant", source_def=sd)
        assert len(articles) > 0
        for a in articles:
            assert a.domain is Domain.AI
            assert a.source_lean == "right"

    def test_returns_article_objects(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=_source_def())
        assert len(articles) > 0
        for a in articles:
            assert isinstance(a, Article)


class TestRSSFetcherWithoutSourceDef:
    def test_domain_is_none_without_source_def(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=None)
        assert len(articles) > 0
        for a in articles:
            assert a.domain is None

    def test_domain_is_none_when_source_def_omitted(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant")
        assert len(articles) > 0
        for a in articles:
            assert a.domain is None

    def test_source_lean_is_none_without_source_def(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant")
        assert len(articles) > 0
        for a in articles:
            assert a.source_lean is None

    def test_fixture_article_urls_present(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant")
        urls = {a.url for a in articles}
        assert "http://example.com/bitcoin-surge" in urls

    def test_fixture_article_titles_present(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant")
        titles = {a.title for a in articles}
        assert "Bitcoin Surges Past Key Resistance Level" in titles

    def test_source_name_taken_from_channel_title(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant")
        # The fixture channel title is "Test Feed"
        for a in articles:
            assert a.source == "Test Feed"

    def test_tags_include_rss(self) -> None:
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant")
        for a in articles:
            assert "rss" in a.tags


class TestRSSFetcherEdgeCases:
    def test_empty_channel_returns_empty_list(self) -> None:
        xml = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
        fetcher = RSSFetcher(client=_StubClient(xml))
        assert fetcher.fetch("http://irrelevant") == []

    def test_item_with_no_title_is_skipped(self) -> None:
        xml = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
            b'<item><link>http://example.com/a</link></item></channel></rss>'
        )
        fetcher = RSSFetcher(client=_StubClient(xml))
        assert fetcher.fetch("http://irrelevant") == []

    def test_item_with_no_link_is_skipped(self) -> None:
        xml = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
            b'<item><title>Some Title</title></item></channel></rss>'
        )
        fetcher = RSSFetcher(client=_StubClient(xml))
        assert fetcher.fetch("http://irrelevant") == []

    def test_rss_with_no_channel_element_returns_empty_list(self) -> None:
        xml = b'<?xml version="1.0"?><rss version="2.0"></rss>'
        fetcher = RSSFetcher(client=_StubClient(xml))
        assert fetcher.fetch("http://irrelevant") == []

    def test_malformed_pub_date_does_not_raise(self) -> None:
        xml = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
            b'<item><title>Article</title><link>http://example.com/a</link>'
            b'<pubDate>definitely not a date</pubDate></item></channel></rss>'
        )
        fetcher = RSSFetcher(client=_StubClient(xml))
        articles = fetcher.fetch("http://irrelevant")
        assert len(articles) == 1
        assert articles[0].published_at is None

    def test_valid_pub_date_parsed(self) -> None:
        xml = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
            b'<item><title>Article</title><link>http://example.com/a</link>'
            b'<pubDate>Mon, 01 Jan 2024 12:00:00 +0000</pubDate></item></channel></rss>'
        )
        fetcher = RSSFetcher(client=_StubClient(xml))
        articles = fetcher.fetch("http://irrelevant")
        assert len(articles) == 1
        assert articles[0].published_at is not None

    def test_source_def_with_none_domain_stamps_none(self) -> None:
        # SourceDef.domain is typed as Domain, but domain=None passed explicitly
        # should stay None on the article (this exercises the None guard in rss.py)
        fetcher = RSSFetcher(client=_StubClient(_rss_bytes()))
        articles = fetcher.fetch("http://irrelevant", source_def=None)
        for a in articles:
            assert a.domain is None

    def test_items_with_empty_title_whitespace_only_are_skipped(self) -> None:
        xml = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
            b'<item><title>   </title><link>http://example.com/a</link></item></channel></rss>'
        )
        fetcher = RSSFetcher(client=_StubClient(xml))
        assert fetcher.fetch("http://irrelevant") == []

    def test_items_with_empty_link_whitespace_only_are_skipped(self) -> None:
        xml = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
            b'<item><title>Valid title</title><link>   </link></item></channel></rss>'
        )
        fetcher = RSSFetcher(client=_StubClient(xml))
        assert fetcher.fetch("http://irrelevant") == []

    def test_body_taken_from_description(self) -> None:
        xml = (
            b'<?xml version="1.0"?><rss version="2.0"><channel><title>T</title>'
            b'<item><title>Headline</title><link>http://example.com/a</link>'
            b'<description>The article body here.</description></item></channel></rss>'
        )
        fetcher = RSSFetcher(client=_StubClient(xml))
        articles = fetcher.fetch("http://irrelevant")
        assert articles[0].body == "The article body here."

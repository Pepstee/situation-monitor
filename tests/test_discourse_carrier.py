"""Adversarial tests for DiscourseCarrierFetcher and roster integration.

Covers:
- CarrierDef field validation
- DiscourseCarrierFetcher.fetch() with mocked HTTP client
- country/lean metadata stamped on returned Articles
- carrier articles survive dedup merge without being silently dropped
- pipeline integration stub produces non-empty digest entry from a fake carrier feed
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import pytest

from situation_monitor.dedup import deduplicate
from situation_monitor.ingestion.discourse_carrier import (
    CARRIER_ROSTER,
    CarrierDef,
    DiscourseCarrierFetcher,
)
from situation_monitor.models import Article, DigestEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _rss_bytes(items: list[dict[str, str]], channel_title: str = "Test Feed") -> bytes:
    """Build a minimal RSS 2.0 XML payload from a list of item dicts."""
    root = ET.Element("rss", version="2.0")
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = channel_title
    for item in items:
        elem = ET.SubElement(channel, "item")
        for tag, val in item.items():
            ET.SubElement(elem, tag).text = val
    return ET.tostring(root, encoding="unicode").encode()


def _one_item(n: int = 1) -> list[dict[str, str]]:
    return [{"title": f"Story {n}", "link": f"https://example.com/story/{n}"}]


class _PerURLClient:
    """Returns pre-programmed bytes keyed by URL; raises on unknown URLs."""

    def __init__(self, mapping: dict[str, bytes]) -> None:
        self._map = mapping
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if url in self._map:
            return self._map[url]
        raise OSError(f"No fixture for URL: {url!r}")


class _UniformClient:
    """Returns the same payload for every URL."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        return self._data


class _ErrorClient:
    """Always raises an OSError."""

    def get(self, url: str) -> bytes:
        raise OSError("network unavailable")


# ---------------------------------------------------------------------------
# CarrierDef — field validation
# ---------------------------------------------------------------------------

class TestCarrierDefFields:
    def test_namedtuple_fields_accessible(self) -> None:
        c = CarrierDef(url="https://feeds.example.com/rss", country="US", lean="centre")
        assert c.url == "https://feeds.example.com/rss"
        assert c.country == "US"
        assert c.lean == "centre"

    def test_lean_values_preserved_verbatim(self) -> None:
        for lean in ("left", "right", "centre", "state"):
            c = CarrierDef(url="https://x.com", country="XX", lean=lean)
            assert c.lean == lean

    def test_country_stored_as_provided(self) -> None:
        c = CarrierDef(url="https://x.com", country="DE", lean="state")
        assert c.country == "DE"

    def test_url_stored_as_provided(self) -> None:
        url = "http://www.xinhuanet.com/english/rss/worldnews.xml"
        c = CarrierDef(url=url, country="CN", lean="state")
        assert c.url == url

    def test_positional_construction_works(self) -> None:
        c = CarrierDef("https://rt.com/rss/", "RU", "state")
        assert c.url == "https://rt.com/rss/"
        assert c.country == "RU"
        assert c.lean == "state"

    def test_unpacking_preserves_order(self) -> None:
        url, country, lean = CarrierDef("https://x.com", "FR", "state")
        assert url == "https://x.com"
        assert country == "FR"
        assert lean == "state"

    def test_equality_based_on_values(self) -> None:
        a = CarrierDef("https://x.com", "GB", "centre")
        b = CarrierDef("https://x.com", "GB", "centre")
        assert a == b

    def test_different_country_not_equal(self) -> None:
        a = CarrierDef("https://x.com", "GB", "centre")
        b = CarrierDef("https://x.com", "US", "centre")
        assert a != b

    def test_is_namedtuple(self) -> None:
        c = CarrierDef("https://x.com", "US", "centre")
        assert hasattr(c, "_fields")
        assert set(c._fields) == {"url", "country", "lean"}


# ---------------------------------------------------------------------------
# CARRIER_ROSTER — built-in roster sanity
# ---------------------------------------------------------------------------

class TestCarrierRoster:
    def test_roster_is_nonempty(self) -> None:
        assert len(CARRIER_ROSTER) > 0

    def test_all_items_are_carrier_defs(self) -> None:
        for item in CARRIER_ROSTER:
            assert isinstance(item, CarrierDef), f"Expected CarrierDef, got {type(item)!r}"

    def test_all_urls_nonempty(self) -> None:
        for c in CARRIER_ROSTER:
            assert c.url, f"Empty URL in {c!r}"

    def test_all_countries_nonempty(self) -> None:
        for c in CARRIER_ROSTER:
            assert c.country, f"Empty country in {c!r}"

    def test_all_leans_nonempty(self) -> None:
        for c in CARRIER_ROSTER:
            assert c.lean, f"Empty lean in {c!r}"

    def test_all_urls_start_with_http(self) -> None:
        for c in CARRIER_ROSTER:
            assert c.url.startswith("http"), f"Non-HTTP URL: {c.url!r}"

    def test_multiple_countries_represented(self) -> None:
        countries = {c.country for c in CARRIER_ROSTER}
        assert len(countries) >= 3, f"Only {countries} found; expected geographic diversity"

    def test_lean_values_are_known(self) -> None:
        known = {"left", "right", "centre", "state"}
        for c in CARRIER_ROSTER:
            assert c.lean in known, f"Unknown lean {c.lean!r} in {c!r}"


# ---------------------------------------------------------------------------
# DiscourseCarrierFetcher.fetch() — happy path
# ---------------------------------------------------------------------------

class TestDiscourseCarrierFetcherHappyPath:
    def _fetcher_with_one_carrier(
        self, country: str = "GB", lean: str = "centre"
    ) -> tuple[DiscourseCarrierFetcher, _UniformClient]:
        carrier_url = "https://fake-feed.example.com/rss"
        data = _rss_bytes(_one_item(), channel_title="Fake Feed")
        client = _UniformClient(data)
        roster = [CarrierDef(url=carrier_url, country=country, lean=lean)]
        fetcher = DiscourseCarrierFetcher(roster=roster, client=client)
        return fetcher, client

    def test_returns_list(self) -> None:
        fetcher, _ = self._fetcher_with_one_carrier()
        result = fetcher.fetch()
        assert isinstance(result, list)

    def test_returns_article_objects(self) -> None:
        fetcher, _ = self._fetcher_with_one_carrier()
        for art in fetcher.fetch():
            assert isinstance(art, Article)

    def test_article_has_correct_lean(self) -> None:
        fetcher, _ = self._fetcher_with_one_carrier(country="GB", lean="centre")
        articles = fetcher.fetch()
        assert len(articles) > 0
        for art in articles:
            assert art.source_lean == "centre"

    def test_article_has_correct_country_tag(self) -> None:
        fetcher, _ = self._fetcher_with_one_carrier(country="GB", lean="centre")
        articles = fetcher.fetch()
        assert len(articles) > 0
        for art in articles:
            assert "country:GB" in art.tags

    def test_article_has_carrier_tag(self) -> None:
        fetcher, _ = self._fetcher_with_one_carrier()
        articles = fetcher.fetch()
        assert len(articles) > 0
        for art in articles:
            assert "carrier" in art.tags

    def test_url_is_used_for_fetch(self) -> None:
        carrier_url = "https://unique-test-url.example.com/rss"
        data = _rss_bytes(_one_item())
        client = _UniformClient(data)
        roster = [CarrierDef(url=carrier_url, country="US", lean="right")]
        DiscourseCarrierFetcher(roster=roster, client=client).fetch()
        assert carrier_url in client.calls

    def test_unused_url_arg_does_not_raise(self) -> None:
        fetcher, _ = self._fetcher_with_one_carrier()
        result = fetcher.fetch(url="https://ignored.example.com")
        assert isinstance(result, list)

    def test_empty_url_arg_works(self) -> None:
        fetcher, _ = self._fetcher_with_one_carrier()
        result = fetcher.fetch(url="")
        assert isinstance(result, list)

    def test_multiple_carriers_all_fetched(self) -> None:
        carriers = [
            CarrierDef("https://gb.example.com/rss", "GB", "centre"),
            CarrierDef("https://ru.example.com/rss", "RU", "state"),
            CarrierDef("https://us.example.com/rss", "US", "right"),
        ]
        mapping = {
            "https://gb.example.com/rss": _rss_bytes(_one_item(1), "GB Feed"),
            "https://ru.example.com/rss": _rss_bytes(_one_item(2), "RU Feed"),
            "https://us.example.com/rss": _rss_bytes(_one_item(3), "US Feed"),
        }
        client = _PerURLClient(mapping)
        fetcher = DiscourseCarrierFetcher(roster=carriers, client=client)
        articles = fetcher.fetch()
        assert len(articles) == 3

    def test_articles_from_different_carriers_have_correct_lean(self) -> None:
        carriers = [
            CarrierDef("https://left.example.com/rss", "QA", "left"),
            CarrierDef("https://right.example.com/rss", "US", "right"),
        ]
        mapping = {
            "https://left.example.com/rss": _rss_bytes(_one_item(1), "Left Feed"),
            "https://right.example.com/rss": _rss_bytes(_one_item(2), "Right Feed"),
        }
        client = _PerURLClient(mapping)
        fetcher = DiscourseCarrierFetcher(roster=carriers, client=client)
        articles = fetcher.fetch()
        leans = {a.source_lean for a in articles}
        assert "left" in leans
        assert "right" in leans

    def test_articles_from_different_carriers_have_correct_country_tags(self) -> None:
        carriers = [
            CarrierDef("https://qa.example.com/rss", "QA", "left"),
            CarrierDef("https://de.example.com/rss", "DE", "state"),
        ]
        mapping = {
            "https://qa.example.com/rss": _rss_bytes(_one_item(1), "QA Feed"),
            "https://de.example.com/rss": _rss_bytes(_one_item(2), "DE Feed"),
        }
        client = _PerURLClient(mapping)
        fetcher = DiscourseCarrierFetcher(roster=carriers, client=client)
        articles = fetcher.fetch()
        country_tags = set()
        for art in articles:
            country_tags.update(t for t in art.tags if t.startswith("country:"))
        assert "country:QA" in country_tags
        assert "country:DE" in country_tags

    def test_tags_not_duplicated_on_multiple_fetches(self) -> None:
        """Tags must not accumulate if fetch() is called more than once."""
        carrier_url = "https://feed.example.com/rss"
        data = _rss_bytes(_one_item())
        client = _UniformClient(data)
        roster = [CarrierDef(url=carrier_url, country="FR", lean="state")]
        fetcher = DiscourseCarrierFetcher(roster=roster, client=client)
        articles = fetcher.fetch()
        assert len(articles) > 0
        for art in articles:
            assert art.tags.count("carrier") == 1
            assert art.tags.count("country:FR") == 1

    def test_empty_roster_returns_empty_list(self) -> None:
        client = _UniformClient(_rss_bytes(_one_item()))
        fetcher = DiscourseCarrierFetcher(roster=[], client=client)
        assert fetcher.fetch() == []

    def test_multiple_items_per_feed_all_returned(self) -> None:
        items = [{"title": f"Article {i}", "link": f"https://example.com/{i}"} for i in range(5)]
        data = _rss_bytes(items)
        client = _UniformClient(data)
        roster = [CarrierDef("https://feed.example.com", "IN", "centre")]
        fetcher = DiscourseCarrierFetcher(roster=roster, client=client)
        articles = fetcher.fetch()
        assert len(articles) == 5


# ---------------------------------------------------------------------------
# DiscourseCarrierFetcher — metadata correctness for specific lean values
# ---------------------------------------------------------------------------

class TestLeanMetadataStamping:
    def _fetch_with_lean(self, lean: str) -> list[Article]:
        data = _rss_bytes(_one_item())
        client = _UniformClient(data)
        roster = [CarrierDef("https://x.com/rss", "XX", lean)]
        return DiscourseCarrierFetcher(roster=roster, client=client).fetch()

    def test_left_lean_stamped(self) -> None:
        articles = self._fetch_with_lean("left")
        assert all(a.source_lean == "left" for a in articles)

    def test_right_lean_stamped(self) -> None:
        articles = self._fetch_with_lean("right")
        assert all(a.source_lean == "right" for a in articles)

    def test_centre_lean_stamped(self) -> None:
        articles = self._fetch_with_lean("centre")
        assert all(a.source_lean == "centre" for a in articles)

    def test_state_lean_stamped(self) -> None:
        articles = self._fetch_with_lean("state")
        assert all(a.source_lean == "state" for a in articles)

    def test_lean_overrides_rss_default(self) -> None:
        """RSSFetcher sets no source_lean; DiscourseCarrierFetcher must overwrite it."""
        data = _rss_bytes(_one_item())
        client = _UniformClient(data)
        roster = [CarrierDef("https://x.com/rss", "RU", "state")]
        articles = DiscourseCarrierFetcher(roster=roster, client=client).fetch()
        for art in articles:
            assert art.source_lean == "state", (
                f"Expected 'state', got {art.source_lean!r}"
            )


# ---------------------------------------------------------------------------
# DiscourseCarrierFetcher — error isolation: one bad feed must not kill others
# ---------------------------------------------------------------------------

class TestFeedErrorIsolation:
    def test_failing_carrier_does_not_raise(self) -> None:
        roster = [CarrierDef("https://bad.example.com/rss", "XX", "state")]
        client = _ErrorClient()
        fetcher = DiscourseCarrierFetcher(roster=roster, client=client)
        result = fetcher.fetch()
        assert result == []

    def test_good_feed_returned_despite_bad_feed(self) -> None:
        good_url = "https://good.example.com/rss"
        bad_url = "https://bad.example.com/rss"
        mapping = {good_url: _rss_bytes(_one_item(), "Good Feed")}
        # bad_url not in mapping → _PerURLClient raises OSError
        client = _PerURLClient(mapping)
        roster = [
            CarrierDef(bad_url, "XX", "state"),
            CarrierDef(good_url, "GB", "centre"),
        ]
        articles = DiscourseCarrierFetcher(roster=roster, client=client).fetch()
        assert len(articles) == 1
        assert "country:GB" in articles[0].tags

    def test_all_feeds_fail_returns_empty_list(self) -> None:
        roster = [
            CarrierDef(f"https://bad{i}.example.com/rss", "XX", "state")
            for i in range(3)
        ]
        client = _ErrorClient()
        assert DiscourseCarrierFetcher(roster=roster, client=client).fetch() == []

    def test_malformed_xml_skipped(self) -> None:
        broken = b"<not valid xml>"
        good_url = "https://good.example.com/rss"
        broken_url = "https://broken.example.com/rss"
        mapping = {
            broken_url: broken,
            good_url: _rss_bytes(_one_item(), "Good Feed"),
        }
        client = _PerURLClient(mapping)
        roster = [
            CarrierDef(broken_url, "ZZ", "left"),
            CarrierDef(good_url, "US", "right"),
        ]
        articles = DiscourseCarrierFetcher(roster=roster, client=client).fetch()
        # Only the good feed's article(s) survive
        assert all("country:US" in a.tags for a in articles)
        assert not any("country:ZZ" in a.tags for a in articles)

    def test_empty_rss_response_yields_no_articles(self) -> None:
        """A feed that returns an RSS channel with no items contributes nothing."""
        data = _rss_bytes([], "Empty Feed")
        client = _UniformClient(data)
        roster = [CarrierDef("https://empty.example.com/rss", "JP", "centre")]
        articles = DiscourseCarrierFetcher(roster=roster, client=client).fetch()
        assert articles == []


# ---------------------------------------------------------------------------
# Default roster is used when no roster is passed
# ---------------------------------------------------------------------------

class TestDefaultRosterUsed:
    def test_default_roster_is_carrier_roster(self) -> None:
        """Without an explicit roster the global CARRIER_ROSTER drives fetch calls."""
        call_log: list[str] = []

        class _CountingClient:
            def get(self, url: str) -> bytes:
                call_log.append(url)
                return _rss_bytes([])  # empty feed is fine — we just count calls

        fetcher = DiscourseCarrierFetcher(client=_CountingClient())
        fetcher.fetch()
        assert len(call_log) == len(CARRIER_ROSTER)

    def test_default_roster_urls_match_carrier_roster(self) -> None:
        call_log: list[str] = []

        class _LoggingClient:
            def get(self, url: str) -> bytes:
                call_log.append(url)
                return _rss_bytes([])

        DiscourseCarrierFetcher(client=_LoggingClient()).fetch()
        expected_urls = {c.url for c in CARRIER_ROSTER}
        assert set(call_log) == expected_urls


# ---------------------------------------------------------------------------
# Carrier articles survive dedup merge without silent drops
# ---------------------------------------------------------------------------

class TestCarrierArticlesSurviveDedup:
    def test_carrier_articles_with_unique_urls_all_survive(self) -> None:
        """dedup must not silently drop carrier articles that have unique URLs."""
        items = [{"title": f"Carrier Story {i}", "link": f"https://example.com/c{i}"} for i in range(4)]
        data = _rss_bytes(items)
        client = _UniformClient(data)
        roster = [CarrierDef("https://feed.example.com/rss", "GB", "centre")]
        articles = DiscourseCarrierFetcher(roster=roster, client=client).fetch()
        deduped = deduplicate(articles)
        assert len(deduped) == 4

    def test_carrier_articles_mixed_with_non_carrier_survive_dedup(self) -> None:
        """Carrier articles mixed into a larger pool should not be swallowed."""
        carrier_items = [
            {"title": "Crisis in region X deepens amid tension", "link": "https://bbc.com/story/1"},
            {"title": "Global markets react to latest events", "link": "https://reuters.com/story/2"},
        ]
        data = _rss_bytes(carrier_items)
        client = _UniformClient(data)
        roster = [CarrierDef("https://bbc.com/rss", "GB", "centre")]
        carrier_articles = DiscourseCarrierFetcher(roster=roster, client=client).fetch()

        extra = [
            Article(url="https://other.com/story/99", title="Technology sector rebounds today after slump", source="other"),
        ]
        pool = carrier_articles + extra
        result = deduplicate(pool)
        # All three have distinct URLs and non-overlapping 6-word title prefixes
        assert len(result) == 3

    def test_exact_url_duplicates_still_deduped(self) -> None:
        """Two carriers pointing to the same RSS story URL: dedup removes one."""
        shared_url = "https://wire.com/breaking-story"
        carriers = [
            CarrierDef("https://feedA.example.com/rss", "GB", "centre"),
            CarrierDef("https://feedB.example.com/rss", "US", "right"),
        ]
        # Both feeds return an item pointing to the same URL
        rss_both = _rss_bytes(
            [{"title": "Breaking Story Now", "link": shared_url}],
        )
        client = _UniformClient(rss_both)
        articles = DiscourseCarrierFetcher(roster=carriers, client=client).fetch()
        assert len(articles) == 2  # fetcher returns both before dedup
        deduped = deduplicate(articles)
        assert len(deduped) == 1  # dedup removes the second occurrence

    def test_carrier_tag_preserved_after_dedup(self) -> None:
        data = _rss_bytes(_one_item())
        client = _UniformClient(data)
        roster = [CarrierDef("https://feed.example.com/rss", "FR", "state")]
        articles = DiscourseCarrierFetcher(roster=roster, client=client).fetch()
        deduped = deduplicate(articles)
        assert len(deduped) == 1
        assert "carrier" in deduped[0].tags

    def test_country_tag_preserved_after_dedup(self) -> None:
        data = _rss_bytes(_one_item())
        client = _UniformClient(data)
        roster = [CarrierDef("https://feed.example.com/rss", "DE", "state")]
        articles = DiscourseCarrierFetcher(roster=roster, client=client).fetch()
        deduped = deduplicate(articles)
        assert len(deduped) == 1
        assert "country:DE" in deduped[0].tags

    def test_source_lean_preserved_after_dedup(self) -> None:
        data = _rss_bytes(_one_item())
        client = _UniformClient(data)
        roster = [CarrierDef("https://feed.example.com/rss", "RU", "state")]
        articles = DiscourseCarrierFetcher(roster=roster, client=client).fetch()
        deduped = deduplicate(articles)
        assert len(deduped) == 1
        assert deduped[0].source_lean == "state"

    def test_near_duplicate_titles_from_two_carriers_deduped(self) -> None:
        """Same story filed by two carriers with near-identical titles → only one survives."""
        same_headline = "Ukraine ceasefire talks stall as parties meet in Geneva today"
        carriers = [
            CarrierDef("https://gb.example.com/rss", "GB", "centre"),
            CarrierDef("https://fr.example.com/rss", "FR", "state"),
        ]
        mapping = {
            "https://gb.example.com/rss": _rss_bytes(
                [{"title": same_headline, "link": "https://gb.example.com/1"}], "GB Feed"
            ),
            "https://fr.example.com/rss": _rss_bytes(
                [{"title": same_headline + " extended", "link": "https://fr.example.com/1"}], "FR Feed"
            ),
        }
        client = _PerURLClient(mapping)
        articles = DiscourseCarrierFetcher(roster=carriers, client=client).fetch()
        deduped = deduplicate(articles)
        assert len(deduped) == 1, "Near-duplicate carrier stories should be deduped to one"


# ---------------------------------------------------------------------------
# Pipeline integration stub — non-empty DigestEntry from a fake carrier feed
# ---------------------------------------------------------------------------

class TestPipelineIntegrationStub:
    """Verify end-to-end: carrier feed → fetch → dedup → DigestEntry is non-empty."""

    def _build_digest(
        self,
        num_items: int = 3,
        country: str = "GB",
        lean: str = "centre",
    ) -> DigestEntry:
        items = [
            {"title": f"Carrier News Story {i}", "link": f"https://carrier.example.com/story/{i}"}
            for i in range(num_items)
        ]
        data = _rss_bytes(items, "Carrier Feed")
        client = _UniformClient(data)
        roster = [CarrierDef("https://carrier.example.com/rss", country, lean)]
        fetcher = DiscourseCarrierFetcher(roster=roster, client=client)

        articles = fetcher.fetch()
        deduped = deduplicate(articles)
        return DigestEntry(articles=deduped, summary="Test digest from carrier feed", topic="world")

    def test_digest_entry_is_not_empty(self) -> None:
        digest = self._build_digest()
        assert len(digest.articles) > 0

    def test_digest_entry_contains_article_objects(self) -> None:
        digest = self._build_digest()
        for art in digest.articles:
            assert isinstance(art, Article)

    def test_digest_summary_non_empty(self) -> None:
        digest = self._build_digest()
        assert digest.summary

    def test_digest_article_count_matches_feed(self) -> None:
        digest = self._build_digest(num_items=5)
        assert len(digest.articles) == 5

    def test_digest_articles_carry_country_tag(self) -> None:
        digest = self._build_digest(country="DE")
        for art in digest.articles:
            assert "country:DE" in art.tags

    def test_digest_articles_carry_lean(self) -> None:
        digest = self._build_digest(lean="state")
        for art in digest.articles:
            assert art.source_lean == "state"

    def test_digest_articles_carry_carrier_tag(self) -> None:
        digest = self._build_digest()
        for art in digest.articles:
            assert "carrier" in art.tags

    def test_multi_carrier_pipeline_produces_multi_source_digest(self) -> None:
        carriers = [
            CarrierDef("https://us.example.com/rss", "US", "right"),
            CarrierDef("https://gb.example.com/rss", "GB", "centre"),
            CarrierDef("https://ru.example.com/rss", "RU", "state"),
        ]
        mapping = {
            "https://us.example.com/rss": _rss_bytes(
                [{"title": "US Capitol latest news update today", "link": "https://us.example.com/1"}], "US Feed"
            ),
            "https://gb.example.com/rss": _rss_bytes(
                [{"title": "British parliament debates Brexit bill", "link": "https://gb.example.com/1"}], "GB Feed"
            ),
            "https://ru.example.com/rss": _rss_bytes(
                [{"title": "Kremlin issues statement on sanctions policy", "link": "https://ru.example.com/1"}], "RU Feed"
            ),
        }
        client = _PerURLClient(mapping)
        fetcher = DiscourseCarrierFetcher(roster=carriers, client=client)
        articles = fetcher.fetch()
        deduped = deduplicate(articles)
        digest = DigestEntry(articles=deduped, summary="Multi-carrier digest", topic="geopolitics")

        assert len(digest.articles) == 3
        country_tags_found = set()
        for art in digest.articles:
            for tag in art.tags:
                if tag.startswith("country:"):
                    country_tags_found.add(tag)
        assert "country:US" in country_tags_found
        assert "country:GB" in country_tags_found
        assert "country:RU" in country_tags_found

    def test_all_failed_feeds_yields_empty_digest(self) -> None:
        roster = [CarrierDef("https://bad.example.com/rss", "XX", "state")]
        client = _ErrorClient()
        fetcher = DiscourseCarrierFetcher(roster=roster, client=client)
        articles = fetcher.fetch()
        deduped = deduplicate(articles)
        digest = DigestEntry(articles=deduped, summary="Empty digest", topic="test")
        assert digest.articles == []

    def test_digest_entry_accepts_carrier_articles(self) -> None:
        """DigestEntry.__post_init__ must not reject the article list shape produced here."""
        digest = self._build_digest(num_items=2)
        assert isinstance(digest.articles, list)
        assert all(hasattr(a, "url") for a in digest.articles)

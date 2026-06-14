"""Adversarial tests for NitterFetcher URL construction and RSS delegation."""

from __future__ import annotations

from pathlib import Path

import pytest

from situation_monitor.ingestion.nitter import NitterFetcher, NITTER_INSTANCES
from situation_monitor.models import Article

# ---------------------------------------------------------------------------
# Stub HTTP client that records calls and returns a fixed RSS payload
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures"


def _rss_bytes(name: str = "rss_sample.xml") -> bytes:
    return (_FIXTURES / name).read_bytes()


class StubHttpClient:
    """Returns a fixed bytes payload for every GET and records every URL fetched."""

    def __init__(self, payload: bytes | None = None, raise_exc: Exception | None = None) -> None:
        self._payload = payload if payload is not None else _rss_bytes()
        self._raise_exc = raise_exc
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._payload


# ---------------------------------------------------------------------------
# (a) Default base URL produces correct RSS endpoint for a given handle
# ---------------------------------------------------------------------------

class TestDefaultBaseUrl:
    def test_rss_url_uses_default_nitter_host(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("elonmusk", client=client)

        fetcher.fetch()

        assert client.calls == ["https://nitter.net/elonmusk/rss"]

    def test_rss_url_contains_handle_segment(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("naval", client=client)

        fetcher.fetch()

        assert "/naval/rss" in client.calls[0]

    def test_rss_url_ends_with_rss(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("someuser", client=client)

        fetcher.fetch()

        assert client.calls[0].endswith("/rss")

    def test_at_prefix_stripped_from_handle(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("@naval", client=client)

        fetcher.fetch()

        # The URL must not contain a literal '@'
        assert "@" not in client.calls[0]
        assert "/naval/rss" in client.calls[0]

    def test_double_at_prefix_stripped(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("@@weird", client=client)

        fetcher.fetch()

        # lstrip('@') removes all leading '@'
        assert "@" not in client.calls[0]
        assert "/weird/rss" in client.calls[0]

    def test_exactly_one_http_call_made(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("user", client=client)

        fetcher.fetch()

        assert len(client.calls) == 1

    def test_default_base_url_in_nitter_instances_list(self) -> None:
        # The hardcoded default must be one of the recognised instances
        assert "https://nitter.net" in NITTER_INSTANCES


# ---------------------------------------------------------------------------
# (b) Custom nitter_base_url is respected
# ---------------------------------------------------------------------------

class TestCustomBaseUrl:
    def test_custom_host_appears_in_fetched_url(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("user", nitter_base_url="https://nitter.example.com", client=client)

        fetcher.fetch()

        assert client.calls[0].startswith("https://nitter.example.com/")

    def test_custom_host_with_trailing_slash_is_normalised(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("user", nitter_base_url="https://nitter.example.com/", client=client)

        fetcher.fetch()

        # rstrip('/') must prevent double-slash
        assert "//user" not in client.calls[0]
        assert client.calls[0] == "https://nitter.example.com/user/rss"

    def test_custom_host_full_url_structure(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("alice", nitter_base_url="https://custom.nitter.io", client=client)

        fetcher.fetch()

        assert client.calls[0] == "https://custom.nitter.io/alice/rss"

    def test_multiple_trailing_slashes_on_base_url(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("bob", nitter_base_url="https://nitter.io///", client=client)

        fetcher.fetch()

        assert "//" not in client.calls[0].replace("https://", "")

    def test_handle_without_at_with_custom_base(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("@techuser", nitter_base_url="https://priv.nitter.net", client=client)

        fetcher.fetch()

        assert client.calls[0] == "https://priv.nitter.net/techuser/rss"


# ---------------------------------------------------------------------------
# (c) Returned Articles carry 'twitter' tag
# ---------------------------------------------------------------------------

class TestTwitterTag:
    def test_all_articles_have_twitter_tag(self) -> None:
        client = StubHttpClient(payload=_rss_bytes("rss_sample.xml"))
        fetcher = NitterFetcher("user", client=client)

        articles = fetcher.fetch()

        assert articles, "expected non-empty article list from fixture"
        assert all("twitter" in a.tags for a in articles)

    def test_twitter_tag_added_only_once_even_if_already_present(self) -> None:
        # RSS base articles come with 'rss' tag; ensure no duplicate 'twitter'
        client = StubHttpClient(payload=_rss_bytes("rss_sample.xml"))
        fetcher = NitterFetcher("user", client=client)

        articles = fetcher.fetch()

        for article in articles:
            assert article.tags.count("twitter") == 1

    def test_rss_tag_also_present_from_delegation(self) -> None:
        # RSSFetcher always adds 'rss' tag; NitterFetcher must not strip it
        client = StubHttpClient(payload=_rss_bytes("rss_sample.xml"))
        fetcher = NitterFetcher("user", client=client)

        articles = fetcher.fetch()

        assert all("rss" in a.tags for a in articles)

    def test_returns_list_of_article_instances(self) -> None:
        client = StubHttpClient(payload=_rss_bytes("rss_sample.xml"))
        fetcher = NitterFetcher("user", client=client)

        articles = fetcher.fetch()

        assert all(isinstance(a, Article) for a in articles)

    def test_twitter_tag_with_left_fixture(self) -> None:
        client = StubHttpClient(payload=_rss_bytes("rss_left.xml"))
        fetcher = NitterFetcher("leftuser", client=client)

        articles = fetcher.fetch()

        assert all("twitter" in a.tags for a in articles)

    def test_twitter_tag_idempotent_on_repeated_fetch(self) -> None:
        client = StubHttpClient(payload=_rss_bytes("rss_sample.xml"))
        fetcher = NitterFetcher("user", client=client)

        articles_first = fetcher.fetch()
        # Fetch again with fresh stub (same payload, new call list)
        client2 = StubHttpClient(payload=_rss_bytes("rss_sample.xml"))
        fetcher2 = NitterFetcher("user", client=client2)
        articles_second = fetcher2.fetch()

        assert all("twitter" in a.tags for a in articles_second)
        assert all(a.tags.count("twitter") == 1 for a in articles_second)


# ---------------------------------------------------------------------------
# (d) Delegation: verifies constructed URL is fetched, not that XML is re-parsed
# ---------------------------------------------------------------------------

class TestDelegation:
    def test_constructed_url_is_passed_to_client(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("naval", nitter_base_url="https://nitter.net", client=client)

        fetcher.fetch()

        assert "https://nitter.net/naval/rss" in client.calls

    def test_explicit_url_overrides_constructed_url(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("naval", client=client)

        fetcher.fetch(url="https://override.example.com/naval/rss")

        # Only the explicit override URL must be fetched
        assert client.calls == ["https://override.example.com/naval/rss"]
        assert "nitter.net" not in client.calls[0]

    def test_explicit_url_still_tags_articles_twitter(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("user", client=client)

        articles = fetcher.fetch(url="https://override.example.com/user/rss")

        assert all("twitter" in a.tags for a in articles)

    def test_client_is_shared_between_nitter_and_rss(self) -> None:
        # RSSFetcher inside NitterFetcher must use the same injected client,
        # so the stub intercepts the actual HTTP call made by RSS delegation.
        client = StubHttpClient()
        fetcher = NitterFetcher("user", client=client)

        fetcher.fetch()

        # One call must have been made (through RSShared client, not a new one)
        assert len(client.calls) == 1

    def test_no_additional_http_calls_beyond_rss_fetch(self) -> None:
        client = StubHttpClient()
        fetcher = NitterFetcher("user", client=client)

        fetcher.fetch()
        fetcher.fetch()

        # Two fetches → two calls; delegation must not make extra calls per fetch
        assert len(client.calls) == 2

    def test_rss_parsing_produces_correct_article_count(self) -> None:
        # rss_sample.xml has 2 items; verify delegation passes them through
        client = StubHttpClient(payload=_rss_bytes("rss_sample.xml"))
        fetcher = NitterFetcher("user", client=client)

        articles = fetcher.fetch()

        assert len(articles) == 2

    def test_rss_parsing_produces_correct_article_count_left_fixture(self) -> None:
        # rss_left.xml has 1 item
        client = StubHttpClient(payload=_rss_bytes("rss_left.xml"))
        fetcher = NitterFetcher("leftuser", client=client)

        articles = fetcher.fetch()

        assert len(articles) == 1

    def test_article_titles_match_fixture_content(self) -> None:
        client = StubHttpClient(payload=_rss_bytes("rss_sample.xml"))
        fetcher = NitterFetcher("user", client=client)

        articles = fetcher.fetch()

        titles = {a.title for a in articles}
        assert "Bitcoin Surges Past Key Resistance Level" in titles
        assert "AI Research Breakthrough Reported by DeepMind" in titles

    def test_empty_rss_channel_returns_empty_list(self) -> None:
        empty_feed = b'<?xml version="1.0"?><rss version="2.0"><channel><title>Empty</title></channel></rss>'
        client = StubHttpClient(payload=empty_feed)
        fetcher = NitterFetcher("user", client=client)

        articles = fetcher.fetch()

        assert articles == []

    def test_no_channel_element_returns_empty_list(self) -> None:
        bad_feed = b'<?xml version="1.0"?><rss version="2.0"></rss>'
        client = StubHttpClient(payload=bad_feed)
        fetcher = NitterFetcher("user", client=client)

        articles = fetcher.fetch()

        assert articles == []

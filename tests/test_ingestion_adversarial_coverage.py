"""Adversarial coverage — parametrized matrix over all ingestion fetcher classes × hostile payloads.

Every fetcher must be resilient to the four canonical bad HTTP payloads:

    b""                  – empty response body
    b"<html>404</html>"  – HTML error page instead of JSON/XML
    b"{broken"           – truncated / malformed JSON
    b"<x>"               – truncated / non-well-formed XML fragment

No fetcher should raise; each must return a list ([] for pure-parse fetchers;
a list of articles with empty price fields for YahooFinanceScraper, which always
creates an article record from the symbol label even when the HTML has no data).
"""

from __future__ import annotations

import pytest

from situation_monitor.ingestion.bluesky import BlueskyFetcher
from situation_monitor.ingestion.crypto import CryptoRSSFetcher
from situation_monitor.ingestion.discourse_carrier import CarrierDef, DiscourseCarrierFetcher
from situation_monitor.ingestion.github_trending import GitHubTrendingFetcher
from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.ingestion.mastodon import MastodonFetcher
from situation_monitor.ingestion.nitter import NitterFetcher
from situation_monitor.ingestion.reddit import RedditScraper
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.ingestion.yahoo_finance import YahooFinanceScraper


# ---------------------------------------------------------------------------
# Stub HTTP client — always returns a fixed payload, never hits the network
# ---------------------------------------------------------------------------

class _StubClient:
    """Returns a fixed bytes payload for any GET call."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        return self._payload


# ---------------------------------------------------------------------------
# Hostile payloads (the four canonical bad-response shapes)
# ---------------------------------------------------------------------------

HOSTILE_PAYLOADS: list[pytest.param] = [
    pytest.param(b"", id="empty-bytes"),
    pytest.param(b"<html>404</html>", id="html-error-page"),
    pytest.param(b"{broken", id="truncated-json"),
    pytest.param(b"<x>", id="malformed-xml"),
]

# ---------------------------------------------------------------------------
# Fetcher factories
#
# Each factory takes a StubClient and returns a zero-argument callable whose
# return value is the fetch() result.  This lets the parametrised test stay
# uniform: it never needs to know the calling convention of each fetcher.
#
# expect_empty=True  → the fetcher MUST return [] on any hostile payload
#                      (JSON / XML / HTML parsers all gracefully degrade)
# expect_empty=False → the fetcher MAY return a non-empty list even for hostile
#                      payloads (YahooFinanceScraper always creates an article
#                      record from the symbol label regardless of HTML content)
# ---------------------------------------------------------------------------

def _make_hn(client: _StubClient):
    return lambda: HNFetcher(client=client).fetch("https://hn.algolia.com/api/v1/search")


def _make_reddit(client: _StubClient):
    return lambda: RedditScraper(client=client).fetch("programming")


def _make_rss(client: _StubClient):
    return lambda: RSSFetcher(client=client).fetch("https://example.com/feed.rss")


def _make_bluesky(client: _StubClient):
    return lambda: BlueskyFetcher("user.bsky.social", client=client).fetch()


def _make_mastodon(client: _StubClient):
    # Pass an explicit url so the fetcher does not need network access to
    # build the RSS URL from the instance name.
    return lambda: MastodonFetcher(
        "user@mastodon.social", client=client
    ).fetch("https://mastodon.social/@user.rss")


def _make_nitter(client: _StubClient):
    return lambda: NitterFetcher(
        "twitterhandle", client=client
    ).fetch("https://nitter.net/twitterhandle/rss")


def _make_crypto(client: _StubClient):
    return lambda: CryptoRSSFetcher(client=client).fetch("https://example.com/crypto.rss")


def _make_github(client: _StubClient):
    return lambda: GitHubTrendingFetcher(client=client).fetch("https://github.com/trending")


def _make_discourse(client: _StubClient):
    # Use a single-entry roster so the client is exercised exactly once.
    roster = [CarrierDef("https://example.com/rss.xml", "XX", "centre")]
    return lambda: DiscourseCarrierFetcher(roster=roster, client=client).fetch()


def _make_yahoo(client: _StubClient):
    # Pass a known symbol; the fetcher creates an Article from the label even
    # when the HTML yields no price data, so expect_empty is False.
    return lambda: YahooFinanceScraper(client=client).fetch(["CL=F"])


# (factory, expect_empty)
_FETCHER_CASES: list[tuple] = [
    (_make_hn,        True,  "HNFetcher"),
    (_make_reddit,    True,  "RedditScraper"),
    (_make_rss,       True,  "RSSFetcher"),
    (_make_bluesky,   True,  "BlueskyFetcher"),
    (_make_mastodon,  True,  "MastodonFetcher"),
    (_make_nitter,    True,  "NitterFetcher"),
    (_make_crypto,    True,  "CryptoRSSFetcher"),
    (_make_github,    True,  "GitHubTrendingFetcher"),
    (_make_discourse, True,  "DiscourseCarrierFetcher"),
    (_make_yahoo,     False, "YahooFinanceScraper"),
]

FETCHER_CASES: list[pytest.param] = [
    pytest.param(factory, expect_empty, id=name)
    for factory, expect_empty, name in _FETCHER_CASES
]

# ---------------------------------------------------------------------------
# The main adversarial parametrised test
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("payload", HOSTILE_PAYLOADS)
@pytest.mark.parametrize("make_fetcher,expect_empty", FETCHER_CASES)
def test_hostile_payload_never_raises(
    make_fetcher,
    expect_empty: bool,
    payload: bytes,
) -> None:
    """Hostile HTTP payload must never cause a fetcher to raise.

    The fetcher is expected to return a list in all cases.  For every fetcher
    except YahooFinanceScraper the list must be empty, because none of the four
    payloads can be parsed as valid JSON / RSS / HTML-with-trending-repos.
    """
    client = _StubClient(payload)
    call = make_fetcher(client)

    # The core contract: no exception is raised.
    result = call()

    assert isinstance(result, list), (
        f"fetch() returned {type(result).__name__!r} instead of list "
        f"for payload {payload!r}"
    )
    if expect_empty:
        assert result == [], (
            f"expected [] for hostile payload {payload!r} but got {len(result)} article(s)"
        )


# ---------------------------------------------------------------------------
# Targeted regression: each new payload variant × each fetcher individually
#
# These are separate from the parametrised matrix above so that a targeted
# failure is immediately legible without reading combined param IDs.
# ---------------------------------------------------------------------------

class TestEmptyBytesAllFetchers:
    """b'' — empty response body."""

    def test_hn(self) -> None:
        result = HNFetcher(client=_StubClient(b"")).fetch("https://example.com")
        assert result == []

    def test_reddit(self) -> None:
        result = RedditScraper(client=_StubClient(b"")).fetch("worldnews")
        assert result == []

    def test_rss(self) -> None:
        result = RSSFetcher(client=_StubClient(b"")).fetch("https://example.com/rss")
        assert result == []

    def test_bluesky(self) -> None:
        result = BlueskyFetcher("a.bsky.social", client=_StubClient(b"")).fetch()
        assert result == []

    def test_mastodon(self) -> None:
        result = MastodonFetcher(
            "u@mast.social", client=_StubClient(b"")
        ).fetch("https://mast.social/@u.rss")
        assert result == []

    def test_nitter(self) -> None:
        result = NitterFetcher("h", client=_StubClient(b"")).fetch("https://n.net/h/rss")
        assert result == []

    def test_crypto(self) -> None:
        result = CryptoRSSFetcher(client=_StubClient(b"")).fetch("https://example.com/c.rss")
        assert result == []

    def test_github_trending(self) -> None:
        result = GitHubTrendingFetcher(client=_StubClient(b"")).fetch("https://github.com/trending")
        assert result == []

    def test_discourse_carrier(self) -> None:
        roster = [CarrierDef("https://example.com/rss.xml", "US", "right")]
        result = DiscourseCarrierFetcher(roster=roster, client=_StubClient(b"")).fetch()
        assert result == []

    def test_yahoo_finance_no_symbols(self) -> None:
        result = YahooFinanceScraper(client=_StubClient(b"")).fetch([])
        assert result == []

    def test_yahoo_finance_with_symbol_returns_list(self) -> None:
        result = YahooFinanceScraper(client=_StubClient(b"")).fetch(["GC=F"])
        assert isinstance(result, list)


class TestHtmlErrorPageAllFetchers:
    """b'<html>404</html>' — HTML error page masquerading as feed content."""

    def test_hn(self) -> None:
        result = HNFetcher(client=_StubClient(b"<html>404</html>")).fetch("https://example.com")
        assert result == []

    def test_reddit(self) -> None:
        result = RedditScraper(client=_StubClient(b"<html>404</html>")).fetch("tech")
        assert result == []

    def test_rss(self) -> None:
        result = RSSFetcher(client=_StubClient(b"<html>404</html>")).fetch("https://example.com/rss")
        assert result == []

    def test_bluesky(self) -> None:
        result = BlueskyFetcher("b.bsky.social", client=_StubClient(b"<html>404</html>")).fetch()
        assert result == []

    def test_mastodon(self) -> None:
        result = MastodonFetcher(
            "v@mast.social", client=_StubClient(b"<html>404</html>")
        ).fetch("https://mast.social/@v.rss")
        assert result == []

    def test_nitter(self) -> None:
        result = NitterFetcher(
            "h2", client=_StubClient(b"<html>404</html>")
        ).fetch("https://n.net/h2/rss")
        assert result == []

    def test_crypto(self) -> None:
        result = CryptoRSSFetcher(
            client=_StubClient(b"<html>404</html>")
        ).fetch("https://example.com/c.rss")
        assert result == []

    def test_github_trending(self) -> None:
        result = GitHubTrendingFetcher(
            client=_StubClient(b"<html>404</html>")
        ).fetch("https://github.com/trending")
        assert result == []

    def test_discourse_carrier(self) -> None:
        roster = [CarrierDef("https://feeds.bbci.co.uk/news/rss.xml", "GB", "centre")]
        result = DiscourseCarrierFetcher(
            roster=roster, client=_StubClient(b"<html>404</html>")
        ).fetch()
        assert result == []


class TestTruncatedJsonAllFetchers:
    """b'{broken' — partial JSON, simulates a connection dropped mid-response."""

    def test_hn(self) -> None:
        result = HNFetcher(client=_StubClient(b"{broken")).fetch("https://example.com")
        assert result == []

    def test_reddit(self) -> None:
        result = RedditScraper(client=_StubClient(b"{broken")).fetch("science")
        assert result == []

    def test_rss(self) -> None:
        result = RSSFetcher(client=_StubClient(b"{broken")).fetch("https://example.com/rss")
        assert result == []

    def test_bluesky(self) -> None:
        result = BlueskyFetcher("c.bsky.social", client=_StubClient(b"{broken")).fetch()
        assert result == []

    def test_mastodon(self) -> None:
        result = MastodonFetcher(
            "w@mast.social", client=_StubClient(b"{broken")
        ).fetch("https://mast.social/@w.rss")
        assert result == []

    def test_nitter(self) -> None:
        result = NitterFetcher(
            "h3", client=_StubClient(b"{broken")
        ).fetch("https://n.net/h3/rss")
        assert result == []

    def test_crypto(self) -> None:
        result = CryptoRSSFetcher(
            client=_StubClient(b"{broken")
        ).fetch("https://example.com/c.rss")
        assert result == []

    def test_github_trending(self) -> None:
        result = GitHubTrendingFetcher(
            client=_StubClient(b"{broken")
        ).fetch("https://github.com/trending")
        assert result == []

    def test_discourse_carrier(self) -> None:
        roster = [CarrierDef("https://example.com/rss.xml", "DE", "state")]
        result = DiscourseCarrierFetcher(
            roster=roster, client=_StubClient(b"{broken")
        ).fetch()
        assert result == []


class TestMalformedXmlAllFetchers:
    """b'<x>' — unclosed XML tag, simulates a truncated XML body."""

    def test_hn(self) -> None:
        result = HNFetcher(client=_StubClient(b"<x>")).fetch("https://example.com")
        assert result == []

    def test_reddit(self) -> None:
        result = RedditScraper(client=_StubClient(b"<x>")).fetch("askreddit")
        assert result == []

    def test_rss(self) -> None:
        result = RSSFetcher(client=_StubClient(b"<x>")).fetch("https://example.com/rss")
        assert result == []

    def test_bluesky(self) -> None:
        result = BlueskyFetcher("d.bsky.social", client=_StubClient(b"<x>")).fetch()
        assert result == []

    def test_mastodon(self) -> None:
        result = MastodonFetcher(
            "x@mast.social", client=_StubClient(b"<x>")
        ).fetch("https://mast.social/@x.rss")
        assert result == []

    def test_nitter(self) -> None:
        result = NitterFetcher(
            "h4", client=_StubClient(b"<x>")
        ).fetch("https://n.net/h4/rss")
        assert result == []

    def test_crypto(self) -> None:
        result = CryptoRSSFetcher(
            client=_StubClient(b"<x>")
        ).fetch("https://example.com/c.rss")
        assert result == []

    def test_github_trending(self) -> None:
        result = GitHubTrendingFetcher(
            client=_StubClient(b"<x>")
        ).fetch("https://github.com/trending")
        assert result == []

    def test_discourse_carrier(self) -> None:
        roster = [CarrierDef("https://example.com/rss.xml", "FR", "state")]
        result = DiscourseCarrierFetcher(
            roster=roster, client=_StubClient(b"<x>")
        ).fetch()
        assert result == []


# ---------------------------------------------------------------------------
# Boundary tests: multi-carrier DiscourseCarrierFetcher with mixed failures
# ---------------------------------------------------------------------------

class TestDiscourseCarrierHostileMultiRoster:
    """DiscourseCarrierFetcher with several carriers all returning hostile payloads."""

    @pytest.mark.parametrize("payload", [b"", b"<html>404</html>", b"{broken", b"<x>"])
    def test_multi_carrier_all_hostile(self, payload: bytes) -> None:
        roster = [
            CarrierDef("https://feeds.bbci.co.uk/news/world/rss.xml", "GB", "centre"),
            CarrierDef("https://www.france24.com/en/rss", "FR", "state"),
            CarrierDef("https://rss.dw.com/rdf/rss-en-all", "DE", "state"),
        ]
        result = DiscourseCarrierFetcher(roster=roster, client=_StubClient(payload)).fetch()
        assert result == []


# ---------------------------------------------------------------------------
# Boundary tests: YahooFinanceScraper never raises regardless of HTML shape
# ---------------------------------------------------------------------------

class TestYahooFinanceHostile:
    """YahooFinanceScraper: always returns a list, never raises."""

    @pytest.mark.parametrize("payload", [b"", b"<html>404</html>", b"{broken", b"<x>"])
    def test_always_returns_list(self, payload: bytes) -> None:
        result = YahooFinanceScraper(client=_StubClient(payload)).fetch(["CL=F", "GC=F"])
        assert isinstance(result, list)

    @pytest.mark.parametrize("payload", [b"", b"<html>404</html>", b"{broken", b"<x>"])
    def test_empty_symbols_always_returns_empty(self, payload: bytes) -> None:
        result = YahooFinanceScraper(client=_StubClient(payload)).fetch([])
        assert result == []

    @pytest.mark.parametrize("payload", [b"", b"<html>404</html>", b"{broken", b"<x>"])
    def test_articles_have_non_empty_title(self, payload: bytes) -> None:
        result = YahooFinanceScraper(client=_StubClient(payload)).fetch(["CL=F"])
        assert len(result) == 1
        assert result[0].title  # label always provides a non-empty title

    @pytest.mark.parametrize("payload", [b"", b"<html>404</html>", b"{broken", b"<x>"])
    def test_articles_have_correct_source(self, payload: bytes) -> None:
        result = YahooFinanceScraper(client=_StubClient(payload)).fetch(["EURUSD=X"])
        assert result[0].source == "yahoo_finance"


# ---------------------------------------------------------------------------
# Boundary tests: GitHubTrendingFetcher handles bytes decode edge cases
# ---------------------------------------------------------------------------

class TestGitHubTrendingHostile:
    """GitHubTrendingFetcher decodes bytes before feeding the HTML parser."""

    def test_non_utf8_bytes_returns_empty(self) -> None:
        # Bytes that are invalid UTF-8; decode(errors="replace") must not crash.
        result = GitHubTrendingFetcher(
            client=_StubClient(b"\xff\xfe\x00")
        ).fetch("https://github.com/trending")
        assert isinstance(result, list)

    def test_html_without_articles_returns_empty(self) -> None:
        html = b"<html><body><p>No trending repos today</p></body></html>"
        result = GitHubTrendingFetcher(
            client=_StubClient(html)
        ).fetch("https://github.com/trending")
        assert result == []

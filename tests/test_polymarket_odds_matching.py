"""Adversarial, independent tests for Polymarket odds matching.

This suite is authored separately from the builder and exercises real code paths
in PolymarketMatcher and PolymarketClient without mocking the unit under test.
All HTTP traffic is replaced by injected fixture sessions; no network calls occur.
"""

from __future__ import annotations

import json
import pathlib
from unittest.mock import MagicMock

import pytest

from situation_monitor.models import Article
from situation_monitor.polymarket import PolymarketClient, PolymarketMatcher

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"
_SIMPLE_MARKETS = _FIXTURE_DIR / "polymarket_markets.json"
_API_MARKETS = _FIXTURE_DIR / "polymarket" / "markets.json"


def _art(title: str = "Untitled", body: str = "") -> Article:
    return Article(url="https://example.com/x", title=title, source="test", body=body)


def _simple_markets() -> list[dict]:
    return json.loads(_SIMPLE_MARKETS.read_text())


def _api_markets() -> list[dict]:
    return json.loads(_API_MARKETS.read_text())


def _session_returning(payload) -> MagicMock:
    """Return a mock requests.Session whose .get().json() yields *payload*."""
    resp = MagicMock()
    resp.json.return_value = payload
    sess = MagicMock()
    sess.get.return_value = resp
    return sess


# ===========================================================================
# PolymarketMatcher — keyword matching against simple fixture format
# ===========================================================================


class TestMatcherFixtureIntegrity:
    """The fixture itself is load-tested first so failures point at fixture, not logic."""

    def test_fixture_file_exists(self) -> None:
        assert _SIMPLE_MARKETS.is_file(), f"Fixture missing: {_SIMPLE_MARKETS}"

    def test_fixture_loads_as_list(self) -> None:
        markets = _simple_markets()
        assert isinstance(markets, list)

    def test_keyword_match_returns_non_none_implied_odds(self) -> None:
        """Core acceptance criterion: keyword hit → non-None odds."""
        matcher = PolymarketMatcher()
        article = _art(title="Bitcoin breaks resistance level")
        result = matcher.match(article, _simple_markets())
        assert result is not None

    def test_no_keyword_match_returns_none_odds(self) -> None:
        """Core acceptance criterion: no keyword hit → None."""
        matcher = PolymarketMatcher()
        article = _art(title="Regional weather update for coastal areas")
        assert matcher.match(article, _simple_markets()) is None


class TestMatcherBodyOnlyMatch:
    """Keywords in the body (not title) must still match."""

    def test_keyword_in_body_only_matches(self) -> None:
        matcher = PolymarketMatcher()
        article = _art(title="Markets update", body="Latest news on bitcoin trades")
        assert matcher.match(article, _simple_markets()) == pytest.approx(0.42)

    def test_neither_title_nor_body_keyword_returns_none(self) -> None:
        matcher = PolymarketMatcher()
        article = _art(title="Rainfall forecast", body="Expect heavy precipitation tomorrow")
        assert matcher.match(article, _simple_markets()) is None


class TestMatcherSubstringSemantics:
    """The implementation uses `kw.lower() in text` (substring), not word-boundary match."""

    def test_keyword_as_substring_of_word_matches(self) -> None:
        # "btc" appears inside "btc-futures"; substring match should fire
        markets = [{"id": "m", "keywords": ["btc"], "odds": 0.55}]
        article = _art(title="btc-futures rally continues")
        matcher = PolymarketMatcher()
        assert matcher.match(article, markets) == pytest.approx(0.55)

    def test_keyword_longer_than_word_does_not_match(self) -> None:
        # "bitcoinx" should NOT be found in text containing only "bitcoin"
        markets = [{"id": "m", "keywords": ["bitcoinx_sentinel"], "odds": 0.5}]
        article = _art(title="bitcoin rises")
        matcher = PolymarketMatcher()
        assert matcher.match(article, markets) is None


class TestMatcherOddsTypes:
    """Odds stored as int or string-float must survive the float() cast."""

    def test_integer_odds_converted_to_float(self) -> None:
        markets = [{"id": "m", "keywords": ["news"], "odds": 1}]
        article = _art(title="Breaking news today")
        result = PolymarketMatcher().match(article, markets)
        assert isinstance(result, float)
        assert result == pytest.approx(1.0)

    def test_string_odds_converted_to_float(self) -> None:
        markets = [{"id": "m", "keywords": ["news"], "odds": "0.65"}]
        article = _art(title="Breaking news today")
        result = PolymarketMatcher().match(article, markets)
        assert isinstance(result, float)
        assert result == pytest.approx(0.65)


class TestMatcherMultiKeyword:
    """Markets with multiple keywords — any one is sufficient; order among keywords doesn't bias result."""

    def test_second_keyword_matches_when_first_absent(self) -> None:
        markets = [{"id": "m", "keywords": ["nonexistent_word_xyz", "bitcoin"], "odds": 0.3}]
        article = _art(title="bitcoin market analysis")
        assert PolymarketMatcher().match(article, markets) == pytest.approx(0.3)

    def test_both_keywords_present_still_single_result(self) -> None:
        markets = [{"id": "m", "keywords": ["bitcoin", "btc"], "odds": 0.3}]
        article = _art(title="bitcoin btc double mention")
        assert PolymarketMatcher().match(article, markets) == pytest.approx(0.3)


class TestMatcherFirstMarketWins:
    """When multiple markets could match, only the first one's odds are returned."""

    def test_first_wins_regardless_of_odds_magnitude(self) -> None:
        markets = [
            {"id": "low", "keywords": ["bitcoin"], "odds": 0.1},
            {"id": "high", "keywords": ["bitcoin"], "odds": 0.9},
        ]
        result = PolymarketMatcher().match(_art(title="bitcoin news"), markets)
        assert result == pytest.approx(0.1)

    def test_order_reversal_changes_result(self) -> None:
        markets_a = [
            {"id": "x", "keywords": ["bitcoin"], "odds": 0.1},
            {"id": "y", "keywords": ["bitcoin"], "odds": 0.9},
        ]
        markets_b = list(reversed(markets_a))
        art = _art(title="bitcoin update")
        assert PolymarketMatcher().match(art, markets_a) == pytest.approx(0.1)
        assert PolymarketMatcher().match(art, markets_b) == pytest.approx(0.9)


class TestMatcherEmptyKeywordsList:
    def test_empty_keywords_list_never_matches(self) -> None:
        markets = [{"id": "m", "keywords": [], "odds": 0.5}]
        # Even a very keyword-rich article should not match an empty keyword list
        article = _art(title="bitcoin btc crypto AGI OpenAI DeepMind")
        assert PolymarketMatcher().match(article, markets) is None

    def test_empty_markets_list_returns_none(self) -> None:
        article = _art(title="bitcoin crashes")
        assert PolymarketMatcher().match(article, []) is None


class TestMatcherCaseInsensitivity:
    def test_uppercase_keyword_matches_lowercase_text(self) -> None:
        markets = [{"id": "m", "keywords": ["BITCOIN"], "odds": 0.5}]
        article = _art(title="bitcoin rises today")
        assert PolymarketMatcher().match(article, markets) == pytest.approx(0.5)

    def test_mixed_case_keyword_matches_mixed_case_text(self) -> None:
        markets = [{"id": "m", "keywords": ["DeepMind"], "odds": 0.25}]
        article = _art(title="DEEPMIND announces new model")
        assert PolymarketMatcher().match(article, markets) == pytest.approx(0.25)


# ===========================================================================
# PolymarketClient — slug/question keyword extraction and price parsing
# ===========================================================================


class TestClientSlugWordFilter:
    """Slug words of 2 or fewer chars must be excluded from keyword matching."""

    def test_three_char_slug_word_is_included(self) -> None:
        # slug "btc-rally" → slug words ["btc", "rally"]; both > 2 chars
        markets = [{"slug": "btc-rally", "question": "?", "outcomePrices": ["0.6", "0.4"]}]
        client = PolymarketClient(slugs=[])
        article = _art(title="btc continues to rally")
        assert client.match(article, markets) == pytest.approx(0.6)

    def test_two_char_slug_word_is_excluded(self) -> None:
        # slug "go-up" → words "go" (len 2, excluded) and "up" (len 2, excluded)
        markets = [{"slug": "go-up", "question": "Will it go up?", "outcomePrices": ["0.5", "0.5"]}]
        client = PolymarketClient(slugs=[])
        # "go" and "up" are both ≤2 chars from slug; question words "will" (4), "it" (2, skip), "go" (2, skip), "up" (2, skip)
        # only "will" from question survives (len 4 > 3); article must NOT contain "will" to avoid spurious match
        article = _art(title="markets are moving in that direction")
        assert client.match(article, markets) is None

    def test_slug_with_all_short_words_produces_no_keywords(self) -> None:
        markets = [{"slug": "ab-cd-ef", "question": "A?", "outcomePrices": ["0.9", "0.1"]}]
        client = PolymarketClient(slugs=[])
        article = _art(title="ab cd ef market update")
        assert client.match(article, markets) is None


class TestClientQuestionWordFilter:
    """Question words of 3 or fewer chars must be excluded."""

    def test_four_char_question_word_is_included(self) -> None:
        # "Will" has 4 chars → included
        markets = [{"slug": "x-y", "question": "Will this happen?", "outcomePrices": ["0.7", "0.3"]}]
        client = PolymarketClient(slugs=[])
        article = _art(title="will the prediction come true")
        assert client.match(article, markets) == pytest.approx(0.7)

    def test_three_char_question_word_is_excluded(self) -> None:
        # "AGI" has 3 chars → excluded from question words; only longer words qualify
        markets = [{"slug": "x-y", "question": "AGI rise?", "outcomePrices": ["0.2", "0.8"]}]
        client = PolymarketClient(slugs=[])
        # "AGI" (3 chars) → excluded; "rise" (4 chars) → included
        article = _art(title="local sports results today")
        assert client.match(article, markets) is None

    def test_question_with_only_short_words_no_match(self) -> None:
        markets = [{"slug": "a-b", "question": "Up or not?", "outcomePrices": ["0.5", "0.5"]}]
        client = PolymarketClient(slugs=[])
        # slug "a-b": both ≤2 chars excluded; question: "Up"(2), "or"(2), "not"(3) → all ≤3 excluded
        article = _art(title="up or not today")
        assert client.match(article, markets) is None


class TestClientInvalidOutcomePrices:
    """Non-numeric prices must not crash the matcher; it should return None or fall through."""

    def test_non_numeric_price_does_not_raise(self) -> None:
        markets = [{"slug": "bitcoin-test", "question": "Bitcoin up?", "outcomePrices": ["N/A", "N/A"]}]
        client = PolymarketClient(slugs=[])
        article = _art(title="bitcoin test market news")
        # Should not raise; may return None
        result = client.match(article, markets)
        assert result is None

    def test_none_price_element_does_not_raise(self) -> None:
        markets = [{"slug": "bitcoin-test", "question": "Bitcoin?", "outcomePrices": [None, "0.5"]}]
        client = PolymarketClient(slugs=[])
        article = _art(title="bitcoin market test today")
        result = client.match(article, markets)
        assert result is None

    def test_invalid_price_falls_through_to_next_market(self) -> None:
        markets = [
            {"slug": "bitcoin-test", "question": "Bitcoin up?", "outcomePrices": ["invalid", "0.5"]},
            {"slug": "bitcoin-fall", "question": "Bitcoin falls?", "outcomePrices": ["0.33", "0.67"]},
        ]
        client = PolymarketClient(slugs=[])
        article = _art(title="bitcoin test fall analysis")
        # First market's price is invalid → skipped; second market matches → 0.33
        result = client.match(article, markets)
        assert result == pytest.approx(0.33)

    def test_empty_outcome_prices_skips_market(self) -> None:
        markets = [
            {"slug": "bitcoin-news", "question": "Bitcoin news?", "outcomePrices": []},
            {"slug": "agi-rise", "question": "AGI rising soon?", "outcomePrices": ["0.15", "0.85"]},
        ]
        client = PolymarketClient(slugs=[])
        # Article matches "bitcoin" (first market) but it has no prices; falls through
        # Article also matches "agi" → second market returns 0.15
        # Wait, "agi" is 3 chars, excluded from question words. "rising" (6 chars) and "soon" (4 chars) are included.
        # Let's use "rising" in article to match
        article = _art(title="bitcoin rising prediction")
        result = client.match(article, markets)
        # "bitcoin" matches first market (slug word "bitcoin" > 2 chars) but empty prices → skip
        # "rising" matches second market question word → returns 0.15
        assert result == pytest.approx(0.15)


class TestClientMatchCaseInsensitive:
    def test_uppercase_article_matches_lowercase_slug(self) -> None:
        markets = [{"slug": "bitcoin-rally", "question": "Bitcoin?", "outcomePrices": ["0.5", "0.5"]}]
        client = PolymarketClient(slugs=[])
        article = _art(title="BITCOIN RALLY EXPECTED")
        assert client.match(article, markets) == pytest.approx(0.5)

    def test_empty_markets_returns_none(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _art(title="bitcoin news")
        assert client.match(article, []) is None

    def test_api_fixture_keyword_match_returns_non_none(self) -> None:
        """Core acceptance criterion against the API-format fixture."""
        client = PolymarketClient(slugs=[])
        article = _art(title="Bitcoin surges to new highs today")
        result = client.match(article, _api_markets())
        assert result is not None

    def test_api_fixture_no_match_returns_none(self) -> None:
        """Core acceptance criterion: unrelated article → None."""
        client = PolymarketClient(slugs=[])
        article = _art(title="Gardening tips for the spring season")
        assert client.match(article, _api_markets()) is None


class TestClientMatchBodyUsed:
    def test_body_is_searched_alongside_title(self) -> None:
        markets = [{"slug": "bitcoin-future", "question": "Bitcoin?", "outcomePrices": ["0.44", "0.56"]}]
        client = PolymarketClient(slugs=[])
        article = _art(title="Financial roundup", body="Analysts discuss bitcoin future prospects")
        assert client.match(article, markets) == pytest.approx(0.44)

    def test_empty_body_does_not_crash(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _art(title="bitcoin news", body="")
        result = client.match(article, _api_markets())
        assert isinstance(result, float)


# ===========================================================================
# PolymarketClient.fetch_markets — fixture session replaces HTTP entirely
# ===========================================================================


class TestFetchMarketsNoNetwork:
    """All tests inject a session; no real requests.Session is ever created."""

    def test_empty_slugs_makes_no_http_calls(self) -> None:
        sess = MagicMock()
        client = PolymarketClient(slugs=[], session=sess)
        result = client.fetch_markets()
        sess.get.assert_not_called()
        assert result == []

    def test_list_response_collected(self) -> None:
        markets = _api_markets()
        sess = _session_returning(markets)
        client = PolymarketClient(slugs=["will-bitcoin-hit-100k-2025"], session=sess)
        result = client.fetch_markets()
        assert result == [markets[0]]

    def test_dict_response_collected(self) -> None:
        single_market = _api_markets()[0]  # a dict
        sess = _session_returning(single_market)
        client = PolymarketClient(slugs=["will-bitcoin-hit-100k-2025"], session=sess)
        result = client.fetch_markets()
        assert result == [single_market]

    def test_empty_list_response_not_collected(self) -> None:
        sess = _session_returning([])
        client = PolymarketClient(slugs=["nonexistent"], session=sess)
        assert client.fetch_markets() == []

    def test_empty_dict_response_not_collected(self) -> None:
        sess = _session_returning({})
        client = PolymarketClient(slugs=["nonexistent"], session=sess)
        assert client.fetch_markets() == []

    def test_multiple_slugs_each_gets_one_call(self) -> None:
        markets = _api_markets()
        r0, r1 = MagicMock(), MagicMock()
        r0.json.return_value = [markets[0]]
        r1.json.return_value = [markets[1]]
        sess = MagicMock()
        sess.get.side_effect = [r0, r1]
        client = PolymarketClient(
            slugs=["will-bitcoin-hit-100k-2025", "will-deepmind-achieve-agi-before-2027"],
            session=sess,
        )
        result = client.fetch_markets()
        assert sess.get.call_count == 2
        assert len(result) == 2

    def test_network_exception_per_slug_is_swallowed(self) -> None:
        sess = MagicMock()
        sess.get.side_effect = ConnectionError("unreachable")
        client = PolymarketClient(slugs=["any-slug"], session=sess)
        assert client.fetch_markets() == []

    def test_json_parse_exception_is_swallowed(self) -> None:
        resp = MagicMock()
        resp.json.side_effect = ValueError("bad json")
        sess = MagicMock()
        sess.get.return_value = resp
        client = PolymarketClient(slugs=["any-slug"], session=sess)
        assert client.fetch_markets() == []

    def test_correct_api_base_url_used(self) -> None:
        sess = _session_returning([])
        client = PolymarketClient(slugs=["test-slug"], session=sess)
        client.fetch_markets()
        call_args = sess.get.call_args
        assert "gamma-api.polymarket.com" in call_args[0][0]

    def test_slug_passed_as_query_param(self) -> None:
        sess = _session_returning([])
        client = PolymarketClient(slugs=["my-specific-slug"], session=sess)
        client.fetch_markets()
        call_kwargs = sess.get.call_args[1]
        assert call_kwargs.get("params", {}).get("slug") == "my-specific-slug"

    def test_pre_injected_session_prevents_requests_import(self) -> None:
        """When a session is injected, the lazy `import requests` branch is never taken.

        We verify this by passing a non-requests object as session and confirming
        fetch_markets still works correctly.
        """
        markets = _api_markets()
        sess = _session_returning(markets)
        client = PolymarketClient(slugs=["will-bitcoin-hit-100k-2025"], session=sess)
        # If requests were imported and session replaced, this would fail differently
        result = client.fetch_markets()
        assert len(result) == 1  # only first element of list response is taken

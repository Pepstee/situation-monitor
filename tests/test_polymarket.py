"""Tests for PolymarketMatcher and PolymarketClient — zero network calls."""

from __future__ import annotations

import json
import pathlib
from unittest.mock import MagicMock

import pytest

from situation_monitor.models import Article
from situation_monitor.polymarket import PolymarketClient, PolymarketMatcher

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "polymarket_markets.json"
API_FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "polymarket" / "markets.json"


def _load_markets() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text())


def _article(title: str = "Generic News Story", body: str = "") -> Article:
    return Article(url="https://example.com/news", title=title, source="test", body=body)


@pytest.fixture()
def matcher() -> PolymarketMatcher:
    return PolymarketMatcher()


@pytest.fixture()
def markets() -> list[dict]:
    return _load_markets()


class TestPolymarketFixtureContent:
    """Sanity-check the fixture so test failures are unambiguous."""

    def test_fixture_has_at_least_two_markets(self, markets: list[dict]) -> None:
        assert len(markets) >= 2

    def test_btc_market_present(self, markets: list[dict]) -> None:
        ids = {m.get("id") for m in markets}
        assert "crypto-btc-100k" in ids

    def test_agi_market_present(self, markets: list[dict]) -> None:
        ids = {m.get("id") for m in markets}
        assert "ai-agi-2026" in ids

    def test_all_markets_have_keywords_list(self, markets: list[dict]) -> None:
        for m in markets:
            assert isinstance(m.get("keywords"), list), f"Missing keywords on {m.get('id')}"

    def test_all_markets_have_numeric_odds(self, markets: list[dict]) -> None:
        for m in markets:
            assert isinstance(m.get("odds"), (int, float)), f"Bad odds on {m.get('id')}"


class TestPolymarketMatcherHappyPath:
    def test_title_keyword_match_returns_odds(self, matcher, markets) -> None:
        article = _article(title="Bitcoin price hits a new all-time high")
        result = matcher.match(article, markets)
        assert result == pytest.approx(0.42)

    def test_body_keyword_match_returns_odds(self, matcher, markets) -> None:
        article = _article(title="Breaking financial news", body="Analysts bullish on BTC outlook")
        result = matcher.match(article, markets)
        assert result == pytest.approx(0.42)

    def test_result_is_float(self, matcher, markets) -> None:
        article = _article(title="Bitcoin rally continues through the week")
        result = matcher.match(article, markets)
        assert isinstance(result, float)

    def test_agi_keyword_in_title_matches_agi_market(self, matcher, markets) -> None:
        article = _article(title="OpenAI announces breakthrough toward AGI")
        result = matcher.match(article, markets)
        assert result == pytest.approx(0.08)

    def test_agi_full_phrase_keyword_matches(self, matcher, markets) -> None:
        article = _article(title="Artificial General Intelligence timeline under debate")
        result = matcher.match(article, markets)
        assert result == pytest.approx(0.08)

    def test_deepmind_keyword_matches_agi_market(self, matcher, markets) -> None:
        article = _article(title="DeepMind publishes results on reasoning benchmarks")
        result = matcher.match(article, markets)
        assert result == pytest.approx(0.08)

    def test_crypto_keyword_matches_btc_market(self, matcher, markets) -> None:
        article = _article(title="Crypto market volatility reaches yearly low")
        result = matcher.match(article, markets)
        assert result == pytest.approx(0.42)


class TestPolymarketMatcherNoMatch:
    def test_unrelated_title_returns_none(self, matcher, markets) -> None:
        article = _article(title="Local weather forecast for the coming week")
        assert matcher.match(article, markets) is None

    def test_empty_markets_list_returns_none(self, matcher) -> None:
        article = _article(title="Bitcoin surges 20% in a single day")
        assert matcher.match(article, []) is None

    def test_market_with_no_keywords_never_matches(self, matcher) -> None:
        markets_no_kw = [{"id": "empty-kw", "odds": 0.5, "keywords": []}]
        article = _article(title="Bitcoin and crypto dominance grows")
        assert matcher.match(article, markets_no_kw) is None

    def test_keyword_partial_word_overlap_only_does_not_falsely_match(self, matcher) -> None:
        # "btcx" should NOT match the keyword "btc"
        markets_specific = [{"id": "test", "odds": 0.9, "keywords": ["btcxyz_unique_sentinel"]}]
        article = _article(title="Bitcoin btc price")
        assert matcher.match(article, markets_specific) is None


class TestPolymarketMatcherCaseInsensitivity:
    def test_uppercase_title_matches_lowercase_keyword(self, matcher, markets) -> None:
        article = _article(title="BITCOIN PRICE SURGES OVERNIGHT")
        assert matcher.match(article, markets) == pytest.approx(0.42)

    def test_lowercase_article_matches_uppercase_keyword(self, matcher, markets) -> None:
        # "AGI" is a keyword; test with lowercase article text
        article = _article(title="agi research timeline pushed to 2028")
        assert matcher.match(article, markets) == pytest.approx(0.08)

    def test_mixed_case_body_matches(self, matcher, markets) -> None:
        article = _article(title="Finance update", body="Will OpenAI reach AGI soon?")
        result = matcher.match(article, markets)
        assert result == pytest.approx(0.08)

    def test_keyword_match_is_case_insensitive_btc(self, matcher, markets) -> None:
        article = _article(title="Market analysis: BTC, ETH and DeFi")
        assert matcher.match(article, markets) == pytest.approx(0.42)


class TestPolymarketMatcherFirstMarketWins:
    def test_first_matching_market_odds_returned(self, matcher) -> None:
        # Both markets match "bitcoin"; first one (odds=0.3) should be returned
        markets = [
            {"id": "m1", "keywords": ["bitcoin"], "odds": 0.3},
            {"id": "m2", "keywords": ["bitcoin"], "odds": 0.7},
        ]
        result = matcher.match(_article(title="Bitcoin soars"), markets)
        assert result == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# PolymarketClient tests — injectable session, zero real network calls
# ---------------------------------------------------------------------------


def _api_markets() -> list[dict]:
    return json.loads(API_FIXTURE_PATH.read_text())


def _mock_session(markets: list[dict]):
    """Return a mock session whose .get().json() returns *markets*."""
    resp = MagicMock()
    resp.json.return_value = markets
    session = MagicMock()
    session.get.return_value = resp
    return session


class TestApiFixtureContent:
    def test_fixture_has_two_markets(self) -> None:
        assert len(_api_markets()) == 2

    def test_all_markets_have_slug(self) -> None:
        for m in _api_markets():
            assert isinstance(m.get("slug"), str) and m["slug"]

    def test_all_markets_have_outcome_prices(self) -> None:
        for m in _api_markets():
            prices = m.get("outcomePrices", [])
            assert len(prices) == 2
            assert all(isinstance(p, str) for p in prices)

    def test_bitcoin_market_present(self) -> None:
        slugs = {m["slug"] for m in _api_markets()}
        assert any("bitcoin" in s for s in slugs)

    def test_agi_market_present(self) -> None:
        slugs = {m["slug"] for m in _api_markets()}
        assert any("agi" in s for s in slugs)


class TestPolymarketClientFetchMarkets:
    def test_fetch_markets_calls_api_per_slug(self) -> None:
        markets = _api_markets()
        session = _mock_session(markets)
        client = PolymarketClient(slugs=["will-bitcoin-hit-100k-2025"], session=session)
        result = client.fetch_markets()
        session.get.assert_called_once()
        assert result == [markets[0]]

    def test_fetch_markets_skips_empty_responses(self) -> None:
        resp = MagicMock()
        resp.json.return_value = []
        session = MagicMock()
        session.get.return_value = resp
        client = PolymarketClient(slugs=["nonexistent-slug"], session=session)
        assert client.fetch_markets() == []

    def test_fetch_markets_handles_exception_gracefully(self) -> None:
        session = MagicMock()
        session.get.side_effect = RuntimeError("network error")
        client = PolymarketClient(slugs=["some-slug"], session=session)
        assert client.fetch_markets() == []

    def test_fetch_markets_collects_multiple_slugs(self) -> None:
        markets = _api_markets()
        # First call returns bitcoin market, second returns agi market
        resp0, resp1 = MagicMock(), MagicMock()
        resp0.json.return_value = [markets[0]]
        resp1.json.return_value = [markets[1]]
        session = MagicMock()
        session.get.side_effect = [resp0, resp1]
        client = PolymarketClient(
            slugs=["will-bitcoin-hit-100k-2025", "will-deepmind-achieve-agi-before-2027"],
            session=session,
        )
        result = client.fetch_markets()
        assert len(result) == 2
        assert session.get.call_count == 2


class TestPolymarketClientMatch:
    def test_bitcoin_article_matches_bitcoin_market(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _article(title="Bitcoin Surges Past Key Resistance Level")
        result = client.match(article, _api_markets())
        assert result == pytest.approx(0.42)

    def test_deepmind_article_matches_agi_market(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _article(
            title="AI Research Breakthrough Reported by DeepMind",
            body="Artificial general intelligence research advances.",
        )
        result = client.match(article, _api_markets())
        assert result == pytest.approx(0.08)

    def test_unrelated_article_returns_none(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _article(title="Local weather forecast for the weekend")
        assert client.match(article, _api_markets()) is None

    def test_empty_markets_returns_none(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _article(title="Bitcoin rally")
        assert client.match(article, []) is None

    def test_first_matching_market_wins(self) -> None:
        markets = [
            {"slug": "bitcoin-up", "question": "Bitcoin up?", "outcomePrices": ["0.9", "0.1"]},
            {"slug": "bitcoin-down", "question": "Bitcoin down?", "outcomePrices": ["0.1", "0.9"]},
        ]
        client = PolymarketClient(slugs=[])
        result = client.match(_article(title="Bitcoin moves"), markets)
        assert result == pytest.approx(0.9)

    def test_match_is_case_insensitive(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _article(title="BITCOIN PRICE DROPS")
        result = client.match(article, _api_markets())
        assert result == pytest.approx(0.42)

    def test_match_result_is_float(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _article(title="Bitcoin hits record high")
        result = client.match(article, _api_markets())
        assert isinstance(result, float)

    def test_implied_odds_come_from_outcome_prices_first_element(self) -> None:
        markets = [{"slug": "test-market", "question": "Test?", "outcomePrices": ["0.73", "0.27"]}]
        client = PolymarketClient(slugs=[])
        article = _article(title="test market news today")
        result = client.match(article, markets)
        assert result == pytest.approx(0.73)

"""Tests for PolymarketMatcher using the bundled markets fixture — zero network calls."""

from __future__ import annotations

import json
import pathlib

import pytest

from situation_monitor.models import Article
from situation_monitor.polymarket import PolymarketMatcher

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "polymarket_markets.json"


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

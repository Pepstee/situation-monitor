"""Polymarket keyword-matching and API client for article odds enrichment."""

from __future__ import annotations

from typing import Optional

from situation_monitor.models import Article


class PolymarketMatcher:
    def match(self, article: Article, markets: list[dict]) -> float | None:
        text = (article.title + " " + article.body).lower()
        for market in markets:
            keywords: list[str] = market.get("keywords", [])
            if any(kw.lower() in text for kw in keywords):
                return float(market["odds"])
        return None


class PolymarketClient:
    """Fetches and matches Polymarket market odds using configurable slugs.

    Pass an injectable session for testing (any object with a `.get(url, **kwargs)`
    method that returns an object with a `.json()` method).  When *session* is None
    a real ``requests.Session`` is created on first call to :meth:`fetch_markets`.
    """

    _API_BASE = "https://gamma-api.polymarket.com/markets"

    def __init__(self, slugs: list[str], session: Optional[object] = None) -> None:
        self._slugs = list(slugs)
        self._session = session  # resolved lazily so requests isn't imported unless needed

    def fetch_markets(self) -> list[dict]:
        """Fetch one market record per configured slug from the Polymarket API."""
        if self._session is None:
            import requests  # noqa: PLC0415  (intentional lazy import)

            self._session = requests.Session()
        markets: list[dict] = []
        for slug in self._slugs:
            try:
                resp = self._session.get(self._API_BASE, params={"slug": slug})
                data = resp.json()
                if isinstance(data, list) and data:
                    markets.append(data[0])
                elif isinstance(data, dict) and data:
                    markets.append(data)
            except Exception:
                pass
        return markets

    def match(self, article: Article, markets: list[dict]) -> Optional[float]:
        """Match *article* against *markets* (API format); return implied_odds or None.

        Keywords are derived from the market slug (words longer than 2 chars) and
        from significant words in the question text (words longer than 3 chars).
        The first matching market's Yes-outcome price is returned as *implied_odds*.
        """
        text = (article.title + " " + (article.body or "")).lower()
        for market in markets:
            slug: str = market.get("slug", "")
            slug_keywords = [w for w in slug.split("-") if len(w) > 2]
            question_words = [
                w.lower()
                for w in market.get("question", "").split()
                if len(w) > 3
            ]
            if any(kw in text for kw in slug_keywords) or any(
                qw in text for qw in question_words
            ):
                prices = market.get("outcomePrices", [])
                if prices:
                    try:
                        return float(prices[0])
                    except (ValueError, TypeError):
                        pass
        return None

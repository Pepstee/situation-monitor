"""Polymarket keyword-matching and API client for article odds enrichment."""

from __future__ import annotations

from typing import Optional

from situation_monitor.models import Article


class PolymarketMatcher:
    def match(self, article: Article, markets: list[dict]) -> float | None:
        # article.body may be None (upstream feeds leave it unset); guard it the
        # same way PolymarketClient.match and the rest of the pipeline do, so a
        # body-less article degrades to a title-only match instead of crashing
        # with "can only concatenate str (not NoneType) to str".
        text = (article.title + " " + (article.body or "")).lower()
        for market in markets:
            # A malformed market record may carry "keywords": null; coerce to an
            # empty list so iteration degrades to "no match" instead of raising
            # "NoneType is not iterable".
            keywords: list[str] = market.get("keywords") or []
            if any(kw.lower() in text for kw in keywords):
                # A malformed market record may omit "odds" or carry a
                # non-numeric value; skip it rather than raising.
                try:
                    return float(market["odds"])
                except (KeyError, TypeError, ValueError):
                    continue
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
            # The API may return "slug": null or "question": null; `.get(k, "")`
            # still yields None for a present-but-null key, so `or ""` is needed
            # to avoid "NoneType has no attribute 'split'".
            slug: str = market.get("slug") or ""
            slug_keywords = [w for w in slug.split("-") if len(w) > 2]
            question_words = [
                w.lower()
                for w in (market.get("question") or "").split()
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

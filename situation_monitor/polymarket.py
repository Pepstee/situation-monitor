"""Polymarket keyword-matching against article content."""

from __future__ import annotations

from situation_monitor.models import Article


class PolymarketMatcher:
    def match(self, article: Article, markets: list[dict]) -> float | None:
        text = (article.title + " " + article.body).lower()
        for market in markets:
            keywords: list[str] = market.get("keywords", [])
            if any(kw.lower() in text for kw in keywords):
                return float(market["odds"])
        return None

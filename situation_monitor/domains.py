"""Content-based domain classification.

A story's section (WORLD / MARKETS / AI) is a property of what the story is
*about*, not merely of which feed delivered it: a Bitcoin story carried by a
general-news feed is still a markets story, and an AI-research story is an AI
story wherever it appears. This mirrors how real aggregators (Ground News,
AllSides) file an item by topic rather than by source.

`classify_domain` reads the headline and body, matches them against curated
keyword sets with word-boundary precision, and returns the most specific
matching domain (AI → MARKETS → WORLD). When nothing matches it falls back to
the domain the source feed declared, so feed-level tagging is preserved as a
sensible default rather than silently overriding it.
"""

from __future__ import annotations

import re
from typing import Optional

from situation_monitor.models import Article, Domain

# Ordered most-specific first. Each phrase is matched on word boundaries so
# "ai" matches the token "AI" but never the "ai" inside "Spain" or "campaign".
_AI_TERMS = [
    "ai", "agi", "artificial intelligence", "artificial general intelligence",
    "machine learning", "deep learning", "neural network", "neural net",
    "large language model", "llm", "generative ai", "genai",
    "deepmind", "openai", "anthropic", "chatgpt", "gpt", "chatbot",
    "superintelligence", "algorithmic", "algorithm",
]

_MARKETS_TERMS = [
    "bitcoin", "btc", "ethereum", "crypto", "cryptocurrency", "blockchain",
    "stock", "stocks", "equity", "equities", "shares", "share price",
    "market", "markets", "wall street", "nasdaq", "dow jones", "s&p", "ftse",
    "nikkei", "bond", "bonds", "treasury", "yield", "inflation",
    "interest rate", "rate cut", "rate hike", "federal reserve", "central bank",
    "earnings", "ipo", "dividend", "ticker", "forex", "futures", "commodities",
]

_WORLD_TERMS = [
    "government", "election", "president", "prime minister", "parliament",
    "congress", "senate", "war", "military", "troops", "ceasefire", "treaty",
    "summit", "diplomat", "sanctions", "climate", "policy", "protest",
    "refugee", "border", "nuclear", "minister", "embassy", "coup",
]


def _compile(terms: list[str]) -> re.Pattern[str]:
    # Sort longest-first so multi-word phrases get a chance before their parts;
    # alternation order does not affect a boundary-anchored search but it keeps
    # the pattern readable. "s&p" needs escaping; word boundaries still apply.
    alternation = "|".join(re.escape(t) for t in sorted(terms, key=len, reverse=True))
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


_AI_RE = _compile(_AI_TERMS)
_MARKETS_RE = _compile(_MARKETS_TERMS)
_WORLD_RE = _compile(_WORLD_TERMS)


def classify_domain(article: Article, default: Optional[Domain] = None) -> Optional[Domain]:
    """Return the content-derived domain for *article*.

    Precedence is most-specific first: a story matching both AI and MARKETS
    cues (e.g. an "AI chip stock") is filed under AI. When no keyword set
    matches, *default* (typically the feed-declared domain) is returned.
    """
    text = f"{article.title} {article.body or ''}"
    if _AI_RE.search(text):
        return Domain.AI
    if _MARKETS_RE.search(text):
        return Domain.MARKETS
    if _WORLD_RE.search(text):
        return Domain.WORLD
    return default

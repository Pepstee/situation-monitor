"""Deduplication utilities for Article lists."""

from __future__ import annotations

import re

from situation_monitor.models import Article


def _normalise(title: str) -> list[str]:
    """Lowercase, strip punctuation, split into words."""
    cleaned = re.sub(r"[^\w\s]", "", (title or "").lower())
    return cleaned.split()


def deduplicate(articles: list[Article]) -> list[Article]:
    """Remove exact URL duplicates then near-duplicate titles.

    Near-duplicate: normalised titles share the same first 6 words (or all
    words if the title is shorter than 6 words).
    """
    seen_urls: set[str] = set()
    unique: list[Article] = []
    for article in articles:
        if article.url in seen_urls:
            continue
        seen_urls.add(article.url)
        unique.append(article)

    _LEADING = 6
    seen_prefixes: set[tuple[str, ...]] = set()
    deduped: list[Article] = []
    for article in unique:
        words = _normalise(article.title)
        prefix = tuple(words[:_LEADING])
        if prefix and prefix in seen_prefixes:
            continue
        if prefix:
            seen_prefixes.add(prefix)
        deduped.append(article)

    return deduped

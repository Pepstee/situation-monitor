"""Article sanitiser: strip HTML, normalise whitespace, truncate oversized fields."""

from __future__ import annotations

import html
import re

from situation_monitor.models import Article

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

_MAX_TITLE = 300
_MAX_BODY = 8000


def _clean(text: str) -> str:
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    return _WS_RE.sub(" ", text).strip()


def sanitise_article(article: Article) -> Article:
    """Sanitise *article* in-place and return it."""
    article.title = _clean(article.title or "")[:_MAX_TITLE]
    article.body = _clean(article.body or "")[:_MAX_BODY]
    return article

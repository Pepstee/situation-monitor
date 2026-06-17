"""Article sanitiser: strip HTML, normalise whitespace, truncate oversized fields."""

from __future__ import annotations

import html
import re

from situation_monitor.models import Article

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# C0/C1 control characters (incl. NUL and BEL) excluding the usual whitespace
# (\t \n \r \f \v) that ``_WS_RE`` already collapses. These survive a plain
# whitespace pass and can corrupt downstream HTML/Telegram rendering.
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]")

_MAX_TITLE = 300
_MAX_BODY = 8000


def _clean(text: str) -> str:
    text = _TAG_RE.sub(" ", text or "")
    text = html.unescape(text)
    text = _CTRL_RE.sub("", text)
    return _WS_RE.sub(" ", text).strip()


def sanitise_article(article: Article) -> Article:
    """Sanitise *article* in-place and return it."""
    article.title = _clean(article.title or "")[:_MAX_TITLE]
    article.body = _clean(article.body or "")[:_MAX_BODY]
    return article

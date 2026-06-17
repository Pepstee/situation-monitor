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
    title = _clean(article.title or "")[:_MAX_TITLE]
    body = _clean(article.body or "")[:_MAX_BODY]
    # ``_clean`` can reduce an all-markup ("<b></b>") or all-control-char title
    # to "" — but the domain model forbids an empty title (Article.__post_init__),
    # and a hostile feed item like "<b></b>" survives the RSS non-empty guard as a
    # raw string only to collapse here. Preserve the invariant with a best-effort
    # fallback (body snippet, else a clear marker) rather than emitting a corrupt
    # record with a blank headline that downstream rendering would happily show.
    if not title:
        title = body[:_MAX_TITLE].strip() or "(untitled)"
    article.title = title
    article.body = body
    return article

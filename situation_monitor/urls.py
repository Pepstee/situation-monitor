"""URL-safety helpers — neutralise hostile link schemes before rendering.

Feed-supplied URLs are untrusted. A malicious or compromised RSS/social source
can set an article's URL to ``javascript:…``, ``data:…`` or ``vbscript:…``.
Rendered verbatim into an HTML ``href`` or a Markdown link, such a URL is a
cross-site-scripting vector: HTML autoescaping does **not** stop it, because the
dangerous payload is the *scheme*, not a character needing entity-encoding.

:func:`safe_url` allow-lists ``http``/``https`` (and scheme-relative URLs) and
collapses anything else to an inert placeholder, defending the dashboard, the
Telegram digest, and the CLI markdown alike.
"""

from __future__ import annotations

from urllib.parse import urlsplit

_SAFE_SCHEMES = frozenset({"http", "https"})
PLACEHOLDER = "#"


def safe_url(url: str | None) -> str:
    """Return *url* when it uses a safe scheme, else the inert placeholder ``#``.

    ``http``/``https`` and scheme-relative URLs (no scheme) are permitted;
    ``javascript:``, ``data:``, ``vbscript:``, ``file:`` and every other scheme
    collapse to ``#``. Embedded C0 control characters (TAB/CR/LF) are stripped
    before the scheme check, because browsers ignore them when resolving a URL —
    so ``"java\\tscript:alert(1)"`` cannot slip past as a relative path.
    """
    if not url:
        return PLACEHOLDER
    candidate = url.strip()
    probe = "".join(ch for ch in candidate if ord(ch) > 0x20)
    try:
        scheme = urlsplit(probe).scheme.lower()
    except ValueError:
        return PLACEHOLDER
    if scheme and scheme not in _SAFE_SCHEMES:
        return PLACEHOLDER
    return candidate

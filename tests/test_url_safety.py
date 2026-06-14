"""Adversarial-hardening tests: hostile feed URLs must never reach a rendered link.

A malicious or compromised RSS/social source can set an article URL to
``javascript:…`` or ``data:…``. Rendered verbatim into the dashboard ``href``,
the Telegram digest link, or the CLI markdown, that is a cross-site-scripting
vector. These tests pin the sanitiser and each render boundary that uses it.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout

import pytest

from situation_monitor.dashboard import make_app
from situation_monitor.digest import breaking_ping
from situation_monitor.models import Article, SpinResult
from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
from situation_monitor.urls import INERT_HREF, safe_url


# ---------------------------------------------------------------------------
# The sanitiser itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hostile",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "  javascript:alert(1)  ",
        "java\tscript:alert(1)",
        "java\nscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
    ],
)
def test_safe_url_neutralises_hostile_schemes(hostile: str) -> None:
    assert safe_url(hostile) == INERT_HREF


@pytest.mark.parametrize(
    "ok",
    [
        "http://example.com/a",
        "https://example.com/a?x=1#frag",
        "//cdn.example.com/a",  # scheme-relative is safe
        "/relative/path",
    ],
)
def test_safe_url_preserves_safe_urls(ok: str) -> None:
    assert safe_url(ok) == ok


def test_safe_url_handles_empty_and_none() -> None:
    assert safe_url(None) == INERT_HREF
    assert safe_url("") == INERT_HREF


# ---------------------------------------------------------------------------
# Render boundaries
# ---------------------------------------------------------------------------


def _aa(url: str) -> AnnotatedArticle:
    art = Article(url=url, title="Hostile Headline", source="evil.example")
    spin = SpinResult(spin_pct=0.0, lens="left", rubric={}, receipts="r")
    return AnnotatedArticle(article=art, spin=spin)


def test_dashboard_does_not_emit_javascript_href() -> None:
    hostile = "javascript:alert(document.cookie)"
    event = DualLensEvent(
        event_title="E",
        left_articles=[_aa(hostile)],
        right_articles=[],
        center_articles=[],
        spin_delta=0.0,
    )
    story = Article(url=hostile, title="Hostile Story", source="evil.example")
    app = make_app(get_stories=lambda: [story], get_events=lambda: [event])
    client = app.test_client()
    body = client.get("/").get_data(as_text=True)
    assert "javascript:" not in body
    assert 'href="#"' in body


def test_breaking_ping_link_strips_hostile_scheme() -> None:
    art = Article(
        url="javascript:alert(1)",
        title="Breaking",
        source="evil.example",
    )
    art.relevance_score = 0.99
    sent: dict[str, str] = {}

    # Force the send path by supplying a token/chat, then capture via monkeypatch.
    import situation_monitor.digest as digest_mod

    original = digest_mod._send_telegram
    digest_mod._send_telegram = lambda token, chat, text: sent.update(text=text)
    try:
        breaking_ping([art], threshold=0.5, bot_token="t", chat_id="c")
    finally:
        digest_mod._send_telegram = original

    assert "javascript:" not in sent["text"]
    assert "(#)" in sent["text"]


def test_cli_markdown_strips_hostile_scheme() -> None:
    from situation_monitor.__main__ import _format_article

    art = Article(url="javascript:alert(1)", title="Hostile", source="evil.example")
    buf = io.StringIO()
    with redirect_stdout(buf):
        _format_article(art)
    out = buf.getvalue()
    assert "javascript:" not in out
    assert "<#>" in out

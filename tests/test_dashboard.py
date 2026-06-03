"""Tests for the Flask web dashboard (situation_monitor/dashboard.py).

Verifies XSS safety (Jinja2 autoescape), correct rendering of article
metadata, and presence of the auto-refresh meta tag.  No network calls.
"""
from __future__ import annotations

import pytest

from situation_monitor.dashboard import make_app
from situation_monitor.models import Article, SourceReliability


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _article(**kwargs) -> Article:
    defaults = dict(url="http://example.com/default", title="Default Title", source="test-source.com")
    defaults.update(kwargs)
    return Article(**defaults)


def _render(app, path: str = "/") -> str:
    with app.test_client() as client:
        return client.get(path).data.decode()


# ---------------------------------------------------------------------------
# XSS safety
# ---------------------------------------------------------------------------


class TestXssSafety:
    def test_script_tag_in_title_not_rendered_raw(self):
        """Raw <script> injected via title must NOT appear literally in HTML output."""
        xss_title = "<script>alert(1)</script>"
        app = make_app(lambda: [_article(title=xss_title, url="http://evil.com/x")])
        html = _render(app)
        assert "<script>" not in html, "Unescaped <script> found — XSS vulnerability"

    def test_closing_script_tag_absent(self):
        """Closing </script> from XSS payload must also be absent."""
        app = make_app(lambda: [_article(title="<script>alert(1)</script>", url="http://evil.com/x")])
        html = _render(app)
        assert "</script>" not in html

    def test_xss_text_content_still_reachable_escaped(self):
        """The visible text inside the payload should still appear — just HTML-escaped."""
        app = make_app(lambda: [_article(title="<script>alert(1)</script>", url="http://evil.com/x")])
        html = _render(app)
        # Jinja2 encodes < → &lt; the text "alert(1)" remains visible but harmless
        assert "alert(1)" in html

    def test_script_tag_in_source_is_escaped(self):
        """XSS injected through the source field must also be escaped."""
        app = make_app(lambda: [_article(
            title="Clean Title",
            source="<script>document.cookie</script>",
        )])
        html = _render(app)
        assert "<script>" not in html

    def test_html_entities_used_for_angle_brackets(self):
        """Angle brackets in title must be encoded as HTML entities."""
        app = make_app(lambda: [_article(title="<script>alert(1)</script>", url="http://evil.com/x")])
        html = _render(app)
        assert "&lt;script&gt;" in html or "&#39;script&#39;" in html or "&lt;" in html


# ---------------------------------------------------------------------------
# Article metadata rendering
# ---------------------------------------------------------------------------


class TestArticleMetadataRendering:
    def test_relevance_score_in_html(self):
        app = make_app(lambda: [_article(relevance_score=0.75)])
        html = _render(app)
        assert "0.75" in html

    def test_relevance_score_formatted_two_decimal_places(self):
        """Template uses '%.2f' format — 0.9 renders as '0.90'."""
        app = make_app(lambda: [_article(relevance_score=0.9)])
        html = _render(app)
        assert "0.90" in html

    def test_source_in_html(self):
        app = make_app(lambda: [_article(source="reuters.com")])
        html = _render(app)
        assert "reuters.com" in html

    def test_title_text_in_html(self):
        app = make_app(lambda: [_article(title="My Interesting Story")])
        html = _render(app)
        assert "My Interesting Story" in html

    def test_url_rendered_as_anchor_href(self):
        app = make_app(lambda: [_article(url="http://example.com/story-99")])
        html = _render(app)
        assert "http://example.com/story-99" in html

    def test_polymarket_odds_in_html(self):
        app = make_app(lambda: [_article(polymarket_odds=0.42)])
        html = _render(app)
        assert "0.42" in html

    def test_source_lean_in_html(self):
        art = _article()
        art.source_lean = "left-center"
        app = make_app(lambda: [art])
        html = _render(app)
        assert "left-center" in html

    def test_none_relevance_score_does_not_render_literal_none(self):
        """A missing relevance score should not produce '>None<' in the HTML."""
        app = make_app(lambda: [_article(relevance_score=None)])
        html = _render(app)
        assert ">None<" not in html

    def test_none_polymarket_odds_does_not_render_literal_none(self):
        app = make_app(lambda: [_article(polymarket_odds=None)])
        html = _render(app)
        assert ">None<" not in html

    def test_multiple_articles_all_appear(self):
        articles = [
            _article(title="First Story", url="http://x.com/1"),
            _article(title="Second Story", url="http://x.com/2"),
        ]
        app = make_app(lambda: articles)
        html = _render(app)
        assert "First Story" in html
        assert "Second Story" in html

    def test_story_count_in_page(self):
        articles = [_article(title=f"Article {i}", url=f"http://x.com/{i}") for i in range(5)]
        app = make_app(lambda: articles)
        html = _render(app)
        assert "5" in html

    def test_empty_stories_returns_200(self):
        app = make_app(lambda: [])
        with app.test_client() as c:
            resp = c.get("/")
        assert resp.status_code == 200

    def test_empty_stories_page_contains_heading(self):
        app = make_app(lambda: [])
        html = _render(app)
        assert "Situation Monitor" in html

    def test_get_stories_called_on_each_request(self):
        """get_stories must be invoked fresh on every request (not cached)."""
        calls = []

        def _get():
            calls.append(1)
            return []

        app = make_app(_get)
        with app.test_client() as c:
            c.get("/")
            c.get("/")
        assert len(calls) == 2


# ---------------------------------------------------------------------------
# Meta-refresh tag
# ---------------------------------------------------------------------------


class TestMetaRefresh:
    def test_meta_refresh_tag_present(self):
        """Dashboard must include an HTTP meta-refresh tag for auto-reload."""
        app = make_app(lambda: [])
        html = _render(app)
        assert 'http-equiv="refresh"' in html or 'http-equiv=refresh' in html.lower()

    def test_meta_refresh_content_is_60_seconds(self):
        """Auto-refresh interval must be 60 seconds as specified in the template."""
        app = make_app(lambda: [])
        html = _render(app)
        assert 'content="60"' in html

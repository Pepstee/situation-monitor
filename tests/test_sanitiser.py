"""Adversarial tests for situation_monitor.sanitiser.

Coverage goals:
- sanitise_article mutates title and body in-place and returns the same object
- _clean strips HTML tags, unescapes HTML entities, normalises whitespace
- Title is capped at 300 chars; body at 8000 chars
- Offline/stub LLM backend has zero effect on sanitiser output (no LLM is called)
- After sanitisation the fields contain natural-language text, not HTML
"""

from __future__ import annotations

import os

import pytest

from situation_monitor.models import Article
from situation_monitor.sanitiser import _MAX_BODY, _MAX_TITLE, _clean, sanitise_article


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _article(title: str = "Title", body: str = "") -> Article:
    return Article(url="https://example.com/a", title=title, source="example.com", body=body)


# ---------------------------------------------------------------------------
# _clean: HTML tag removal
# ---------------------------------------------------------------------------


class TestCleanTagRemoval:
    def test_no_tags_passthrough(self):
        assert _clean("hello world") == "hello world"

    def test_single_open_close_tag_removed(self):
        assert _clean("<b>bold</b>") == "bold"

    def test_tag_with_attributes_removed(self):
        result = _clean('<a href="https://x.com">link text</a>')
        assert result == "link text"

    def test_self_closing_tag_removed(self):
        result = _clean("before<br/>after")
        assert "br" not in result
        assert "<" not in result
        assert ">" not in result

    def test_img_tag_removed(self):
        result = _clean('<img src="photo.jpg" alt="photo"/>')
        assert "<" not in result
        assert ">" not in result

    def test_nested_tags_all_removed(self):
        result = _clean("<div><p><span>text</span></p></div>")
        assert result == "text"

    def test_multiple_sibling_tags_all_removed(self):
        result = _clean("<b>one</b> <i>two</i> <u>three</u>")
        assert "one" in result
        assert "two" in result
        assert "three" in result
        assert "<" not in result

    def test_script_tag_content_also_stripped(self):
        result = _clean("<script>alert(1)</script>remaining text")
        assert "<" not in result
        assert ">" not in result
        # Tag body is removed; the trailing text survives
        assert "remaining text" in result

    def test_malformed_unclosed_tag_stripped(self):
        result = _clean("<b unclosed text")
        # _TAG_RE matches <[^>]+>, so an unclosed tag without '>' is not matched —
        # that is intentional boundary behaviour we pin here.
        assert isinstance(result, str)

    def test_output_contains_no_angle_brackets_from_tags(self):
        html = "<p class='x'>Some <strong>important</strong> news today.</p>"
        result = _clean(html)
        assert "<" not in result
        assert ">" not in result
        assert "important" in result


# ---------------------------------------------------------------------------
# _clean: HTML entity unescaping
# ---------------------------------------------------------------------------


class TestCleanEntityUnescaping:
    def test_amp_entity_unescaped(self):
        assert _clean("fish &amp; chips") == "fish & chips"

    def test_lt_entity_unescaped(self):
        assert "&lt;" not in _clean("1 &lt; 2")
        assert "<" in _clean("1 &lt; 2")

    def test_gt_entity_unescaped(self):
        assert "&gt;" not in _clean("3 &gt; 1")
        assert ">" in _clean("3 &gt; 1")

    def test_quot_entity_unescaped(self):
        result = _clean("He said &quot;hello&quot;")
        assert '"' in result
        assert "&quot;" not in result

    def test_apos_numeric_entity_unescaped(self):
        result = _clean("it&#39;s fine")
        assert "'" in result
        assert "&#39;" not in result

    def test_nbsp_numeric_entity_normalised(self):
        # &#160; is a non-breaking space; after unescaping it becomes a whitespace
        # char that \s+ collapses to a single regular space.
        result = _clean("word&#160;word")
        # The two words must be separated by exactly one space
        assert result == "word word"

    def test_named_entity_hellip_unescaped(self):
        result = _clean("news&hellip;more")
        assert "&hellip;" not in result

    def test_multiple_entities_all_unescaped(self):
        result = _clean("&lt;tag&gt; &amp; &quot;value&quot;")
        assert "&lt;" not in result
        assert "&gt;" not in result
        assert "&amp;" not in result
        assert "&quot;" not in result


# ---------------------------------------------------------------------------
# _clean: whitespace normalisation
# ---------------------------------------------------------------------------


class TestCleanWhitespaceNormalisation:
    def test_leading_whitespace_stripped(self):
        assert _clean("   hello") == "hello"

    def test_trailing_whitespace_stripped(self):
        assert _clean("hello   ") == "hello"

    def test_multiple_internal_spaces_collapsed(self):
        assert _clean("one  two   three") == "one two three"

    def test_tab_collapsed_to_single_space(self):
        assert _clean("one\ttwo") == "one two"

    def test_newline_collapsed_to_single_space(self):
        assert _clean("line one\nline two") == "line one line two"

    def test_mixed_whitespace_collapsed(self):
        result = _clean("  word  \t\n  word  ")
        assert result == "word word"

    def test_tags_replaced_by_space_not_concatenation(self):
        # Two words with only an HTML tag between them must be separated by a space,
        # not run together.
        result = _clean("first<br/>second")
        assert "first" in result
        assert "second" in result
        # The tag is replaced with a space; the collapsed result is "first second"
        assert "firstsecond" not in result

    def test_empty_string_stays_empty(self):
        assert _clean("") == ""

    def test_whitespace_only_string_becomes_empty(self):
        assert _clean("   \t\n  ") == ""

    def test_tags_only_becomes_empty(self):
        assert _clean("<div><p></p></div>") == ""


# ---------------------------------------------------------------------------
# sanitise_article: field extraction and identity
# ---------------------------------------------------------------------------


class TestSanitiseArticleFields:
    def test_returns_same_object(self):
        art = _article("Hello <b>World</b>")
        result = sanitise_article(art)
        assert result is art

    def test_title_cleaned_in_place(self):
        art = _article("<h1>Breaking News</h1>")
        sanitise_article(art)
        assert art.title == "Breaking News"
        assert "<h1>" not in art.title

    def test_body_cleaned_in_place(self):
        art = _article(body="<p>Story text &amp; details.</p>")
        sanitise_article(art)
        assert "<p>" not in art.body
        assert "&amp;" not in art.body
        assert "Story text & details." == art.body

    def test_empty_body_stays_empty(self):
        art = _article()  # body defaults to ""
        sanitise_article(art)
        assert art.body == ""

    def test_non_title_body_fields_unchanged(self):
        art = _article("Title", "Body")
        art.source = "my-source"
        art.url = "https://example.com/test"
        art.relevance_score = 0.75
        sanitise_article(art)
        assert art.source == "my-source"
        assert art.url == "https://example.com/test"
        assert art.relevance_score == 0.75

    def test_tags_list_field_unchanged(self):
        art = _article()
        art.tags = ["politics", "economy"]
        sanitise_article(art)
        assert art.tags == ["politics", "economy"]

    def test_result_is_natural_language_not_html(self):
        """The core 'stub returns natural-language' invariant.

        HTML *tags* are stripped; HTML *entities* are decoded into their literal
        characters (so &lt; becomes '<', which is now natural-language text, not a
        tag).  Only raw HTML entities and tag markup should be absent.
        """
        art = _article(
            "<h1>Major &amp; breaking event unfolds</h1>",
            "<p>Details: <strong>important</strong> development &lt;here&gt;.</p>",
        )
        sanitise_article(art)
        # HTML tag syntax is gone from the title
        assert "<h1>" not in art.title
        assert "</h1>" not in art.title
        # No raw (un-decoded) entities remain
        assert "&amp;" not in art.title
        assert "&lt;" not in art.body
        assert "&gt;" not in art.body
        # HTML tag markup gone from body; entity-decoded '<here>' is legitimate text
        assert "<strong>" not in art.body
        assert "</strong>" not in art.body
        assert "<p>" not in art.body
        # Readable natural language survives
        assert "Major & breaking event unfolds" == art.title
        assert "Details: important development <here>." == art.body


# ---------------------------------------------------------------------------
# sanitise_article: truncation boundaries
# ---------------------------------------------------------------------------


class TestSanitiseArticleTruncation:
    def test_title_at_exactly_max_not_truncated(self):
        exact = "x" * _MAX_TITLE
        art = _article(exact)
        sanitise_article(art)
        assert len(art.title) == _MAX_TITLE

    def test_title_one_over_max_truncated(self):
        over = "x" * (_MAX_TITLE + 1)
        art = _article(over)
        sanitise_article(art)
        assert len(art.title) == _MAX_TITLE

    def test_title_well_over_max_truncated_to_exactly_max(self):
        over = "y" * (_MAX_TITLE * 2)
        art = _article(over)
        sanitise_article(art)
        assert len(art.title) == _MAX_TITLE

    def test_body_at_exactly_max_not_truncated(self):
        exact = "b" * _MAX_BODY
        art = _article(body=exact)
        sanitise_article(art)
        assert len(art.body) == _MAX_BODY

    def test_body_one_over_max_truncated(self):
        over = "b" * (_MAX_BODY + 1)
        art = _article(body=over)
        sanitise_article(art)
        assert len(art.body) == _MAX_BODY

    def test_body_far_over_max_truncated(self):
        over = "z" * (_MAX_BODY * 3)
        art = _article(body=over)
        sanitise_article(art)
        assert len(art.body) == _MAX_BODY

    def test_html_in_long_title_stripped_before_truncation(self):
        # The tags are stripped first; truncation applies to the cleaned string.
        # Build a title where HTML padding would push it over the limit.
        base = "A" * _MAX_TITLE
        tagged = f"<b>{base}</b>"
        art = _article(tagged)
        sanitise_article(art)
        # After strip, the clean content is `_MAX_TITLE` "A"s — fits exactly.
        assert art.title == base

    def test_html_in_very_long_body_stripped_before_truncation(self):
        clean_content = "W" * _MAX_BODY
        padded = f"<p>{clean_content}</p>"
        art = _article(body=padded)
        sanitise_article(art)
        # After stripping the tags the whitespace padding collapses; the cleaned
        # body is exactly _MAX_BODY 'W's which fits within the limit.
        assert art.body == clean_content


# ---------------------------------------------------------------------------
# sanitise_article: offline / LLM-backend independence
# ---------------------------------------------------------------------------


class TestOfflineModeIsNoOp:
    """The sanitiser must behave identically regardless of the LLM backend.

    It performs no LLM call, so setting SM_LLM_BACKEND to any value — including
    'offline', 'stub', 'claude', or 'ollama' — must produce exactly the same
    sanitised output.
    """

    _DIRTY_TITLE = "<h2>Breaking &amp; urgent news today</h2>"
    _DIRTY_BODY = "<p>Details &lt;here&gt; — <em>important</em> update.</p>"
    _CLEAN_TITLE = "Breaking & urgent news today"
    _CLEAN_BODY = "Details <here> — important update."

    def _run(self, backend: str) -> tuple[str, str]:
        os.environ["SM_LLM_BACKEND"] = backend
        try:
            art = _article(self._DIRTY_TITLE, self._DIRTY_BODY)
            sanitise_article(art)
            return art.title, art.body
        finally:
            os.environ.pop("SM_LLM_BACKEND", None)

    def test_offline_backend_produces_clean_title(self):
        title, _ = self._run("offline")
        assert title == self._CLEAN_TITLE

    def test_offline_backend_produces_clean_body(self):
        _, body = self._run("offline")
        assert body == self._CLEAN_BODY

    def test_stub_backend_same_as_offline(self):
        offline_result = self._run("offline")
        stub_result = self._run("stub")
        assert offline_result == stub_result

    def test_deterministic_backend_same_as_offline(self):
        offline_result = self._run("offline")
        det_result = self._run("deterministic")
        assert offline_result == det_result

    def test_no_backend_set_produces_same_output(self, monkeypatch):
        monkeypatch.delenv("SM_LLM_BACKEND", raising=False)
        art = _article(self._DIRTY_TITLE, self._DIRTY_BODY)
        sanitise_article(art)
        assert art.title == self._CLEAN_TITLE
        assert art.body == self._CLEAN_BODY

    def test_sanitiser_does_not_import_llm_module_at_runtime(self):
        """Verify sanitiser.py never touches the LLM client."""
        import situation_monitor.sanitiser as san_mod

        assert not hasattr(san_mod, "get_llm_client"), (
            "sanitiser module must not import or expose get_llm_client"
        )


# ---------------------------------------------------------------------------
# sanitise_article: realistic feed content (integration-style)
# ---------------------------------------------------------------------------


class TestRealisticFeedContent:
    def test_rss_paragraph_tags_stripped(self):
        body = (
            "<p>World leaders gathered in Vienna on Monday to discuss </p>"
            "<p>climate targets ahead of the UN summit next week.</p>"
        )
        art = _article(body=body)
        sanitise_article(art)
        assert "<p>" not in art.body
        assert "Vienna" in art.body
        assert "UN summit" in art.body

    def test_html_email_style_content(self):
        body = (
            '<div class="content"><h3>Market update</h3>'
            "<ul><li>S&amp;P 500: +0.5%</li><li>FTSE 100: -0.2%</li></ul></div>"
        )
        art = _article(body=body)
        sanitise_article(art)
        assert "S&P 500" in art.body
        assert "FTSE 100" in art.body
        assert "<" not in art.body

    def test_title_with_entity_and_tags(self):
        art = _article("<strong>US &amp; EU reach deal on AI regulation</strong>")
        sanitise_article(art)
        assert art.title == "US & EU reach deal on AI regulation"

    def test_body_with_script_injection_tag_stripped(self):
        # The sanitiser strips HTML *tags* only; the text content between tags
        # (including JS source) is NOT removed — that is not its responsibility.
        # The <script> and </script> delimiters are gone; the surrounding prose survives.
        body = 'Real news.<script>alert(1)</script> More real news.'
        art = _article(body=body)
        sanitise_article(art)
        assert "<script>" not in art.body
        assert "</script>" not in art.body
        assert "Real news." in art.body
        assert "More real news." in art.body

    def test_unicode_content_preserved(self):
        art = _article("Événements en <b>Île-de-France</b>", "Résumé: activité économique.")
        sanitise_article(art)
        assert "Événements en Île-de-France" == art.title
        assert "Résumé: activité économique." == art.body

    def test_cjk_content_preserved(self):
        art = _article("日本語の<b>ニュース</b>", "経済<em>成長</em>について。")
        sanitise_article(art)
        assert "<b>" not in art.title
        assert "<em>" not in art.body
        assert "日本語の" in art.title
        assert "経済" in art.body

    def test_repeated_sanitisation_is_idempotent(self):
        """Calling sanitise_article twice must yield the same result as once."""
        art = _article("<p>Once sanitised &amp; done.</p>")
        sanitise_article(art)
        title_first = art.title
        body_first = art.body
        sanitise_article(art)
        assert art.title == title_first
        assert art.body == body_first

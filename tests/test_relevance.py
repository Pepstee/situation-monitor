"""Adversarial tests for situation_monitor.relevance.score_relevance.

All LLM calls use injected stub callables — zero real network or LLM calls.
"""

from __future__ import annotations

import json

from situation_monitor.models import Article
from situation_monitor.relevance import score_relevance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _article(title: str = "Test Article", body: str = "some body text") -> Article:
    return Article(url="https://example.com/a", title=title, source="example.com", body=body)


def _stub(score: float):
    """Return a stub LLM callable that always returns a valid JSON score."""
    def _call(_prompt: str) -> str:
        return json.dumps({"score": score})
    return _call


def _stub_raw(response: str):
    """Return a stub LLM callable that returns the given raw string."""
    def _call(_prompt: str) -> str:
        return response
    return _call


def _stub_raising(exc: Exception):
    """Return a stub LLM callable that raises the given exception."""
    def _call(_prompt: str) -> str:
        raise exc
    return _call


# ---------------------------------------------------------------------------
# Acceptance criteria (the three mandated cases)
# ---------------------------------------------------------------------------

class TestAcceptanceCriteria:
    def test_high_relevance_topic_match_scores_gte_07(self) -> None:
        article = _article(
            title="Bitcoin ETF Approved by SEC — Major Win for Crypto Markets",
            body="The US Securities and Exchange Commission approved the first spot Bitcoin ETF today.",
        )
        client = _stub(0.92)
        result = score_relevance(article, ["cryptocurrency", "Bitcoin", "ETF"], client)
        assert result >= 0.7, f"Expected >= 0.7, got {result}"

    def test_unrelated_article_scores_lte_04(self) -> None:
        article = _article(
            title="Best Vegan Recipes for Summer",
            body="Try these refreshing salads and smoothies to stay cool this summer.",
        )
        client = _stub(0.05)
        result = score_relevance(article, ["cryptocurrency", "Bitcoin", "ETF"], client)
        assert result <= 0.4, f"Expected <= 0.4, got {result}"

    def test_llm_error_falls_back_to_10(self) -> None:
        article = _article()
        client = _stub_raising(RuntimeError("LLM unavailable"))
        result = score_relevance(article, ["AI", "machine learning"], client)
        assert result == 1.0


# ---------------------------------------------------------------------------
# Empty-topics fast-path
# ---------------------------------------------------------------------------

class TestEmptyTopics:
    def test_empty_topics_returns_10_without_calling_llm(self) -> None:
        called = []

        def _spy(_prompt: str) -> str:
            called.append(_prompt)
            return '{"score": 0.0}'

        result = score_relevance(_article(), [], _spy)
        assert result == 1.0
        assert called == [], "LLM should NOT be called when topics list is empty"

    def test_empty_topics_list_not_none(self) -> None:
        # Distinct from None — the function contract accepts list[str]
        result = score_relevance(_article(), [], _stub(0.0))
        assert result == 1.0


# ---------------------------------------------------------------------------
# Score clamping
# ---------------------------------------------------------------------------

class TestScoreClamping:
    def test_score_above_one_is_clamped_to_one(self) -> None:
        result = score_relevance(_article(), ["topic"], _stub(1.5))
        assert result == 1.0

    def test_score_below_zero_is_clamped_to_zero(self) -> None:
        result = score_relevance(_article(), ["topic"], _stub(-0.3))
        assert result == 0.0

    def test_score_exactly_zero_passes_through(self) -> None:
        result = score_relevance(_article(), ["topic"], _stub(0.0))
        assert result == 0.0

    def test_score_exactly_one_passes_through(self) -> None:
        result = score_relevance(_article(), ["topic"], _stub(1.0))
        assert result == 1.0

    def test_mid_range_score_unchanged(self) -> None:
        result = score_relevance(_article(), ["topic"], _stub(0.65))
        assert abs(result - 0.65) < 1e-9


# ---------------------------------------------------------------------------
# Fallback on bad LLM output
# ---------------------------------------------------------------------------

class TestFallbackOnBadOutput:
    def test_invalid_json_returns_10(self) -> None:
        result = score_relevance(_article(), ["AI"], _stub_raw("not json at all"))
        assert result == 1.0

    def test_json_without_score_key_returns_10(self) -> None:
        result = score_relevance(_article(), ["AI"], _stub_raw('{"relevance": 0.9}'))
        assert result == 1.0

    def test_score_as_non_numeric_string_returns_10(self) -> None:
        result = score_relevance(_article(), ["AI"], _stub_raw('{"score": "high"}'))
        assert result == 1.0

    def test_empty_response_returns_10(self) -> None:
        result = score_relevance(_article(), ["AI"], _stub_raw(""))
        assert result == 1.0

    def test_exception_from_llm_returns_10(self) -> None:
        result = score_relevance(_article(), ["AI"], _stub_raising(ValueError("bad")))
        assert result == 1.0

    def test_connection_error_returns_10(self) -> None:
        result = score_relevance(_article(), ["AI"], _stub_raising(ConnectionError("timeout")))
        assert result == 1.0

    def test_null_score_value_returns_10(self) -> None:
        # float(None) raises TypeError → should fall back
        result = score_relevance(_article(), ["AI"], _stub_raw('{"score": null}'))
        assert result == 1.0


# ---------------------------------------------------------------------------
# Markdown-fenced JSON stripping
# ---------------------------------------------------------------------------

class TestMarkdownFenceStripping:
    def test_plain_json_fenced_response_is_parsed(self) -> None:
        fenced = "```\n{\"score\": 0.8}\n```"
        result = score_relevance(_article(), ["crypto"], _stub_raw(fenced))
        assert abs(result - 0.8) < 1e-9

    def test_json_language_tagged_fence_is_parsed(self) -> None:
        fenced = "```json\n{\"score\": 0.75}\n```"
        result = score_relevance(_article(), ["crypto"], _stub_raw(fenced))
        assert abs(result - 0.75) < 1e-9

    def test_fenced_score_is_clamped(self) -> None:
        fenced = "```json\n{\"score\": 2.5}\n```"
        result = score_relevance(_article(), ["topic"], _stub_raw(fenced))
        assert result == 1.0

    def test_fence_with_extra_whitespace_is_parsed(self) -> None:
        fenced = "  ```json\n{\"score\": 0.6}\n```  "
        # strip() is applied first, so leading spaces on the outer string are removed
        result = score_relevance(_article(), ["topic"], _stub_raw(fenced))
        assert abs(result - 0.6) < 1e-9


# ---------------------------------------------------------------------------
# Prompt construction — verify topics and article fields reach the LLM
# ---------------------------------------------------------------------------

class TestPromptConstruction:
    def test_prompt_contains_all_topics(self) -> None:
        captured: list[str] = []

        def _spy(prompt: str) -> str:
            captured.append(prompt)
            return '{"score": 0.5}'

        topics = ["quantum computing", "cryptography", "blockchain"]
        score_relevance(_article(), topics, _spy)
        assert captured, "LLM callable was never called"
        prompt = captured[0]
        for t in topics:
            assert t in prompt, f"Topic {t!r} missing from prompt"

    def test_prompt_contains_article_title(self) -> None:
        captured: list[str] = []

        def _spy(prompt: str) -> str:
            captured.append(prompt)
            return '{"score": 0.5}'

        article = _article(title="Unique Title XYZ-9999")
        score_relevance(article, ["topic"], _spy)
        assert "Unique Title XYZ-9999" in captured[0]

    def test_prompt_contains_article_body_excerpt(self) -> None:
        captured: list[str] = []

        def _spy(prompt: str) -> str:
            captured.append(prompt)
            return '{"score": 0.5}'

        body = "Distinctive body content ABCD-1234"
        article = _article(body=body)
        score_relevance(article, ["topic"], _spy)
        assert "Distinctive body content ABCD-1234" in captured[0]

    def test_body_is_truncated_to_1000_chars(self) -> None:
        captured: list[str] = []

        def _spy(prompt: str) -> str:
            captured.append(prompt)
            return '{"score": 0.5}'

        long_body = "A" * 2000
        article = _article(body=long_body)
        score_relevance(article, ["topic"], _spy)
        # The prompt should contain exactly 1000 A's, not 2000
        assert "A" * 1001 not in captured[0], "Body should be truncated to 1000 chars"
        assert "A" * 1000 in captured[0], "First 1000 body chars should appear in prompt"

    def test_empty_body_article_does_not_crash(self) -> None:
        article = Article(url="https://x.com/a", title="Titleless body", source="x.com", body="")
        result = score_relevance(article, ["topic"], _stub(0.5))
        assert 0.0 <= result <= 1.0


# ---------------------------------------------------------------------------
# Return-type contract
# ---------------------------------------------------------------------------

class TestReturnType:
    def test_return_is_float(self) -> None:
        result = score_relevance(_article(), ["topic"], _stub(0.5))
        assert isinstance(result, float)

    def test_return_within_unit_interval(self) -> None:
        for raw in (0.0, 0.25, 0.5, 0.75, 1.0):
            result = score_relevance(_article(), ["topic"], _stub(raw))
            assert 0.0 <= result <= 1.0, f"score {raw} produced out-of-range result {result}"

    def test_integer_score_in_json_is_accepted(self) -> None:
        # LLM may return {"score": 1} (no decimal); float(1) == 1.0
        result = score_relevance(_article(), ["AI"], _stub_raw('{"score": 1}'))
        assert result == 1.0

    def test_score_is_deterministic_for_same_stub(self) -> None:
        article = _article()
        topics = ["science", "technology"]
        client = _stub(0.77)
        assert score_relevance(article, topics, client) == score_relevance(article, topics, client)

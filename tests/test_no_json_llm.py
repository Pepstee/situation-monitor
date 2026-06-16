"""Tests for no-JSON LLM response parsing in relevance and propaganda modules.

Both modules use regex-based parsing, not JSON parsing, so they accept:
  - plain numbers / natural-language prose ("The score is 0.85")
  - JSON-formatted text (via incidental regex match on embedded number/technique)
  - mixed formats (explanation + embedded value)

These tests are adversarial: they exercise the real extraction paths and can
fail when the regex contracts are violated.
"""

from __future__ import annotations

import pytest

from situation_monitor.models import Article
from situation_monitor.propaganda import enrich_article, flag_article
from situation_monitor.relevance import score_relevance


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _article(
    title: str = "Article Title",
    body: str = "Article body text.",
    url: str = "https://example.com/a",
    source: str = "example.com",
) -> Article:
    return Article(url=url, title=title, source=source, body=body)


def _client(response: str):
    """Return a callable that always returns *response*, capturing the prompt."""
    captured: list[str] = []

    def _call(prompt: str) -> str:
        captured.append(prompt)
        return response

    _call.prompts = captured  # type: ignore[attr-defined]
    return _call


def _raising(exc: Exception):
    def _call(_prompt: str) -> str:
        raise exc
    return _call


# ===========================================================================
# relevance.score_relevance — natural language responses
# ===========================================================================

class TestRelevanceNaturalLanguage:
    """LLM returns plain prose with an embedded float — no JSON wrapping."""

    def test_plain_float_string(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("0.85"))
        assert abs(result - 0.85) < 1e-9

    def test_prose_then_float(self) -> None:
        result = score_relevance(
            _article(), ["ai"], _client("The relevance score is 0.85 for this topic.")
        )
        assert abs(result - 0.85) < 1e-9

    def test_float_after_colon(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("Relevance: 0.6"))
        assert abs(result - 0.6) < 1e-9

    def test_float_on_its_own_line(self) -> None:
        raw = "After analysis of the article content:\n\n0.72\n"
        result = score_relevance(_article(), ["ai"], _client(raw))
        assert abs(result - 0.72) < 1e-9

    def test_very_wordy_response_with_embedded_float(self) -> None:
        raw = (
            "After thorough consideration of the article's content relative "
            "to the given topics, I'd assign a relevance rating of 0.45."
        )
        result = score_relevance(_article(), ["finance"], _client(raw))
        assert abs(result - 0.45) < 1e-9

    def test_integer_response_parses_as_float(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("1"))
        assert result == 1.0

    def test_zero_plain_returns_zero(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("0"))
        assert result == 0.0

    def test_float_with_leading_whitespace(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("   0.5   "))
        assert abs(result - 0.5) < 1e-9

    def test_newline_before_float(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("\n0.3\n"))
        assert abs(result - 0.3) < 1e-9

    def test_explanation_score_label_float(self) -> None:
        raw = "Explanation: article covers AI topics.\nScore: 0.88"
        result = score_relevance(_article(), ["ai"], _client(raw))
        assert abs(result - 0.88) < 1e-9

    def test_pure_text_no_numbers_falls_back_to_one(self) -> None:
        raw = "This article is not relevant to the given topics at all."
        result = score_relevance(_article(), ["finance"], _client(raw))
        assert result == 1.0

    def test_word_none_falls_back_to_one(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("none"))
        assert result == 1.0

    def test_empty_string_falls_back_to_one(self) -> None:
        result = score_relevance(_article(), ["ai"], _client(""))
        assert result == 1.0

    def test_whitespace_only_falls_back_to_one(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("   \n\t  "))
        assert result == 1.0


class TestRelevanceFirstNumberSemantics:
    """_FLOAT_RE.search extracts the FIRST number in the string — tests pin that."""

    def test_first_of_two_numbers_is_extracted(self) -> None:
        # "0.7 out of 1.0" → first number is 0.7
        result = score_relevance(_article(), ["ai"], _client("0.7 out of 1.0"))
        assert abs(result - 0.7) < 1e-9

    def test_multiple_numbers_first_wins(self) -> None:
        result = score_relevance(
            _article(), ["ai"], _client("Articles scored: 0.3, 0.5, 0.9")
        )
        assert abs(result - 0.3) < 1e-9

    def test_number_at_string_start_is_extracted(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("0.55 — moderately relevant"))
        assert abs(result - 0.55) < 1e-9

    def test_clamping_above_one_from_prose(self) -> None:
        # Score larger than 1.0 is clamped down
        result = score_relevance(_article(), ["ai"], _client("Score: 1.5"))
        assert result == 1.0

    def test_integer_above_one_is_clamped(self) -> None:
        # "2" → float("2") = 2.0 → clamped to 1.0
        result = score_relevance(_article(), ["ai"], _client("Score: 2"))
        assert result == 1.0

    def test_decimal_only_notation(self) -> None:
        # ".75" matches the `\.\d+` branch
        result = score_relevance(_article(), ["ai"], _client(".75"))
        assert abs(result - 0.75) < 1e-9


class TestRelevanceJSONBackwardCompat:
    """JSON-shaped responses still work because the regex extracts the embedded number."""

    def test_json_with_score_key_parses_value(self) -> None:
        # '{"score": 0.8}' → regex finds "0.8"
        result = score_relevance(_article(), ["ai"], _client('{"score": 0.8}'))
        assert abs(result - 0.8) < 1e-9

    def test_json_with_different_key_parses_value(self) -> None:
        # '{"relevance": 0.75}' → regex finds "0.75" (the first number present)
        result = score_relevance(_article(), ["ai"], _client('{"relevance": 0.75}'))
        assert abs(result - 0.75) < 1e-9

    def test_json_integer_score(self) -> None:
        result = score_relevance(_article(), ["ai"], _client('{"score": 1}'))
        assert result == 1.0

    def test_markdown_fenced_json(self) -> None:
        raw = "```json\n{\"score\": 0.65}\n```"
        result = score_relevance(_article(), ["ai"], _client(raw))
        assert abs(result - 0.65) < 1e-9

    def test_json_score_zero(self) -> None:
        # '{"score": 0}' — regex extracts "0" → 0.0
        result = score_relevance(_article(), ["ai"], _client('{"score": 0}'))
        assert result == 0.0

    def test_json_with_null_value_falls_back_to_one(self) -> None:
        # '{"score": null}' — no digit in "null" → no match → fallback 1.0
        result = score_relevance(_article(), ["ai"], _client('{"score": null}'))
        assert result == 1.0

    def test_json_with_string_value_no_digits_falls_back(self) -> None:
        # '{"score": "high"}' — "high" has no digits → fallback 1.0
        result = score_relevance(_article(), ["ai"], _client('{"score": "high"}'))
        assert result == 1.0

    def test_json_score_clamped_above_one(self) -> None:
        result = score_relevance(_article(), ["ai"], _client('{"score": 1.5}'))
        assert result == 1.0


class TestRelevanceMixedFormat:
    """Responses that mix prose explanation with a structured answer."""

    def test_labeled_score_with_explanation(self) -> None:
        raw = (
            "The article discusses cryptocurrency markets.\n"
            "Topics provided: Bitcoin, ETF.\n"
            "Relevance: 0.9\n"
            "Confidence: high"
        )
        result = score_relevance(_article(), ["Bitcoin", "ETF"], _client(raw))
        assert abs(result - 0.9) < 1e-9

    def test_thinking_then_answer(self) -> None:
        raw = (
            "<think>Article is about cooking. Topics about tech.</think>\n"
            "0.05"
        )
        result = score_relevance(_article(), ["AI"], _client(raw))
        assert abs(result - 0.05) < 1e-9

    def test_summary_then_score(self) -> None:
        raw = "This article is highly relevant to AI topics.\n\nFinal score: 0.95"
        result = score_relevance(_article(), ["AI"], _client(raw))
        assert abs(result - 0.95) < 1e-9

    def test_result_stays_float(self) -> None:
        result = score_relevance(_article(), ["ai"], _client("0.77"))
        assert isinstance(result, float)

    def test_result_in_unit_interval_for_prose_response(self) -> None:
        raw = "After careful analysis the relevance score is 0.4."
        result = score_relevance(_article(), ["politics"], _client(raw))
        assert 0.0 <= result <= 1.0


# ===========================================================================
# propaganda.flag_article — natural language responses
# ===========================================================================

class TestPropagandaNaturalLanguage:
    """LLM returns technique names in prose — regex extraction must find them."""

    def test_single_technique_in_prose(self) -> None:
        raw = "The article uses loaded_language throughout."
        result = flag_article(_article(), _client(raw))
        assert result == ["loaded_language"]

    def test_multiple_techniques_listed(self) -> None:
        raw = "loaded_language\nappeal_to_fear\nbandwagon"
        result = flag_article(_article(), _client(raw))
        assert set(result) == {"loaded_language", "appeal_to_fear", "bandwagon"}

    def test_techniques_in_sentence(self) -> None:
        raw = "I detected bandwagon and false_dichotomy in this piece."
        result = flag_article(_article(), _client(raw))
        assert set(result) == {"bandwagon", "false_dichotomy"}

    def test_none_keyword_returns_empty(self) -> None:
        raw = "none"
        result = flag_article(_article(), _client(raw))
        assert result == []

    def test_none_found_sentence_returns_empty(self) -> None:
        raw = "No propaganda techniques were found in this article."
        result = flag_article(_article(), _client(raw))
        assert result == []

    def test_case_insensitive_technique_match(self) -> None:
        raw = "LOADED_LANGUAGE and APPEAL_TO_FEAR detected."
        result = flag_article(_article(), _client(raw))
        assert set(result) == {"loaded_language", "appeal_to_fear"}

    def test_mixed_case_technique(self) -> None:
        raw = "Technique: Bandwagon, False_Dichotomy"
        result = flag_article(_article(), _client(raw))
        assert set(result) == {"bandwagon", "false_dichotomy"}

    def test_all_five_techniques_detected(self) -> None:
        raw = (
            "loaded_language, appeal_to_fear, bandwagon, "
            "false_dichotomy, scapegoating"
        )
        result = flag_article(_article(), _client(raw))
        assert set(result) == {
            "loaded_language", "appeal_to_fear", "bandwagon",
            "false_dichotomy", "scapegoating",
        }

    def test_duplicate_technique_deduplicated(self) -> None:
        raw = "loaded_language loaded_language loaded_language"
        result = flag_article(_article(), _client(raw))
        assert result == ["loaded_language"]
        assert result.count("loaded_language") == 1

    def test_unknown_technique_name_ignored(self) -> None:
        raw = "propaganda misinformation disinformation loaded_language"
        result = flag_article(_article(), _client(raw))
        assert result == ["loaded_language"]

    def test_empty_response_returns_empty(self) -> None:
        result = flag_article(_article(), _client(""))
        assert result == []

    def test_whitespace_only_returns_empty(self) -> None:
        result = flag_article(_article(), _client("   \n  "))
        assert result == []

    def test_client_exception_returns_empty(self) -> None:
        result = flag_article(_article(), _raising(RuntimeError("network error")))
        assert result == []

    def test_scapegoating_detected(self) -> None:
        raw = "The article employs scapegoating techniques."
        result = flag_article(_article(), _client(raw))
        assert result == ["scapegoating"]


class TestPropagandaJSONBackwardCompat:
    """JSON-shaped responses still work: technique names are embedded in the string."""

    def test_json_flags_array_parsed_via_regex(self) -> None:
        # technique names appear inside the JSON string → regex finds them
        raw = '{"flags": ["loaded_language", "appeal_to_fear"]}'
        result = flag_article(_article(), _client(raw))
        assert set(result) == {"loaded_language", "appeal_to_fear"}

    def test_json_single_flag(self) -> None:
        raw = '{"flags": ["scapegoating"]}'
        result = flag_article(_article(), _client(raw))
        assert result == ["scapegoating"]

    def test_json_empty_flags_array(self) -> None:
        # No technique names in '{"flags": []}' → empty result
        raw = '{"flags": []}'
        result = flag_article(_article(), _client(raw))
        assert result == []

    def test_json_none_value_returns_empty(self) -> None:
        raw = '{"flags": null}'
        result = flag_article(_article(), _client(raw))
        assert result == []

    def test_json_with_all_techniques(self) -> None:
        techniques = [
            "loaded_language", "appeal_to_fear", "bandwagon",
            "false_dichotomy", "scapegoating",
        ]
        raw = '{"flags": ' + str(techniques).replace("'", '"') + "}"
        result = flag_article(_article(), _client(raw))
        assert set(result) == set(techniques)


# ===========================================================================
# propaganda.enrich_article — natural language responses
# ===========================================================================

class TestEnrichArticleNaturalLanguage:
    """enrich_article should parse natural language with technique names and
    LOADED_LANGUAGE/PROPAGANDA flag lines."""

    def test_explicit_loaded_language_yes(self) -> None:
        raw = "loaded_language\nLOADED_LANGUAGE: yes\nPROPAGANDA: yes"
        art = _article()
        enrich_article(art, _client(raw))
        assert art.loaded_language is True
        assert art.propaganda_flag is True
        assert "loaded_language" in art.propaganda_flags

    def test_explicit_loaded_language_no(self) -> None:
        raw = "LOADED_LANGUAGE: no\nPROPAGANDA: no"
        art = _article()
        enrich_article(art, _client(raw))
        assert art.loaded_language is False
        assert art.propaganda_flag is False

    def test_techniques_without_explicit_flags_derive_propaganda_flag(self) -> None:
        # No PROPAGANDA: line → propaganda_flag = bool(flags)
        raw = "appeal_to_fear\nscapegoating"
        art = _article()
        enrich_article(art, _client(raw))
        assert set(art.propaganda_flags) == {"appeal_to_fear", "scapegoating"}
        assert art.propaganda_flag is True
        assert art.loaded_language is False

    def test_no_techniques_and_no_explicit_flags_leaves_defaults(self) -> None:
        raw = "none"
        art = _article()
        enrich_article(art, _client(raw))
        assert art.propaganda_flags == []
        assert art.propaganda_flag is False
        assert art.loaded_language is False

    def test_loaded_language_true_value(self) -> None:
        raw = "loaded_language\nLOADED_LANGUAGE: true\nPROPAGANDA: true"
        art = _article()
        enrich_article(art, _client(raw))
        assert art.loaded_language is True
        assert art.propaganda_flag is True

    def test_loaded_language_hyphen_separator(self) -> None:
        raw = "loaded_language\nLOADED_LANGUAGE - yes\nPROPAGANDA - yes"
        art = _article()
        enrich_article(art, _client(raw))
        assert art.loaded_language is True

    def test_propaganda_flag_line_with_underscore(self) -> None:
        raw = "appeal_to_fear\nLOADED_LANGUAGE: no\nPROPAGANDA_FLAG: yes"
        art = _article()
        enrich_article(art, _client(raw))
        assert art.propaganda_flag is True

    def test_case_insensitive_loaded_language_line(self) -> None:
        raw = "loaded_language\nloaded_language: yes\npropaganda: yes"
        art = _article()
        enrich_article(art, _client(raw))
        assert art.loaded_language is True
        assert art.propaganda_flag is True

    def test_exception_from_client_leaves_article_unchanged(self) -> None:
        art = _article()
        enrich_article(art, _raising(ConnectionError("timeout")))
        assert art.propaganda_flags == []
        assert art.loaded_language is False
        assert art.propaganda_flag is False

    def test_empty_response_leaves_defaults(self) -> None:
        art = _article()
        enrich_article(art, _client(""))
        assert art.propaganda_flags == []
        assert art.loaded_language is False
        assert art.propaganda_flag is False

    def test_enrich_replaces_existing_flags(self) -> None:
        # enrich_article assigns the parsed flags list directly, replacing any prior value
        art = _article()
        art.propaganda_flags = ["bandwagon"]
        enrich_article(art, _client("loaded_language\nLOADED_LANGUAGE: yes"))
        # "bandwagon" is NOT preserved — enrich_article replaces, not merges
        assert art.propaganda_flags == ["loaded_language"]
        assert art.loaded_language is True


class TestEnrichArticleBackwardCompatJSON:
    """JSON-shaped responses for enrich_article still work via embedded strings."""

    def test_json_with_technique_in_value_string(self) -> None:
        # technique names embedded inside JSON string values are found by regex
        raw = '{"techniques": ["loaded_language", "appeal_to_fear"], "loaded_language": true}'
        art = _article()
        enrich_article(art, _client(raw))
        # Techniques extracted from JSON string content
        assert "loaded_language" in art.propaganda_flags
        assert "appeal_to_fear" in art.propaganda_flags

    def test_technique_name_as_json_key_is_still_extracted(self) -> None:
        # The technique regex matches the literal string "loaded_language" wherever it
        # appears — including as a JSON key name.  A response like
        # '{"loaded_language": false}' therefore produces flags=["loaded_language"]
        # and propaganda_flag=True (derived from non-empty flags), even though the
        # JSON *value* is false.  This is the expected regex-based behaviour.
        raw = '{"propaganda_flag": true, "loaded_language": false}'
        art = _article()
        enrich_article(art, _client(raw))
        # "loaded_language" appears in the string → extracted as a technique flag
        assert "loaded_language" in art.propaganda_flags
        # propaganda_flag derived from non-empty flags (no PROPAGANDA: line matches)
        assert art.propaganda_flag is True

    def test_mixed_json_and_natural_language(self) -> None:
        raw = 'Techniques found: loaded_language.\nLOADED_LANGUAGE: yes\nPROPAGANDA: yes'
        art = _article()
        enrich_article(art, _client(raw))
        assert "loaded_language" in art.propaganda_flags
        assert art.loaded_language is True
        assert art.propaganda_flag is True


# ===========================================================================
# Integration: natural language through the full relevance+propaganda pipeline
# ===========================================================================

class TestNaturalLanguagePipelineIntegration:
    """Simulate what an unconstrained LLM might return and verify both modules
    handle it without raising."""

    @pytest.mark.parametrize("raw,expected_min,expected_max", [
        ("0.9", 0.9, 0.9),
        ("The article is very relevant. Score: 0.85.", 0.85, 0.85),
        ("Relevance rating: 0.0", 0.0, 0.0),
        ("Highly relevant!\n1.0", 1.0, 1.0),
        ("Irrelevant. 0", 0.0, 0.0),
    ])
    def test_relevance_natural_responses(
        self, raw: str, expected_min: float, expected_max: float
    ) -> None:
        result = score_relevance(_article(), ["ai"], _client(raw))
        assert expected_min <= result <= expected_max, (
            f"Response {raw!r} produced {result}, expected [{expected_min}, {expected_max}]"
        )

    @pytest.mark.parametrize("raw,expected_flags", [
        ("none", []),
        ("loaded_language", ["loaded_language"]),
        ("appeal_to_fear, scapegoating", ["appeal_to_fear", "scapegoating"]),
        ("No techniques detected.", []),
        ("BANDWAGON", ["bandwagon"]),
    ])
    def test_propaganda_natural_responses(
        self, raw: str, expected_flags: list
    ) -> None:
        result = flag_article(_article(), _client(raw))
        assert set(result) == set(expected_flags), (
            f"Response {raw!r} produced {result}, expected {expected_flags}"
        )

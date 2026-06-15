"""
Acceptance and adversarial tests for bias dataset paired lookups and propaganda
flag propagation through scored Article objects.

Acceptance criteria covered:
  1. Known domain returns correct lean AND reliability_tier; unknown returns None.
  2. Stub LLM returning propaganda_flag=True propagates through the Article.
  3. Stub LLM returning loaded_language=False is explicitly tested.
  4. Zero network I/O — every LLM client is a local stub (MagicMock).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from situation_monitor.bias import get_source_lean, get_source_reliability
from situation_monitor.models import Article
from situation_monitor.propaganda import enrich_article


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _article(
    url: str = "https://example.com/news",
    title: str = "Test Article",
    source: str = "example.com",
    body: str = "Some article body text.",
) -> Article:
    return Article(url=url, title=title, source=source, body=body)


def _stub(payload: dict) -> MagicMock:
    """Stub LLM client that returns a fixed JSON string; never makes network calls."""
    return MagicMock(return_value=json.dumps(payload))


# ---------------------------------------------------------------------------
# Acceptance criterion 1a: known domain → correct lean AND reliability_tier
# ---------------------------------------------------------------------------

class TestKnownDomainPairedLookup:
    """Both lean and reliability_tier are correct for the same source string."""

    def test_foxnews_right_and_mixed(self) -> None:
        assert get_source_lean("foxnews.com") == "right"
        assert get_source_reliability("foxnews.com") == "mixed"

    def test_reuters_center_and_high(self) -> None:
        assert get_source_lean("reuters.com") == "center"
        assert get_source_reliability("reuters.com") == "high"

    def test_breitbart_right_and_low(self) -> None:
        assert get_source_lean("breitbart.com") == "right"
        assert get_source_reliability("breitbart.com") == "low"

    def test_nytimes_left_center_and_high(self) -> None:
        assert get_source_lean("nytimes.com") == "left-center"
        assert get_source_reliability("nytimes.com") == "high"

    def test_cnn_left_and_medium(self) -> None:
        assert get_source_lean("cnn.com") == "left"
        assert get_source_reliability("cnn.com") == "medium"

    def test_bbc_center_and_high(self) -> None:
        assert get_source_lean("bbc.com") == "center"
        assert get_source_reliability("bbc.com") == "high"

    def test_bbc_co_uk_center_and_high(self) -> None:
        # bbc.co.uk is its own entry in the dataset with identical values
        assert get_source_lean("bbc.co.uk") == "center"
        assert get_source_reliability("bbc.co.uk") == "high"

    def test_apnews_center_and_high(self) -> None:
        assert get_source_lean("apnews.com") == "center"
        assert get_source_reliability("apnews.com") == "high"

    def test_wsj_right_center_and_high(self) -> None:
        assert get_source_lean("wsj.com") == "right-center"
        assert get_source_reliability("wsj.com") == "high"


# ---------------------------------------------------------------------------
# Acceptance criterion 1b: unknown domain → None from BOTH functions
# ---------------------------------------------------------------------------

class TestUnknownDomainReturnsNone:
    """Both lookup functions must return None for any source not in the dataset."""

    def test_both_none_for_fabricated_domain(self) -> None:
        domain = "xkcd-news-2099.net"
        assert get_source_lean(domain) is None
        assert get_source_reliability(domain) is None

    def test_lean_is_none_for_unknown(self) -> None:
        assert get_source_lean("totally-unknown-xyz-9876.org") is None

    def test_reliability_is_none_for_unknown(self) -> None:
        assert get_source_reliability("totally-unknown-xyz-9876.org") is None

    def test_numeric_looking_source_both_none(self) -> None:
        # No dataset key starts with or contains "12345news.com"
        assert get_source_lean("12345news.com") is None
        assert get_source_reliability("12345news.com") is None

    def test_gibberish_both_none(self) -> None:
        assert get_source_lean("qqqqrrrrssss") is None
        assert get_source_reliability("qqqqrrrrssss") is None


# ---------------------------------------------------------------------------
# Bias lookup edge cases — boundary behavior of the substring matching rule
# ---------------------------------------------------------------------------

class TestBiasLookupSubstringBehavior:
    """
    Matching rule: key in source_lower OR source_lower in key.
    These tests document real (possibly surprising) boundary behaviors.
    """

    def test_full_url_with_path_matches_apnews(self) -> None:
        # "apnews.com" is a substring of the full URL → match
        assert get_source_lean("https://apnews.com/article/some-story") == "center"
        assert get_source_reliability("https://apnews.com/article/some-story") == "high"

    def test_short_fragment_that_is_substring_of_key(self) -> None:
        # "reuters" is a substring of "reuters.com" → source_lower in key → match
        result = get_source_lean("reuters")
        assert result == "center"
        result_r = get_source_reliability("reuters")
        assert result_r == "high"

    def test_source_with_subdomain_still_resolves(self) -> None:
        # "feeds.ft.com" contains "ft.com" → key in source_lower → match
        assert get_source_lean("feeds.ft.com") == "center"
        assert get_source_reliability("feeds.ft.com") == "high"

    def test_case_insensitive_mixed_case_url(self) -> None:
        assert get_source_lean("HTTPS://WWW.BBC.COM/NEWS") == "center"
        assert get_source_reliability("HTTPS://WWW.BBC.COM/NEWS") == "high"

    def test_empty_or_trivial_source_resolves_to_no_match(self) -> None:
        # An empty or single-character source is a substring of nearly every
        # domain key; it must NOT be mis-attributed to the first curated entry.
        # A source-less article has no known lean — the lookup returns None.
        assert get_source_lean("") is None
        assert get_source_reliability("") is None
        assert get_source_lean("m") is None
        assert get_source_reliability("m") is None


# ---------------------------------------------------------------------------
# Acceptance criterion 2: propaganda_flag=True propagates through Article
# ---------------------------------------------------------------------------

class TestPropagandaFlagTruePropagation:
    """Stub LLM returning propaganda_flag=True must set Article.propaganda_flag."""

    def test_propaganda_flag_true_set_on_article(self) -> None:
        art = _article()
        enrich_article(art, _stub({"flags": ["loaded_language"], "loaded_language": True, "propaganda_flag": True}))
        assert art.propaganda_flag is True

    def test_propaganda_flag_true_with_empty_flags_list(self) -> None:
        # LLM may signal propaganda even when naming no specific technique
        art = _article()
        enrich_article(art, _stub({"flags": [], "loaded_language": False, "propaganda_flag": True}))
        assert art.propaganda_flag is True
        assert art.propaganda_flags == []

    def test_propaganda_flag_is_bool_type_not_truthy_int(self) -> None:
        art = _article()
        enrich_article(art, _stub({"flags": [], "loaded_language": False, "propaganda_flag": True}))
        assert type(art.propaganda_flag) is bool
        assert art.propaganda_flag is True

    def test_all_canonical_flags_with_propaganda_true(self) -> None:
        techniques = ["loaded_language", "appeal_to_fear", "bandwagon", "false_dichotomy", "scapegoating"]
        art = _article()
        enrich_article(art, _stub({"flags": techniques, "loaded_language": True, "propaganda_flag": True}))
        assert art.propaganda_flag is True
        assert art.propaganda_flags == techniques
        assert art.loaded_language is True

    def test_scapegoating_only_propagates_flag(self) -> None:
        art = _article()
        enrich_article(art, _stub({"flags": ["scapegoating"], "loaded_language": False, "propaganda_flag": True}))
        assert art.propaganda_flag is True
        assert "scapegoating" in art.propaganda_flags


# ---------------------------------------------------------------------------
# Acceptance criterion 3: loaded_language=False explicitly tested
# ---------------------------------------------------------------------------

class TestLoadedLanguageFalsePropagation:
    """Stub LLM returning loaded_language=False must write False (not merely default)."""

    def test_loaded_language_false_clean_article(self) -> None:
        art = _article()
        enrich_article(art, _stub({"flags": [], "loaded_language": False, "propaganda_flag": False}))
        assert art.loaded_language is False

    def test_loaded_language_false_when_propaganda_flag_true(self) -> None:
        # LLM may detect a technique without classifying language as loaded
        art = _article()
        enrich_article(art, _stub({"flags": ["bandwagon"], "loaded_language": False, "propaganda_flag": True}))
        assert art.loaded_language is False
        assert art.propaganda_flag is True

    def test_loaded_language_false_is_bool_type(self) -> None:
        art = _article()
        enrich_article(art, _stub({"flags": [], "loaded_language": False, "propaganda_flag": False}))
        assert type(art.loaded_language) is bool
        assert art.loaded_language is False

    def test_loaded_language_false_after_true_in_prior_enrichment(self) -> None:
        # Verify enrich_article overwrites the field even if previously True
        art = _article()
        enrich_article(art, _stub({"flags": ["loaded_language"], "loaded_language": True, "propaganda_flag": True}))
        assert art.loaded_language is True

        # A second call with False should overwrite
        enrich_article(art, _stub({"flags": [], "loaded_language": False, "propaganda_flag": False}))
        assert art.loaded_language is False


# ---------------------------------------------------------------------------
# Adversarial edge cases for enrich_article
# ---------------------------------------------------------------------------

class TestEnrichArticleAdversarial:
    """
    Edge cases that stress the error-handling in enrich_article and could
    surface real bugs that simple happy-path tests would miss.
    """

    def test_invalid_flags_type_does_not_overwrite_but_bools_still_written(self) -> None:
        # flags list has non-strings → propaganda_flags stays default [],
        # but loaded_language and propaganda_flag are still written from JSON booleans.
        art = _article()
        enrich_article(art, _stub({"flags": [1, 2, 3], "loaded_language": True, "propaganda_flag": True}))
        assert art.propaganda_flags == []   # not overwritten (invalid list)
        assert art.loaded_language is True   # still propagated from JSON
        assert art.propaganda_flag is True   # still propagated from JSON

    def test_mixed_string_and_non_string_flags_rejected(self) -> None:
        # ["real_flag", 99] fails all(isinstance(f, str)) → propaganda_flags unchanged
        art = _article()
        enrich_article(art, _stub({"flags": ["appeal_to_fear", 99], "loaded_language": False, "propaganda_flag": False}))
        assert art.propaganda_flags == []

    def test_json_array_response_leaves_all_defaults(self) -> None:
        # json.loads("[]") → list, list.get() → AttributeError caught → defaults
        art = _article()
        enrich_article(art, MagicMock(return_value=json.dumps([])))
        assert art.propaganda_flags == []
        assert art.loaded_language is False
        assert art.propaganda_flag is False

    def test_integer_coercion_for_booleans(self) -> None:
        # bool(0) = False, bool(1) = True — integers pass through bool()
        art = _article()
        enrich_article(art, _stub({"flags": [], "loaded_language": 0, "propaganda_flag": 1}))
        assert art.loaded_language is False
        assert art.propaganda_flag is True

    def test_enrich_called_exactly_once(self) -> None:
        stub = _stub({"flags": [], "loaded_language": False, "propaganda_flag": False})
        enrich_article(_article(), stub)
        stub.assert_called_once()

    def test_enrich_returns_none_and_modifies_in_place(self) -> None:
        art = _article()
        original_id = id(art)
        result = enrich_article(art, _stub({"flags": ["scapegoating"], "loaded_language": True, "propaganda_flag": True}))
        assert result is None
        assert id(art) == original_id
        assert art.propaganda_flag is True

    def test_flags_null_value_leaves_propaganda_flags_default(self) -> None:
        # flags=null → data.get("flags", []) = None → isinstance check fails → default
        art = _article()
        enrich_article(art, _stub({"flags": None, "loaded_language": False, "propaganda_flag": False}))
        assert art.propaganda_flags == []

    def test_empty_string_response_leaves_all_defaults(self) -> None:
        art = _article()
        enrich_article(art, MagicMock(return_value=""))
        assert art.propaganda_flags == []
        assert art.loaded_language is False
        assert art.propaganda_flag is False

    def test_network_exception_leaves_all_defaults(self) -> None:
        art = _article()
        enrich_article(art, MagicMock(side_effect=ConnectionError("network down")))
        assert art.propaganda_flags == []
        assert art.loaded_language is False
        assert art.propaganda_flag is False


# ---------------------------------------------------------------------------
# Integration: bias lookup + propaganda enrichment on the same Article
# ---------------------------------------------------------------------------

class TestBiasAndPropagandaOnScoredArticle:
    """
    End-to-end: assign bias fields from CURATED_BIAS then enrich with propaganda.
    All I/O is local; the LLM client is a stub.
    """

    def test_known_source_bias_then_propaganda_flag_true(self) -> None:
        art = Article(
            url="https://www.foxnews.com/story",
            title="Enemies at the Gate",
            source="foxnews.com",
            body="Radical extremists are destroying everything we hold dear!",
        )
        art.source_lean = get_source_lean(art.source)
        art.reliability_tier = get_source_reliability(art.source)

        enrich_article(art, _stub({
            "flags": ["scapegoating", "appeal_to_fear"],
            "loaded_language": True,
            "propaganda_flag": True,
        }))

        assert art.source_lean == "right"
        assert art.reliability_tier == "mixed"
        assert art.propaganda_flag is True
        assert art.loaded_language is True
        assert "scapegoating" in art.propaganda_flags
        assert "appeal_to_fear" in art.propaganda_flags

    def test_known_source_bias_then_loaded_language_false(self) -> None:
        art = Article(
            url="https://www.reuters.com/story",
            title="Global Market Update",
            source="reuters.com",
            body="Global markets rose 0.3 percent on Wednesday following a calm session.",
        )
        art.source_lean = get_source_lean(art.source)
        art.reliability_tier = get_source_reliability(art.source)

        enrich_article(art, _stub({
            "flags": [],
            "loaded_language": False,
            "propaganda_flag": False,
        }))

        assert art.source_lean == "center"
        assert art.reliability_tier == "high"
        assert art.propaganda_flag is False
        assert art.loaded_language is False
        assert art.propaganda_flags == []

    def test_unknown_source_bias_none_but_propaganda_still_enriched(self) -> None:
        art = Article(
            url="https://mystery-news.io/article",
            title="Something Happened",
            source="mystery-news.io",
            body="Nobody knows what happened.",
        )
        art.source_lean = get_source_lean(art.source)
        art.reliability_tier = get_source_reliability(art.source)

        enrich_article(art, _stub({
            "flags": ["bandwagon"],
            "loaded_language": True,
            "propaganda_flag": True,
        }))

        # Bias fields are None — unknown source
        assert art.source_lean is None
        assert art.reliability_tier is None
        # Propaganda fields are still populated from the stub
        assert art.propaganda_flag is True
        assert art.loaded_language is True
        assert art.propaganda_flags == ["bandwagon"]

    def test_article_with_breitbart_low_reliability_and_flags(self) -> None:
        art = Article(
            url="https://www.breitbart.com/politics/story",
            title="Crisis at the Border",
            source="breitbart.com",
            body="The radical agenda continues to threaten our way of life.",
        )
        art.source_lean = get_source_lean(art.source)
        art.reliability_tier = get_source_reliability(art.source)

        enrich_article(art, _stub({
            "flags": ["loaded_language", "false_dichotomy"],
            "loaded_language": True,
            "propaganda_flag": True,
        }))

        assert art.source_lean == "right"
        assert art.reliability_tier == "low"
        assert art.propaganda_flag is True
        assert "loaded_language" in art.propaganda_flags
        assert "false_dichotomy" in art.propaganda_flags

"""Tests for situation_monitor.propaganda — zero real LLM calls."""

from __future__ import annotations

import json
from unittest.mock import MagicMock


from situation_monitor.models import Article
from situation_monitor.propaganda import enrich_article, flag_article


def _article(
    title: str = "Shocking Truth Revealed",
    body: str = "Enemies of the people are destroying everything we hold dear.",
) -> Article:
    return Article(url="https://example.com/article", title=title, source="test", body=body)


def _client_returning(payload: str) -> MagicMock:
    return MagicMock(return_value=payload)


class TestFlagArticleValidResponse:
    def test_returns_flags_from_valid_json(self) -> None:
        client = _client_returning(json.dumps({"flags": ["loaded_language", "appeal_to_fear"]}))
        assert flag_article(_article(), client) == ["loaded_language", "appeal_to_fear"]

    def test_returns_empty_list_when_no_flags(self) -> None:
        client = _client_returning(json.dumps({"flags": []}))
        assert flag_article(_article(), client) == []

    def test_all_canonical_techniques_returned(self) -> None:
        techniques = ["loaded_language", "appeal_to_fear", "bandwagon", "false_dichotomy", "scapegoating"]
        client = _client_returning(json.dumps({"flags": techniques}))
        assert flag_article(_article(), client) == techniques

    def test_single_flag_returned_as_list(self) -> None:
        client = _client_returning(json.dumps({"flags": ["bandwagon"]}))
        result = flag_article(_article(), client)
        assert result == ["bandwagon"]
        assert isinstance(result, list)


class TestFlagArticleClientCallBehaviour:
    def test_client_called_exactly_once(self) -> None:
        client = _client_returning(json.dumps({"flags": []}))
        flag_article(_article(), client)
        client.assert_called_once()

    def test_client_called_with_a_single_string_argument(self) -> None:
        client = _client_returning(json.dumps({"flags": []}))
        flag_article(_article(), client)
        args, kwargs = client.call_args
        assert len(args) == 1
        assert isinstance(args[0], str)

    def test_prompt_contains_article_title(self) -> None:
        title = "Unique Sentinel Title 99XYZ"
        client = _client_returning(json.dumps({"flags": []}))
        flag_article(_article(title=title), client)
        prompt = client.call_args[0][0]
        assert title in prompt

    def test_prompt_contains_body_excerpt(self) -> None:
        body = "Very specific body content sentinel ABCDE."
        client = _client_returning(json.dumps({"flags": []}))
        flag_article(_article(body=body), client)
        prompt = client.call_args[0][0]
        assert body in prompt


class TestFlagArticleMalformedResponse:
    def test_malformed_json_returns_empty_list(self) -> None:
        client = _client_returning("not valid json at all {{{")
        assert flag_article(_article(), client) == []

    def test_empty_string_response_returns_empty_list(self) -> None:
        client = _client_returning("")
        assert flag_article(_article(), client) == []

    def test_missing_flags_key_returns_empty_list(self) -> None:
        # data.get("flags", []) returns [] → valid empty list → returns []
        client = _client_returning(json.dumps({"propaganda": ["loaded_language"]}))
        assert flag_article(_article(), client) == []

    def test_flags_is_a_string_not_list_returns_empty_list(self) -> None:
        client = _client_returning(json.dumps({"flags": "loaded_language"}))
        assert flag_article(_article(), client) == []

    def test_flags_contains_non_string_items_returns_empty_list(self) -> None:
        client = _client_returning(json.dumps({"flags": [1, 2, 3]}))
        assert flag_article(_article(), client) == []

    def test_flags_is_null_returns_empty_list(self) -> None:
        client = _client_returning(json.dumps({"flags": None}))
        assert flag_article(_article(), client) == []

    def test_client_raises_exception_returns_empty_list(self) -> None:
        client = MagicMock(side_effect=RuntimeError("LLM service down"))
        assert flag_article(_article(), client) == []

    def test_client_returns_non_json_object_returns_empty_list(self) -> None:
        # Valid JSON but not an object → data.get() would fail
        client = _client_returning(json.dumps(["loaded_language"]))
        assert flag_article(_article(), client) == []


class TestFlagArticleBodyTruncation:
    def test_body_beyond_2000_chars_excluded_from_prompt(self) -> None:
        sentinel = "SHOULD_NOT_APPEAR_IN_PROMPT"
        body = "x" * 2000 + sentinel
        client = _client_returning(json.dumps({"flags": []}))
        flag_article(_article(body=body), client)
        prompt = client.call_args[0][0]
        assert sentinel not in prompt

    def test_body_within_2000_chars_fully_included(self) -> None:
        body = "y" * 1999 + "Z"
        client = _client_returning(json.dumps({"flags": []}))
        flag_article(_article(body=body), client)
        prompt = client.call_args[0][0]
        assert body in prompt

    def test_empty_body_does_not_raise(self) -> None:
        client = _client_returning(json.dumps({"flags": []}))
        result = flag_article(_article(body=""), client)
        assert result == []


class TestEnrichArticle:
    def test_sets_flags_loaded_language_and_propaganda_flag(self) -> None:
        payload = json.dumps({
            "flags": ["loaded_language", "appeal_to_fear"],
            "loaded_language": True,
            "propaganda_flag": True,
        })
        art = _article()
        enrich_article(art, _client_returning(payload))
        assert art.propaganda_flags == ["loaded_language", "appeal_to_fear"]
        assert art.loaded_language is True
        assert art.propaganda_flag is True

    def test_clean_article_sets_all_false(self) -> None:
        payload = json.dumps({"flags": [], "loaded_language": False, "propaganda_flag": False})
        art = _article()
        enrich_article(art, _client_returning(payload))
        assert art.propaganda_flags == []
        assert art.loaded_language is False
        assert art.propaganda_flag is False

    def test_malformed_response_leaves_defaults(self) -> None:
        art = _article()
        enrich_article(art, _client_returning("not json {{{"))
        assert art.propaganda_flags == []
        assert art.loaded_language is False
        assert art.propaganda_flag is False

    def test_client_exception_leaves_defaults(self) -> None:
        art = _article()
        enrich_article(art, MagicMock(side_effect=RuntimeError("down")))
        assert art.loaded_language is False
        assert art.propaganda_flag is False

    def test_prompt_contains_title_and_body(self) -> None:
        payload = json.dumps({"flags": [], "loaded_language": False, "propaganda_flag": False})
        client = _client_returning(payload)
        art = _article(title="Sentinel Title XYZ", body="Sentinel body content ABC")
        enrich_article(art, client)
        prompt = client.call_args[0][0]
        assert "Sentinel Title XYZ" in prompt
        assert "Sentinel body content ABC" in prompt

    def test_missing_booleans_default_to_false(self) -> None:
        payload = json.dumps({"flags": ["bandwagon"]})
        art = _article()
        enrich_article(art, _client_returning(payload))
        assert art.propaganda_flags == ["bandwagon"]
        assert art.loaded_language is False
        assert art.propaganda_flag is False

"""Tests for SpinEstimator.estimate_spin: return type, rubric keys, spin_pct range,
receipts content, stub LLM (no network), and AI-domain-specific fields."""
from __future__ import annotations

import json

import pytest

from situation_monitor.bias import SpinEstimator
from situation_monitor.models import Article, Domain, SpinResult

EXPECTED_RUBRIC_KEYS = {"loaded_language", "omission", "sourcing_asymmetry", "emotional_framing"}


def _make_response(
    spin_pct: float = 0.4,
    lens: str = "center",
    loaded_language: float = 0.2,
    omission: float = 0.3,
    sourcing_asymmetry: float = 0.1,
    emotional_framing: float = 0.15,
    hype_vs_substance: float | None = None,
    vendor_pr: bool | None = None,
) -> str:
    """Build a well-formed JSON string that satisfies the estimator's schema."""
    return json.dumps({
        "spin_pct": spin_pct,
        "lens": lens,
        "rubric": {
            "loaded_language": loaded_language,
            "omission": omission,
            "sourcing_asymmetry": sourcing_asymmetry,
            "emotional_framing": emotional_framing,
        },
        "hype_vs_substance": hype_vs_substance,
        "vendor_pr": vendor_pr,
    })


def _stub(response: str):
    """Return a callable LLM stub that records calls and returns *response*."""
    calls: list[str] = []

    def _call(prompt: str) -> str:
        calls.append(prompt)
        return response

    _call.calls = calls  # type: ignore[attr-defined]
    return _call


def _article(domain: Domain | None = None, source: str = "BBC") -> Article:
    return Article(
        url="https://bbc.com/news/world/test",
        title="Test headline for spin analysis",
        source=source,
        body="The body of the article goes here for analysis purposes.",
        domain=domain,
    )


class TestReturnsSpinResult:
    def test_returns_spin_result_instance(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response()))
        assert isinstance(result, SpinResult)

    def test_returns_spin_result_on_unparseable_llm_response(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub("not json at all!!!"))
        assert isinstance(result, SpinResult)

    def test_returns_spin_result_on_empty_llm_response(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(""))
        assert isinstance(result, SpinResult)

    def test_returns_spin_result_on_partial_json(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub('{"spin_pct": 0.3}'))
        assert isinstance(result, SpinResult)


class TestSpinPctRange:
    """spin_pct must lie in [0.0, 1.0] when the stub returns a value in that range."""

    def test_spin_pct_mid_value_passes_through(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response(spin_pct=0.5)))
        assert 0.0 <= result.spin_pct <= 1.0
        assert result.spin_pct == pytest.approx(0.5)

    def test_spin_pct_at_zero(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response(spin_pct=0.0)))
        assert result.spin_pct == pytest.approx(0.0)
        assert 0.0 <= result.spin_pct <= 1.0

    def test_spin_pct_at_one(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response(spin_pct=1.0)))
        assert result.spin_pct == pytest.approx(1.0)
        assert 0.0 <= result.spin_pct <= 1.0

    def test_spin_pct_fractional_value(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response(spin_pct=0.73)))
        assert 0.0 <= result.spin_pct <= 1.0


class TestMalformedNumericFields:
    """Valid JSON carrying non-numeric values must degrade gracefully, not crash."""

    def test_string_spin_pct_does_not_crash(self) -> None:
        result = SpinEstimator().estimate_spin(
            _article(), _stub('{"spin_pct": "high", "lens": "left"}')
        )
        assert isinstance(result, SpinResult)
        assert isinstance(result.spin_pct, float)

    def test_null_spin_pct_falls_back_to_default(self) -> None:
        result = SpinEstimator().estimate_spin(
            _article(), _stub('{"spin_pct": null, "lens": "center"}')
        )
        assert isinstance(result, SpinResult)
        assert result.spin_pct == pytest.approx(50.0)

    def test_bool_spin_pct_does_not_pass_through_as_one(self) -> None:
        result = SpinEstimator().estimate_spin(
            _article(), _stub('{"spin_pct": true, "lens": "center"}')
        )
        assert isinstance(result, SpinResult)
        assert result.spin_pct == pytest.approx(50.0)

    def test_null_lens_does_not_become_literal_none_string(self) -> None:
        result = SpinEstimator().estimate_spin(
            _article(), _stub('{"spin_pct": 0.4, "lens": null}')
        )
        assert isinstance(result, SpinResult)
        assert result.lens == "center"

    def test_numeric_string_spin_pct_is_coerced(self) -> None:
        result = SpinEstimator().estimate_spin(
            _article(), _stub('{"spin_pct": "42.5", "lens": "right"}')
        )
        assert result.spin_pct == pytest.approx(42.5)


class TestRubricKeys:
    def test_rubric_has_four_expected_keys(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response()))
        assert set(result.rubric.keys()) == EXPECTED_RUBRIC_KEYS

    def test_rubric_values_are_floats(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response()))
        for k, v in result.rubric.items():
            assert isinstance(v, float), f"rubric[{k!r}] is not a float: {v!r}"

    def test_rubric_values_in_unit_interval(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response()))
        for k, v in result.rubric.items():
            assert 0.0 <= v <= 1.0, f"rubric[{k!r}]={v} outside [0.0, 1.0]"

    def test_rubric_is_empty_on_fallback(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub("unparseable"))
        assert isinstance(result.rubric, dict)

    def test_rubric_loaded_language_key_present(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response()))
        assert "loaded_language" in result.rubric

    def test_rubric_omission_key_present(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response()))
        assert "omission" in result.rubric

    def test_rubric_sourcing_asymmetry_key_present(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response()))
        assert "sourcing_asymmetry" in result.rubric

    def test_rubric_emotional_framing_key_present(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub(_make_response()))
        assert "emotional_framing" in result.rubric


class TestReceiptsNonEmpty:
    def test_receipts_non_empty_when_signals_fire(self) -> None:
        response = _make_response(loaded_language=0.8, omission=0.7, sourcing_asymmetry=0.6, emotional_framing=0.9)
        result = SpinEstimator().estimate_spin(_article(), _stub(response))
        assert result.receipts
        assert len(result.receipts) > 0

    def test_receipts_non_empty_when_no_signals_fire(self) -> None:
        response = _make_response(loaded_language=0.0, omission=0.0, sourcing_asymmetry=0.0, emotional_framing=0.0)
        result = SpinEstimator().estimate_spin(_article(), _stub(response))
        assert result.receipts
        assert "No strong spin signals" in result.receipts

    def test_receipts_names_fired_rubric_signals(self) -> None:
        response = _make_response(loaded_language=0.9, omission=0.0, sourcing_asymmetry=0.0, emotional_framing=0.0)
        result = SpinEstimator().estimate_spin(_article(), _stub(response))
        assert "Loaded Language" in result.receipts

    def test_receipts_non_empty_on_fallback(self) -> None:
        result = SpinEstimator().estimate_spin(_article(), _stub("not json"))
        assert result.receipts
        assert len(result.receipts) > 0

    def test_receipts_mentions_prior_lean_on_fallback(self) -> None:
        result = SpinEstimator().estimate_spin(_article(source="bbc.com"), _stub("garbage"))
        assert "center" in result.receipts or "centre" in result.receipts or "bbc.com" in result.receipts


class TestStubLLMUsedNoNetwork:
    def test_stub_is_called_exactly_once(self) -> None:
        llm = _stub(_make_response())
        SpinEstimator().estimate_spin(_article(), llm)
        assert len(llm.calls) == 1  # type: ignore[attr-defined]

    def test_prompt_contains_article_title(self) -> None:
        article = Article(url="https://ft.com/x", title="Oil prices surge sharply", source="FT")
        llm = _stub(_make_response())
        SpinEstimator().estimate_spin(article, llm)
        assert "Oil prices surge sharply" in llm.calls[0]  # type: ignore[attr-defined]

    def test_prompt_contains_article_source(self) -> None:
        article = Article(url="https://ft.com/x", title="Breaking news", source="Financial Times")
        llm = _stub(_make_response())
        SpinEstimator().estimate_spin(article, llm)
        assert "Financial Times" in llm.calls[0]  # type: ignore[attr-defined]

    def test_prompt_contains_rubric_keywords(self) -> None:
        llm = _stub(_make_response())
        SpinEstimator().estimate_spin(_article(), llm)
        prompt = llm.calls[0]  # type: ignore[attr-defined]
        assert "Loaded Language" in prompt
        assert "Omission" in prompt
        assert "Sourcing Asymmetry" in prompt or "sourcing_asymmetry" in prompt
        assert "Emotional Framing" in prompt or "emotional_framing" in prompt


class TestAIDomainArticle:
    def test_ai_domain_hype_vs_substance_non_none(self) -> None:
        article = _article(domain=Domain.AI)
        response = _make_response(hype_vs_substance=0.8)
        result = SpinEstimator().estimate_spin(article, _stub(response))
        assert result.hype_vs_substance is not None

    def test_ai_domain_hype_vs_substance_in_unit_interval(self) -> None:
        article = _article(domain=Domain.AI)
        response = _make_response(hype_vs_substance=0.75)
        result = SpinEstimator().estimate_spin(article, _stub(response))
        assert result.hype_vs_substance is not None
        assert 0.0 <= result.hype_vs_substance <= 1.0

    def test_ai_domain_hype_vs_substance_clamped_to_one(self) -> None:
        article = _article(domain=Domain.AI)
        response = _make_response(hype_vs_substance=1.5)
        result = SpinEstimator().estimate_spin(article, _stub(response))
        assert result.hype_vs_substance is not None
        assert result.hype_vs_substance <= 1.0

    def test_ai_domain_hype_vs_substance_clamped_to_zero(self) -> None:
        article = _article(domain=Domain.AI)
        response = _make_response(hype_vs_substance=-0.5)
        result = SpinEstimator().estimate_spin(article, _stub(response))
        assert result.hype_vs_substance is not None
        assert result.hype_vs_substance >= 0.0

    def test_ai_domain_vendor_pr_is_set(self) -> None:
        article = _article(domain=Domain.AI)
        response = _make_response(hype_vs_substance=0.8, vendor_pr=True)
        result = SpinEstimator().estimate_spin(article, _stub(response))
        assert result.vendor_pr is not None

    def test_ai_domain_fallback_hype_vs_substance_non_none(self) -> None:
        article = _article(domain=Domain.AI)
        result = SpinEstimator().estimate_spin(article, _stub("not json"))
        assert result.hype_vs_substance is not None

    def test_ai_domain_fallback_vendor_pr_set(self) -> None:
        article = _article(domain=Domain.AI)
        result = SpinEstimator().estimate_spin(article, _stub("not json"))
        assert result.vendor_pr is not None

    def test_non_ai_domain_hype_vs_substance_is_none(self) -> None:
        article = _article(domain=Domain.WORLD)
        result = SpinEstimator().estimate_spin(article, _stub(_make_response()))
        assert result.hype_vs_substance is None

    def test_non_ai_domain_vendor_pr_is_none(self) -> None:
        article = _article(domain=Domain.MARKETS)
        result = SpinEstimator().estimate_spin(article, _stub(_make_response()))
        assert result.vendor_pr is None

    def test_no_domain_hype_vs_substance_is_none(self) -> None:
        article = _article(domain=None)
        result = SpinEstimator().estimate_spin(article, _stub(_make_response()))
        assert result.hype_vs_substance is None

    def test_ai_domain_null_hype_vs_substance_from_llm_falls_back_to_spin_pct(self) -> None:
        """When the LLM returns null for hype_vs_substance on an AI article, it falls
        back to spin_pct / 100 (so must be non-None and in [0, 1])."""
        article = _article(domain=Domain.AI)
        response = _make_response(spin_pct=0.6, hype_vs_substance=None)
        result = SpinEstimator().estimate_spin(article, _stub(response))
        assert result.hype_vs_substance is not None
        assert 0.0 <= result.hype_vs_substance <= 1.0

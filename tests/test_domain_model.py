"""Tests for the core domain model: Domain, SpinResult, Article."""
from __future__ import annotations

import pytest

from situation_monitor.models import Article, Domain, SpinResult


class TestDomain:
    def test_has_exactly_three_members(self) -> None:
        assert len(Domain) == 3

    def test_members_are_world_markets_ai(self) -> None:
        assert {m.name for m in Domain} == {"WORLD", "MARKETS", "AI"}

    def test_world_value_is_string_world(self) -> None:
        assert Domain.WORLD.value == "world"

    def test_markets_value_is_string_markets(self) -> None:
        assert Domain.MARKETS.value == "markets"

    def test_ai_value_is_string_ai(self) -> None:
        assert Domain.AI.value == "ai"

    def test_all_values_are_strings(self) -> None:
        for member in Domain:
            assert isinstance(member.value, str)

    def test_no_extra_member_beyond_three(self) -> None:
        # Any 4th member would be caught by the len check; this double-checks by name
        extra = {m.name for m in Domain} - {"WORLD", "MARKETS", "AI"}
        assert extra == set()


class TestSpinResultConstruction:
    def test_constructs_with_all_required_fields(self) -> None:
        result = SpinResult(
            spin_pct=0.4,
            lens="center",
            rubric={
                "loaded_language": 0.2,
                "omission": 0.3,
                "sourcing_asymmetry": 0.1,
                "emotional_framing": 0.4,
            },
            receipts="Spin signals fired: Emotional Framing (0.40).",
        )
        assert result.spin_pct == 0.4
        assert result.lens == "center"
        assert isinstance(result.rubric, dict)
        assert result.receipts != ""

    def test_hype_vs_substance_defaults_to_none(self) -> None:
        result = SpinResult(spin_pct=0.5, lens="left", rubric={}, receipts="x")
        assert result.hype_vs_substance is None

    def test_vendor_pr_defaults_to_none(self) -> None:
        result = SpinResult(spin_pct=0.5, lens="right", rubric={}, receipts="x")
        assert result.vendor_pr is None

    def test_hype_vs_substance_can_be_provided(self) -> None:
        result = SpinResult(spin_pct=0.7, lens="center", rubric={}, receipts="x", hype_vs_substance=0.9)
        assert result.hype_vs_substance == 0.9

    def test_vendor_pr_true_can_be_provided(self) -> None:
        result = SpinResult(spin_pct=0.2, lens="left", rubric={}, receipts="x", vendor_pr=True)
        assert result.vendor_pr is True

    def test_vendor_pr_false_can_be_provided(self) -> None:
        result = SpinResult(spin_pct=0.1, lens="right", rubric={}, receipts="x", vendor_pr=False)
        assert result.vendor_pr is False

    def test_missing_required_spin_pct_raises(self) -> None:
        with pytest.raises(TypeError):
            SpinResult(lens="center", rubric={}, receipts="x")  # type: ignore[call-arg]

    def test_missing_required_lens_raises(self) -> None:
        with pytest.raises(TypeError):
            SpinResult(spin_pct=0.5, rubric={}, receipts="x")  # type: ignore[call-arg]

    def test_missing_required_rubric_raises(self) -> None:
        with pytest.raises(TypeError):
            SpinResult(spin_pct=0.5, lens="center", receipts="x")  # type: ignore[call-arg]

    def test_missing_required_receipts_raises(self) -> None:
        with pytest.raises(TypeError):
            SpinResult(spin_pct=0.5, lens="center", rubric={})  # type: ignore[call-arg]


class TestArticleDomainField:
    def test_domain_defaults_to_none(self) -> None:
        article = Article(url="https://example.com/a", title="Test headline", source="TestSource")
        assert article.domain is None

    def test_domain_accepts_world(self) -> None:
        article = Article(
            url="https://example.com/a",
            title="Test headline",
            source="TestSource",
            domain=Domain.WORLD,
        )
        assert article.domain is Domain.WORLD

    def test_domain_accepts_markets(self) -> None:
        article = Article(
            url="https://example.com/b",
            title="Market news",
            source="TestSource",
            domain=Domain.MARKETS,
        )
        assert article.domain is Domain.MARKETS

    def test_domain_accepts_ai(self) -> None:
        article = Article(
            url="https://example.com/c",
            title="AI news",
            source="TestSource",
            domain=Domain.AI,
        )
        assert article.domain is Domain.AI

    def test_domain_none_explicitly_accepted(self) -> None:
        article = Article(
            url="https://example.com/d",
            title="Generic news",
            source="TestSource",
            domain=None,
        )
        assert article.domain is None

    def test_domain_can_be_reassigned(self) -> None:
        article = Article(url="https://example.com/e", title="T", source="S")
        article.domain = Domain.AI
        assert article.domain is Domain.AI

    def test_empty_url_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="url"):
            Article(url="", title="Title", source="Source")

    def test_empty_title_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="title"):
            Article(url="https://example.com/a", title="", source="Source")

    def test_empty_source_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="source"):
            Article(url="https://example.com/a", title="Title", source="")

    def test_default_body_is_empty_string(self) -> None:
        article = Article(url="https://example.com/a", title="T", source="S")
        assert article.body == ""

    def test_tags_default_to_empty_list(self) -> None:
        article = Article(url="https://example.com/a", title="T", source="S")
        assert article.tags == []

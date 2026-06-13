"""Tests for the deterministic, offline spin estimator (lexicon + deterministic_spin).

These guard the headline product promise — "spin made measurable" — actually
holding without an LLM: neutral copy scores ~0, charged copy scores high,
opposing framings of one event produce a real non-zero spin_delta, and every
score is explainable via named fired terms.
"""

from __future__ import annotations

import pytest

from situation_monitor.dual_lens import deterministic_spin, group_by_event
from situation_monitor.lexicon import score_text
from situation_monitor.models import Article


def _article(title: str, source: str = "unknown.com", body: str = "", **kw) -> Article:
    return Article(url=f"https://{source}/x", title=title, source=source, body=body, **kw)


class TestScoreText:
    def test_neutral_text_scores_zero(self) -> None:
        s = score_text(
            "Central bank holds interest rates steady",
            "The central bank kept its benchmark rate unchanged and said it would monitor data.",
        )
        assert s.spin_pct == pytest.approx(0.0)
        assert s.fired == {}

    def test_charged_text_scores_above_neutral(self) -> None:
        neutral = score_text("Committee reviews proposed budget", "Members discussed the budget.")
        charged = score_text(
            "Reckless regime threatens to destroy economy",
            "Critics warn the disastrous policy will devastate jobs.",
        )
        assert charged.spin_pct > neutral.spin_pct
        assert charged.spin_pct > 50.0

    def test_score_is_bounded_zero_to_hundred(self) -> None:
        s = score_text(
            "Threatens destroy crush devastate slam blast hammer torch ravage smash",
            "warn fear panic terror crisis disaster catastrophe doom peril meltdown",
        )
        assert 0.0 <= s.spin_pct <= 100.0

    def test_scoring_is_deterministic(self) -> None:
        a = score_text("Markets surge as fears mount", "Investors panic over the looming crisis.")
        b = score_text("Markets surge as fears mount", "Investors panic over the looming crisis.")
        assert a.spin_pct == b.spin_pct
        assert a.fired == b.fired

    def test_title_terms_weighted_more_than_body(self) -> None:
        in_title = score_text("Regime threatens economy", "A routine update was issued.")
        in_body = score_text("A routine update was issued", "Regime threatens economy.")
        assert in_title.spin_pct > in_body.spin_pct

    def test_receipts_name_the_fired_terms(self) -> None:
        s = score_text("Government threatens to destroy jobs", "")
        assert "threatens" in s.receipts()
        assert "destroy" in s.receipts()

    def test_receipts_neutral_message_when_nothing_fires(self) -> None:
        s = score_text("Quarterly report published on schedule", "")
        assert "neutral framing" in s.receipts().lower()

    def test_empty_input_scores_zero(self) -> None:
        assert score_text("", "").spin_pct == pytest.approx(0.0)


class TestDeterministicSpin:
    def test_lens_follows_source_lean_override(self) -> None:
        art = _article("Some headline", source="obscure.example", source_lean="left")
        assert deterministic_spin(art).lens == "left"

    def test_lens_falls_back_to_source_prior(self) -> None:
        assert "left" in deterministic_spin(_article("Headline", source="cnn.com")).lens
        assert "right" in deterministic_spin(_article("Headline", source="foxnews.com")).lens

    def test_charged_article_scores_higher_than_neutral(self) -> None:
        charged = deterministic_spin(_article(
            "Reckless regime threatens to destroy the economy", source="cnn.com",
            body="Critics warn of looming disaster.",
        ))
        neutral = deterministic_spin(_article(
            "Central bank publishes quarterly report", source="cnn.com",
            body="The report covered routine indicators.",
        ))
        assert charged.spin_pct > neutral.spin_pct

    def test_receipts_are_populated(self) -> None:
        result = deterministic_spin(_article("Markets surge amid panic", source="reuters.com"))
        assert result.receipts


class TestDefaultPipelineMeasuresSpin:
    """The default group_by_event path (no spin_fn) must yield a real spin_delta."""

    def test_opposing_framings_produce_nonzero_spin_delta(self) -> None:
        left = _article(
            "Government Climate Policy Reform Backed by Scientists",
            source="left-news.example",
            body="Climate scientists endorse sweeping government climate policy reform proposals.",
            source_lean="left",
        )
        right = _article(
            "Government Climate Policy Reform Threatens Economic Growth",
            source="right-news.example",
            body="Business groups warn the reform will destroy jobs and hamper economic growth.",
            source_lean="right",
        )
        events = group_by_event([left, right])
        assert len(events) == 1
        assert events[0].spin_delta > 0.0

    def test_neutral_only_event_has_zero_spin(self) -> None:
        a = _article(
            "Central bank holds interest rates steady today",
            source="reuters.com",
            body="The bank kept its benchmark rate unchanged pending further data.",
        )
        events = group_by_event([a])
        assert events[0].center_articles[0].spin.spin_pct == pytest.approx(0.0)

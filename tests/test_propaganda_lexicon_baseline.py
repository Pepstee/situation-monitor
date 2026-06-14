"""Tests for the deterministic, offline propaganda baseline.

These pin the behaviour that makes the digest's propaganda layer genuinely work
without an LLM: a neutral wire report yields no flags, a framed headline yields
the exact techniques that fired, and the baseline never downgrades an LLM
positive (OR-merge semantics).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from situation_monitor.models import Article
from situation_monitor.propaganda import (
    apply_lexicon_baseline,
    enrich_article,
    lexicon_signal,
)


def _article(title: str, body: str = "") -> Article:
    return Article(url="https://example.com/a", title=title, source="example.com", body=body)


class TestLexiconSignal:
    def test_neutral_headline_yields_no_signal(self) -> None:
        flags, loaded, flagged = lexicon_signal(
            _article("EUR/USD Falls as Fed Signals Prolonged High Rates")
        )
        assert flags == []
        assert loaded is False
        assert flagged is False

    def test_charged_verb_headline_flags_loaded_language(self) -> None:
        flags, loaded, flagged = lexicon_signal(
            _article("Government Reform Threatens Economic Growth")
        )
        assert "loaded_language" in flags
        assert loaded is True
        assert flagged is True

    def test_endorsement_headline_flags_glittering_generalities(self) -> None:
        flags, loaded, flagged = lexicon_signal(
            _article("Historic Reform Backed and Praised by Scientists")
        )
        assert "glittering_generalities" in flags
        assert flagged is True

    def test_fear_framing_flags_appeal_to_fear(self) -> None:
        flags, _loaded, flagged = lexicon_signal(
            _article("Looming Catastrophe Sparks Panic and Alarm")
        )
        assert "appeal_to_fear" in flags
        assert flagged is True

    def test_signal_is_deterministic(self) -> None:
        art = _article("Reckless Regime Slams Reform")
        assert lexicon_signal(art) == lexicon_signal(art)


class TestApplyLexiconBaseline:
    def test_populates_clean_article_from_lexicon(self) -> None:
        art = _article("Crude Oil Prices Surge on OPEC Supply Cut Extension")
        apply_lexicon_baseline(art)
        assert art.propaganda_flag is True
        assert art.loaded_language is True
        assert "loaded_language" in art.propaganda_flags

    def test_leaves_neutral_article_clean(self) -> None:
        art = _article("S&P 500 Hits Record High on Strong Earnings Season")
        apply_lexicon_baseline(art)
        assert art.propaganda_flag is False
        assert art.loaded_language is False
        assert art.propaganda_flags == []

    def test_never_downgrades_existing_llm_positive(self) -> None:
        # A neutral headline whose LLM said "propaganda" must stay flagged.
        art = _article("Quiet Market Session")
        art.propaganda_flag = True
        art.loaded_language = True
        art.propaganda_flags = ["scapegoating"]
        apply_lexicon_baseline(art)
        assert art.propaganda_flag is True
        assert art.loaded_language is True
        assert "scapegoating" in art.propaganda_flags

    def test_merges_without_duplicating_flags(self) -> None:
        art = _article("Reform Threatens Growth")
        art.propaganda_flags = ["loaded_language"]
        apply_lexicon_baseline(art)
        assert art.propaganda_flags.count("loaded_language") == 1

    def test_baseline_fills_in_after_offline_llm_enrichment(self) -> None:
        # The offline backend returns a score blob with no propaganda keys, so
        # enrich_article leaves everything default; the baseline must populate it.
        offline = MagicMock(return_value=json.dumps({"score": 0.5}))
        art = _article("Government Reform Threatens Economic Growth")
        enrich_article(art, offline)
        assert art.propaganda_flag is False  # LLM contributed nothing
        apply_lexicon_baseline(art)
        assert art.propaganda_flag is True
        assert art.loaded_language is True

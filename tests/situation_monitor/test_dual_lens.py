"""Adversarial tests for dual-lens cross-lens pairing logic (situation_monitor/dual_lens.py).

Focus: articles from opposite political lenses are correctly paired into the same
DualLensEvent; spin_fn determines bucket assignment; cluster vocabulary growth enables
transitive pairing; edge cases around lens inference and spin_delta computation.
"""

from __future__ import annotations

import urllib.parse

import pytest

from situation_monitor.dual_lens import (
    AnnotatedArticle,
    DualLensEvent,
    _avg_spin,
    _lean_bucket,
    _significant_words,
    _stub_spin,
    group_by_event,
)
from situation_monitor.models import Article, SpinResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _article(
    title: str,
    source: str = "unknown.com",
    source_lean: str | None = None,
    **kwargs,
) -> Article:
    slug = urllib.parse.quote(title.lower()[:40], safe="")
    url = kwargs.pop("url", f"https://{source}/{slug}")
    a = Article(url=url, title=title, source=source, **kwargs)
    a.source_lean = source_lean
    return a


def _spin(pct: float, lens: str) -> SpinResult:
    return SpinResult(spin_pct=pct, lens=lens, rubric={}, receipts="test")


def _fixed_spin(pct: float, lens: str):
    def _fn(article: Article) -> SpinResult:
        return _spin(pct, lens)
    return _fn


def _map_spin(lean_map: dict[str, tuple[float, str]]):
    """Dispatch on article.source → (spin_pct, lens)."""
    def _fn(article: Article) -> SpinResult:
        pct, lens = lean_map.get(article.source, (50.0, "center"))
        return _spin(pct, lens)
    return _fn


# ---------------------------------------------------------------------------
# Cross-lens pairing: same event, opposite lenses cluster together
# ---------------------------------------------------------------------------


class TestCrossLensPairing:
    LEFT_TITLE = "Belfast ceasefire talks collapse as unionist leaders walk out today"
    RIGHT_TITLE = "Belfast ceasefire talks derailed by republican demands at negotiations"

    def _left(self) -> Article:
        return _article(self.LEFT_TITLE, "cnn.com", source_lean="left")

    def _right(self) -> Article:
        return _article(self.RIGHT_TITLE, "foxnews.com", source_lean="right")

    def test_opposite_lens_articles_cluster_into_single_event(self):
        result = group_by_event([self._left(), self._right()])
        assert len(result) == 1, "Both Belfast articles must cluster into one DualLensEvent"

    def test_left_article_in_left_bucket(self):
        result = group_by_event([self._left(), self._right()])
        sources = {aa.article.source for aa in result[0].left_articles}
        assert "cnn.com" in sources

    def test_right_article_in_right_bucket(self):
        result = group_by_event([self._left(), self._right()])
        sources = {aa.article.source for aa in result[0].right_articles}
        assert "foxnews.com" in sources

    def test_neither_article_lost(self):
        result = group_by_event([self._left(), self._right()])
        event = result[0]
        total = len(event.left_articles) + len(event.right_articles) + len(event.center_articles)
        assert total == 2

    def test_center_bucket_empty_for_two_opposite_lens_articles(self):
        result = group_by_event([self._left(), self._right()])
        assert result[0].center_articles == []

    def test_spin_delta_positive_for_opposite_lenses(self):
        """Different lenses must produce a non-zero spin_delta."""
        spin_map = {"cnn.com": (80.0, "left"), "foxnews.com": (40.0, "right")}
        result = group_by_event([self._left(), self._right()], spin_fn=_map_spin(spin_map))
        assert result[0].spin_delta == pytest.approx(40.0)

    def test_spin_delta_zero_when_both_lenses_equal_spin_pct(self):
        spin_map = {"cnn.com": (60.0, "left"), "foxnews.com": (60.0, "right")}
        result = group_by_event([self._left(), self._right()], spin_fn=_map_spin(spin_map))
        assert result[0].spin_delta == pytest.approx(0.0)

    def test_order_independence_left_first(self):
        fwd = group_by_event([self._left(), self._right()])
        rev = group_by_event([self._right(), self._left()])
        assert len(fwd) == 1
        assert len(rev) == 1
        fwd_left_sources = {aa.article.source for aa in fwd[0].left_articles}
        rev_left_sources = {aa.article.source for aa in rev[0].left_articles}
        assert fwd_left_sources == rev_left_sources

    def test_paired_event_spin_delta_always_non_negative(self):
        """abs() must ensure delta is non-negative even when right spin exceeds left."""
        spin_map = {"cnn.com": (20.0, "left"), "foxnews.com": (90.0, "right")}
        result = group_by_event([self._left(), self._right()], spin_fn=_map_spin(spin_map))
        assert result[0].spin_delta >= 0.0


# ---------------------------------------------------------------------------
# spin_fn lens determines bucket, not source_lean attribute
# ---------------------------------------------------------------------------


class TestSpinFnDeterminesBucket:
    def test_spin_fn_right_overrides_left_source_lean(self):
        """If spin_fn returns lens='right' for a left-leaning source, article goes to right bucket."""
        article = _article("Belfast talks collapse amid tensions today", "cnn.com", source_lean="left")
        result = group_by_event([article], spin_fn=_fixed_spin(40.0, "right"))
        assert len(result[0].right_articles) == 1
        assert result[0].left_articles == []

    def test_spin_fn_left_overrides_right_source_lean(self):
        """spin_fn result wins over article.source_lean for bucket placement."""
        article = _article("Senate tax bill passes amid controversy today", "foxnews.com", source_lean="right")
        result = group_by_event([article], spin_fn=_fixed_spin(75.0, "left"))
        assert len(result[0].left_articles) == 1
        assert result[0].right_articles == []

    def test_spin_fn_center_overrides_extreme_source_lean(self):
        article = _article("Federal Reserve raises interest rates today", "breitbart.com", source_lean="right")
        result = group_by_event([article], spin_fn=_fixed_spin(30.0, "center"))
        assert len(result[0].center_articles) == 1
        assert result[0].right_articles == []

    def test_left_center_lens_routes_to_left_bucket(self):
        """'left-center' must be treated as left, not center."""
        article = _article("Climate policy reform endorsed by scientists globally", "nytimes.com")
        result = group_by_event([article], spin_fn=_fixed_spin(55.0, "left-center"))
        assert len(result[0].left_articles) == 1
        assert result[0].right_articles == []
        assert result[0].center_articles == []

    def test_right_center_lens_routes_to_right_bucket(self):
        """'right-center' must be treated as right, not center."""
        article = _article("Senate approves sweeping tax reform package today", "wsj.com")
        result = group_by_event([article], spin_fn=_fixed_spin(45.0, "right-center"))
        assert len(result[0].right_articles) == 1
        assert result[0].left_articles == []
        assert result[0].center_articles == []

    def test_unknown_lens_string_routes_to_center(self):
        article = _article("Belfast trade deals face new hurdles today", "thehill.com")
        result = group_by_event([article], spin_fn=_fixed_spin(50.0, "libertarian"))
        assert len(result[0].center_articles) == 1
        assert result[0].left_articles == []
        assert result[0].right_articles == []


# ---------------------------------------------------------------------------
# Cross-lens pairing with 3+ articles
# ---------------------------------------------------------------------------


class TestThreeWayCrossLensPairing:
    def test_three_way_event_left_right_center_all_paired(self):
        left = _article("Belfast peace process collapses under political pressure today", "cnn.com")
        right = _article("Belfast peace process attacked by nationalist opponents today", "foxnews.com")
        center = _article("Belfast peace process faces fresh challenges ahead today", "reuters.com")
        spin_map = {
            "cnn.com": (80.0, "left"),
            "foxnews.com": (70.0, "right"),
            "reuters.com": (30.0, "center"),
        }
        result = group_by_event([left, right, center], spin_fn=_map_spin(spin_map))
        assert len(result) == 1
        event = result[0]
        assert len(event.left_articles) == 1
        assert len(event.right_articles) == 1
        assert len(event.center_articles) == 1

    def test_two_left_one_right_buckets_correct(self):
        left1 = _article("Belfast ceasefire deal collapses amid violence today", "cnn.com")
        left2 = _article("Belfast ceasefire deal under threat from militant groups", "huffpost.com")
        right = _article("Belfast ceasefire deal opposed strongly by unionist leaders", "foxnews.com")
        spin_map = {
            "cnn.com": (80.0, "left"),
            "huffpost.com": (75.0, "left"),
            "foxnews.com": (30.0, "right"),
        }
        result = group_by_event([left1, left2, right], spin_fn=_map_spin(spin_map))
        assert len(result) == 1
        event = result[0]
        assert len(event.left_articles) == 2
        assert len(event.right_articles) == 1

    def test_spin_delta_averages_across_multiple_articles_per_side(self):
        """avg_left=(80+70)/2=75; avg_right=(30+40)/2=35; delta=40."""
        left1 = _article("Belfast ceasefire deal collapses amid violence today", "cnn.com")
        left2 = _article("Belfast ceasefire deal under threat from violent groups", "huffpost.com")
        right1 = _article("Belfast ceasefire deal opposed strongly by unionists today", "foxnews.com")
        right2 = _article("Belfast ceasefire deal fails despite international pressure", "breitbart.com")
        spin_map = {
            "cnn.com": (80.0, "left"),
            "huffpost.com": (70.0, "left"),
            "foxnews.com": (30.0, "right"),
            "breitbart.com": (40.0, "right"),
        }
        result = group_by_event([left1, left2, right1, right2], spin_fn=_map_spin(spin_map))
        assert len(result) == 1
        assert result[0].spin_delta == pytest.approx(40.0)

    def test_center_articles_do_not_affect_spin_delta(self):
        """Center articles must not be included in either avg_left or avg_right."""
        left = _article("Global climate summit begins negotiations in Geneva today", "cnn.com")
        right = _article("Global climate summit opens with disputes in Geneva today", "foxnews.com")
        center = _article("Global climate summit proceedings unfold in Geneva", "reuters.com")
        spin_map = {
            "cnn.com": (80.0, "left"),
            "foxnews.com": (30.0, "right"),
            "reuters.com": (50.0, "center"),
        }
        result_without_center = group_by_event([left, right], spin_fn=_map_spin(spin_map))
        result_with_center = group_by_event([left, right, center], spin_fn=_map_spin(spin_map))
        # delta must be the same regardless of center article presence
        assert result_without_center[0].spin_delta == pytest.approx(
            result_with_center[0].spin_delta
        )


# ---------------------------------------------------------------------------
# Transitive cross-lens pairing via cluster vocabulary growth
# ---------------------------------------------------------------------------


class TestTransitiveCrossLensPairing:
    def test_third_article_joins_via_shared_vocab_with_second(self):
        """C shares 2 words with B's vocabulary that was added after A+B merged."""
        a = _article("Belfast ceasefire agreement signed today formally", "cnn.com")
        b = _article("Belfast ceasefire agreement under pressure from parties", "foxnews.com")
        # c shares "ceasefire agreement" with the grown cluster vocabulary
        c = _article("Ceasefire agreement collapsed under sustained political pressure", "reuters.com")
        result = group_by_event([a, b, c])
        assert len(result) == 1, "All three articles must cluster transitively"

    def test_transitive_cluster_preserves_cross_lens_bucket_assignment(self):
        a = _article("Belfast ceasefire agreement signed formally today", "cnn.com")
        b = _article("Belfast ceasefire agreement faces political opposition today", "foxnews.com")
        c = _article("Ceasefire agreement details unveiled amid negotiations today", "reuters.com")
        spin_map = {
            "cnn.com": (80.0, "left"),
            "foxnews.com": (35.0, "right"),
            "reuters.com": (50.0, "center"),
        }
        result = group_by_event([a, b, c], spin_fn=_map_spin(spin_map))
        assert len(result) == 1
        event = result[0]
        assert len(event.left_articles) == 1
        assert len(event.right_articles) == 1
        assert len(event.center_articles) == 1

    def test_unrelated_event_stays_separate(self):
        belfast1 = _article("Belfast ceasefire agreement announced today formally", "cnn.com")
        belfast2 = _article("Belfast ceasefire agreement faces opposition challenges", "foxnews.com")
        unrelated = _article("SpaceX launches new rocket towards lunar orbit today", "bbc.com")
        result = group_by_event([belfast1, belfast2, unrelated])
        assert len(result) == 2

    def test_no_spurious_cross_event_merging(self):
        """Two clearly distinct events must NOT merge even with shared common words."""
        ev1_a = _article("Federal Reserve raises interest rates sharply today", "reuters.com")
        ev1_b = _article("Federal Reserve rate hike impacts global financial markets", "cnn.com")
        ev2_a = _article("SpaceX rocket launches successfully towards moon orbit", "bbc.com")
        ev2_b = _article("SpaceX rocket mission achieves lunar orbit insertion successfully", "foxnews.com")
        result = group_by_event([ev1_a, ev1_b, ev2_a, ev2_b])
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Stub spin uses source_lean attribute when available
# ---------------------------------------------------------------------------


class TestStubSpinSourceLeanIntegration:
    def test_stub_spin_uses_source_lean_left(self):
        article = _article("Belfast ceasefire talks resume", "obscure-left-blog.io", source_lean="left")
        spin = _stub_spin(article)
        assert spin.lens == "left"

    def test_stub_spin_uses_source_lean_right(self):
        article = _article("Tax reform passed", "obscure-right-blog.io", source_lean="right")
        spin = _stub_spin(article)
        assert spin.lens == "right"

    def test_stub_spin_falls_back_to_prior_for_unknown_source(self):
        """No source_lean set → fall back to ALLSIDES_PRIORS via _prior_lean."""
        article = _article("Local news story", "totally-unknown-source-xyz-2026.io")
        spin = _stub_spin(article)
        # Unknown source defaults to center
        assert spin.lens == "center"

    def test_stub_spin_uses_prior_for_known_source_without_lean(self):
        """cnn.com in CURATED_BIAS → left, even when source_lean is None."""
        article = _article("Breaking news today", "cnn.com")
        spin = _stub_spin(article)
        assert "left" in spin.lens

    def test_group_by_event_uses_source_lean_for_bucketing_with_default_spin_fn(self):
        """source_lean='right' on article → right bucket when using default spin_fn."""
        article = _article("Senate approves sweeping tax reform bill today", "unknown-right.io", source_lean="right")
        result = group_by_event([article])
        assert len(result[0].right_articles) == 1
        assert result[0].left_articles == []

    def test_group_by_event_two_opposite_leans_pair_with_default_spin_fn(self):
        """source_lean sets the lens so both articles pair into left and right buckets."""
        left = _article("Belfast peace process collapses amid political pressure", "left-outlet.io", source_lean="left")
        right = _article("Belfast peace process derailed by republican demands here", "right-outlet.io", source_lean="right")
        result = group_by_event([left, right])
        assert len(result) == 1
        assert result[0].left_articles
        assert result[0].right_articles


# ---------------------------------------------------------------------------
# High-significance cross-lens event detection
# ---------------------------------------------------------------------------


class TestHighSignificanceEvent:
    def test_large_spin_delta_indicates_high_significance(self):
        """spin_delta > 50 means the two sides frame the event very differently."""
        left = _article("Belfast ceasefire deal seen as historic breakthrough today", "cnn.com")
        right = _article("Belfast ceasefire deal condemned as nationalist capitulation today", "foxnews.com")
        spin_map = {"cnn.com": (95.0, "left"), "foxnews.com": (10.0, "right")}
        result = group_by_event([left, right], spin_fn=_map_spin(spin_map))
        assert result[0].spin_delta > 50.0

    def test_max_spin_delta_bounded_by_100(self):
        """spin_pct range is 0–100, so delta can be at most 100 (0 vs 100)."""
        left = _article("Belfast ceasefire deal signed by all parties today", "cnn.com")
        right = _article("Belfast ceasefire deal breaks down completely today", "foxnews.com")
        spin_map = {"cnn.com": (100.0, "left"), "foxnews.com": (0.0, "right")}
        result = group_by_event([left, right], spin_fn=_map_spin(spin_map))
        assert result[0].spin_delta == pytest.approx(100.0)

    def test_symmetric_event_has_zero_delta(self):
        """Same framing on both sides → delta must be exactly zero."""
        left = _article("Climate summit opens with optimism across parties today", "cnn.com")
        right = _article("Climate summit proceedings start with positive exchanges", "foxnews.com")
        spin_map = {"cnn.com": (50.0, "left"), "foxnews.com": (50.0, "right")}
        result = group_by_event([left, right], spin_fn=_map_spin(spin_map))
        assert result[0].spin_delta == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Return-type invariants for cross-lens events
# ---------------------------------------------------------------------------


class TestReturnTypeInvariants:
    def test_each_element_is_dual_lens_event_instance(self):
        left = _article("Belfast peace process collapses today formally", "cnn.com")
        right = _article("Belfast peace process attacked by nationalist groups", "foxnews.com")
        for item in group_by_event([left, right]):
            assert isinstance(item, DualLensEvent)

    def test_annotated_article_links_to_original_article_object(self):
        original = _article("Belfast peace process collapses today", "cnn.com")
        result = group_by_event([original], spin_fn=_fixed_spin(70.0, "left"))
        aa = result[0].left_articles[0]
        assert aa.article is original

    def test_annotated_article_spin_is_returned_by_spin_fn(self):
        article = _article("Belfast peace process stalls today", "cnn.com")
        result = group_by_event([article], spin_fn=_fixed_spin(87.0, "left"))
        aa = result[0].left_articles[0]
        assert aa.spin.spin_pct == pytest.approx(87.0)
        assert aa.spin.lens == "left"

    def test_spin_delta_is_float_for_cross_lens_event(self):
        left = _article("Belfast ceasefire announced formally today", "cnn.com")
        right = _article("Belfast ceasefire condemned strongly today", "foxnews.com")
        spin_map = {"cnn.com": (80.0, "left"), "foxnews.com": (30.0, "right")}
        event = group_by_event([left, right], spin_fn=_map_spin(spin_map))[0]
        assert isinstance(event.spin_delta, float)

    def test_total_articles_conserved_across_cross_lens_events(self):
        """Every input article must appear in exactly one bucket of exactly one event."""
        articles = [
            _article("Federal Reserve raises interest rates today sharply", "reuters.com"),
            _article("SpaceX launches rocket towards moon today", "bbc.com"),
            _article("Federal Reserve rate hike impacts markets today broadly", "cnn.com"),
        ]
        result = group_by_event(articles)
        total = sum(
            len(e.left_articles) + len(e.right_articles) + len(e.center_articles)
            for e in result
        )
        assert total == 3

    def test_event_title_is_longest_title_in_cluster(self):
        short = _article("Belfast peace talks stall today", "cnn.com")
        long = _article(
            "Belfast peace talks stall amid bitter political disagreements over border issues",
            "foxnews.com",
        )
        spin_map = {"cnn.com": (80.0, "left"), "foxnews.com": (30.0, "right")}
        result = group_by_event([short, long], spin_fn=_map_spin(spin_map))
        assert len(result) == 1
        assert result[0].event_title == long.title

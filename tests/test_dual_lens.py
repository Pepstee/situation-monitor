"""Adversarial pytest suite for situation_monitor.dual_lens.

Covers: empty input, single-article, clustering, bucket assignment, spin_delta
computation, single-lens events, and the Belfast scenario.
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
# Test helpers
# ---------------------------------------------------------------------------

def make_article(title: str, source: str = "unknown.com", **kwargs) -> Article:
    slug = urllib.parse.quote(title.lower(), safe="")
    url = kwargs.pop("url", f"https://{source}/{slug}")
    return Article(url=url, title=title, source=source, **kwargs)


def make_spin(spin_pct: float, lens: str) -> SpinResult:
    return SpinResult(spin_pct=spin_pct, lens=lens, rubric={}, receipts="test")


def fixed_spin(spin_pct: float, lens: str):
    """spin_fn that returns the same SpinResult for every article."""
    def _fn(article: Article) -> SpinResult:
        return make_spin(spin_pct, lens)
    return _fn


def lean_spin_fn(lean_map: dict[str, tuple[float, str]]):
    """spin_fn that dispatches on article.source to get (spin_pct, lens)."""
    def _fn(article: Article) -> SpinResult:
        spin_pct, lens = lean_map.get(article.source, (50.0, "center"))
        return make_spin(spin_pct, lens)
    return _fn


# ---------------------------------------------------------------------------
# _significant_words
# ---------------------------------------------------------------------------

class TestSignificantWords:
    def test_strips_known_stopwords(self) -> None:
        words = _significant_words("The peace process in Belfast")
        assert "the" not in words
        assert "in" not in words

    def test_retains_meaningful_content_words(self) -> None:
        words = _significant_words("Belfast peace process erupts")
        assert "belfast" in words
        assert "peace" in words
        assert "process" in words
        assert "erupts" in words

    def test_strips_punctuation_before_splitting(self) -> None:
        words = _significant_words("Belfast: 'peace' falters!")
        assert "belfast" in words
        assert "peace" in words
        assert "falters" in words
        # punctuation must not appear as part of any token
        for w in words:
            assert "'" not in w and ":" not in w and "!" not in w

    def test_lowercases_all_words(self) -> None:
        words = _significant_words("BELFAST Peace PROCESS")
        assert "belfast" in words
        assert "peace" in words
        assert "process" in words

    def test_empty_title_returns_empty_frozenset(self) -> None:
        assert _significant_words("") == frozenset()

    def test_all_stopwords_returns_empty(self) -> None:
        result = _significant_words("the a an in of to is by")
        assert result == frozenset()

    def test_short_words_two_chars_or_fewer_excluded(self) -> None:
        # "AI" → "ai" (len 2) excluded; "fire" (len 4) kept
        words = _significant_words("AI is on fire")
        assert "ai" not in words
        assert "is" not in words
        assert "on" not in words
        assert "fire" in words

    def test_returns_frozenset(self) -> None:
        result = _significant_words("Belfast peace process")
        assert isinstance(result, frozenset)

    def test_words_three_chars_included(self) -> None:
        # "war" has 3 chars → included
        words = _significant_words("war broke out")
        assert "war" in words


# ---------------------------------------------------------------------------
# _lean_bucket
# ---------------------------------------------------------------------------

class TestLeanBucket:
    def test_left_maps_to_left(self) -> None:
        assert _lean_bucket("left") == "left"

    def test_left_center_maps_to_left(self) -> None:
        assert _lean_bucket("left-center") == "left"

    def test_right_maps_to_right(self) -> None:
        assert _lean_bucket("right") == "right"

    def test_right_center_maps_to_right(self) -> None:
        assert _lean_bucket("right-center") == "right"

    def test_center_maps_to_center(self) -> None:
        assert _lean_bucket("center") == "center"

    def test_unrecognised_string_maps_to_center(self) -> None:
        assert _lean_bucket("libertarian") == "center"
        assert _lean_bucket("unknown") == "center"

    def test_empty_string_maps_to_center(self) -> None:
        assert _lean_bucket("") == "center"


# ---------------------------------------------------------------------------
# _avg_spin
# ---------------------------------------------------------------------------

class TestAvgSpin:
    def test_empty_list_returns_zero(self) -> None:
        assert _avg_spin([]) == 0.0

    def test_single_article_returns_its_spin(self) -> None:
        aa = AnnotatedArticle(
            article=make_article("Belfast talks resume"),
            spin=make_spin(80.0, "left"),
        )
        assert _avg_spin([aa]) == pytest.approx(80.0)

    def test_two_articles_averaged(self) -> None:
        a1 = AnnotatedArticle(article=make_article("Event one"), spin=make_spin(60.0, "left"))
        a2 = AnnotatedArticle(article=make_article("Event two"), spin=make_spin(40.0, "left"))
        assert _avg_spin([a1, a2]) == pytest.approx(50.0)

    def test_three_articles_averaged_correctly(self) -> None:
        articles = [
            AnnotatedArticle(article=make_article(f"Article {i}"), spin=make_spin(float(i * 10), "left"))
            for i in range(1, 4)  # 10, 20, 30 → 20.0
        ]
        assert _avg_spin(articles) == pytest.approx(20.0)

    def test_zero_spin_articles_average_zero(self) -> None:
        articles = [
            AnnotatedArticle(article=make_article("Neutral piece"), spin=make_spin(0.0, "center"))
            for _ in range(3)
        ]
        assert _avg_spin(articles) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# group_by_event: empty input (acceptance criterion)
# ---------------------------------------------------------------------------

class TestGroupByEventEmpty:
    def test_empty_list_returns_empty_list(self) -> None:
        assert group_by_event([]) == []

    def test_return_type_is_list_on_empty_input(self) -> None:
        assert isinstance(group_by_event([]), list)


# ---------------------------------------------------------------------------
# group_by_event: single article
# ---------------------------------------------------------------------------

class TestGroupByEventSingleArticle:
    def test_produces_exactly_one_event(self) -> None:
        article = make_article("Belfast peace talks collapse today", source="cnn.com")
        result = group_by_event([article], spin_fn=fixed_spin(70.0, "left"))
        assert len(result) == 1

    def test_event_title_matches_article_title(self) -> None:
        title = "Belfast peace talks collapse today"
        article = make_article(title, source="cnn.com")
        result = group_by_event([article], spin_fn=fixed_spin(70.0, "left"))
        assert result[0].event_title == title

    def test_single_left_article_has_empty_right_and_center(self) -> None:
        article = make_article("Belfast peace talks collapse today", source="cnn.com")
        result = group_by_event([article], spin_fn=fixed_spin(70.0, "left"))
        event = result[0]
        assert len(event.left_articles) == 1
        assert event.right_articles == []
        assert event.center_articles == []

    def test_single_right_article_has_empty_left_and_center(self) -> None:
        article = make_article("Senate tax reform bill approved today", source="foxnews.com")
        result = group_by_event([article], spin_fn=fixed_spin(60.0, "right"))
        event = result[0]
        assert event.left_articles == []
        assert len(event.right_articles) == 1
        assert event.center_articles == []

    def test_single_center_article_has_empty_left_and_right(self) -> None:
        article = make_article("Central bank raises rates amid inflation fears", source="reuters.com")
        result = group_by_event([article], spin_fn=fixed_spin(20.0, "center"))
        event = result[0]
        assert event.left_articles == []
        assert event.right_articles == []
        assert len(event.center_articles) == 1


# ---------------------------------------------------------------------------
# group_by_event: clustering by semantic title overlap (acceptance criterion)
# ---------------------------------------------------------------------------

class TestGroupByEventClustering:
    def test_similar_titles_cluster_regardless_of_source(self) -> None:
        a1 = make_article("Belfast peace process collapses under political pressure", source="cnn.com")
        a2 = make_article("Belfast peace process under threat from extremist groups", source="foxnews.com")
        result = group_by_event([a1, a2])
        assert len(result) == 1, "Articles sharing ≥2 significant words must cluster"

    def test_three_sources_different_leans_same_cluster(self) -> None:
        """Clustering is title-driven; source lean must not prevent grouping."""
        left = make_article("Belfast ceasefire talks resume amid pressure today", source="cnn.com")
        right = make_article("Belfast ceasefire talks threatened by nationalist groups", source="foxnews.com")
        center = make_article("Belfast ceasefire talks continue despite rising tensions", source="reuters.com")
        result = group_by_event([left, right, center])
        assert len(result) == 1

    def test_dissimilar_titles_produce_separate_events(self) -> None:
        a1 = make_article("Federal Reserve raises interest rates sharply today", source="reuters.com")
        a2 = make_article("SpaceX launches rocket towards lunar orbit today", source="bbc.com")
        result = group_by_event([a1, a2])
        assert len(result) == 2

    def test_exactly_two_shared_words_merges(self) -> None:
        """_MIN_OVERLAP == 2: exactly 2 shared significant words IS enough to merge."""
        a1 = make_article("Belfast election results disputed strongly by unionists", source="cnn.com")
        a2 = make_article("Scotland election results shock nationalist supporters today", source="foxnews.com")
        # shared: "election", "results" → 2 ≥ 2 → merge
        result = group_by_event([a1, a2])
        assert len(result) == 1

    def test_exactly_one_shared_word_does_not_merge(self) -> None:
        """1 shared significant word is below _MIN_OVERLAP; must NOT merge."""
        a1 = make_article("Belfast flooding causes widespread infrastructure damage", source="bbc.com")
        a2 = make_article("Tokyo flooding impacts millions across coastal regions", source="reuters.com")
        # shared: only "flooding" → 1 < 2 → no merge
        result = group_by_event([a1, a2])
        assert len(result) == 2

    def test_event_title_is_longest_article_title_in_cluster(self) -> None:
        short = make_article("Belfast peace talks stall", source="cnn.com")
        long = make_article(
            "Belfast peace talks stall amid bitter political disagreements over border",
            source="foxnews.com",
        )
        result = group_by_event([short, long])
        assert len(result) == 1
        assert result[0].event_title == long.title

    def test_cluster_vocabulary_grows_transitively(self) -> None:
        """Article C can join the cluster formed by A+B using B's words, even if C
        barely overlaps with A alone."""
        a = make_article("Belfast ceasefire agreement signed today", source="cnn.com")
        b = make_article("Belfast ceasefire agreement under pressure from parties", source="foxnews.com")
        # c shares "ceasefire agreement" with the growing cluster vocabulary
        c = make_article("Ceasefire agreement collapsed under intense political pressure", source="bbc.com")
        result = group_by_event([a, b, c])
        assert len(result) == 1

    def test_zero_significant_word_article_forms_own_cluster(self) -> None:
        """A title made entirely of stopwords cannot share ≥2 words with anyone."""
        a = make_article("The is an in of to", source="cnn.com")
        b = make_article("Belfast peace process latest developments today", source="foxnews.com")
        result = group_by_event([a, b])
        # "the is an in of to" → empty sig-word set → no overlap with anything → own cluster
        assert len(result) == 2


# ---------------------------------------------------------------------------
# group_by_event: left/right/center buckets match source lean (acceptance criterion)
# ---------------------------------------------------------------------------

class TestGroupByEventBuckets:
    def test_left_source_lands_in_left_bucket(self) -> None:
        article = make_article("Belfast peace process collapses amid tensions", source="cnn.com")
        spin_map = {"cnn.com": (70.0, "left")}
        result = group_by_event([article], spin_fn=lean_spin_fn(spin_map))
        assert len(result[0].left_articles) == 1
        assert result[0].right_articles == []

    def test_right_source_lands_in_right_bucket(self) -> None:
        article = make_article("Senate approves sweeping tax reform package", source="foxnews.com")
        spin_map = {"foxnews.com": (65.0, "right")}
        result = group_by_event([article], spin_fn=lean_spin_fn(spin_map))
        assert len(result[0].right_articles) == 1
        assert result[0].left_articles == []

    def test_center_source_lands_in_center_bucket(self) -> None:
        article = make_article("Interest rates decision sparks market reaction", source="reuters.com")
        spin_map = {"reuters.com": (25.0, "center")}
        result = group_by_event([article], spin_fn=lean_spin_fn(spin_map))
        assert len(result[0].center_articles) == 1
        assert result[0].left_articles == []
        assert result[0].right_articles == []

    def test_left_center_lens_routes_to_left_bucket(self) -> None:
        article = make_article("Belfast peace process stalls in latest talks", source="nytimes.com")
        result = group_by_event([article], spin_fn=fixed_spin(55.0, "left-center"))
        assert len(result[0].left_articles) == 1
        assert result[0].right_articles == []

    def test_right_center_lens_routes_to_right_bucket(self) -> None:
        article = make_article("Senate approves tax reform bill today", source="wsj.com")
        result = group_by_event([article], spin_fn=fixed_spin(45.0, "right-center"))
        assert len(result[0].right_articles) == 1
        assert result[0].left_articles == []

    def test_three_way_split_across_buckets(self) -> None:
        articles = [
            make_article("Belfast peace process collapses under pressure", source="cnn.com"),
            make_article("Belfast peace process attacked by political opponents", source="foxnews.com"),
            make_article("Belfast peace process faces fresh challenges today", source="reuters.com"),
        ]
        spin_map = {
            "cnn.com": (80.0, "left"),
            "foxnews.com": (70.0, "right"),
            "reuters.com": (30.0, "center"),
        }
        result = group_by_event(articles, spin_fn=lean_spin_fn(spin_map))
        assert len(result) == 1
        event = result[0]
        assert len(event.left_articles) == 1
        assert len(event.right_articles) == 1
        assert len(event.center_articles) == 1

    def test_multiple_left_articles_all_in_left_bucket(self) -> None:
        articles = [
            make_article("Belfast peace process collapses under political pressure", source="cnn.com"),
            make_article("Belfast peace process stalls amid unionist objections", source="huffpost.com"),
        ]
        spin_map = {
            "cnn.com": (70.0, "left"),
            "huffpost.com": (80.0, "left"),
        }
        result = group_by_event(articles, spin_fn=lean_spin_fn(spin_map))
        assert len(result) == 1
        event = result[0]
        assert len(event.left_articles) == 2
        assert event.right_articles == []


# ---------------------------------------------------------------------------
# group_by_event: spin_delta computation (acceptance criterion)
# ---------------------------------------------------------------------------

class TestSpinDelta:
    def test_equal_spin_both_sides_delta_is_zero(self) -> None:
        articles = [
            make_article("Global climate summit begins negotiations in Geneva", source="cnn.com"),
            make_article("Global climate summit opens with disputes in Geneva", source="foxnews.com"),
        ]
        spin_map = {
            "cnn.com": (60.0, "left"),
            "foxnews.com": (60.0, "right"),
        }
        result = group_by_event(articles, spin_fn=lean_spin_fn(spin_map))
        assert result[0].spin_delta == pytest.approx(0.0)

    def test_delta_is_absolute_difference_of_averages(self) -> None:
        articles = [
            make_article("Global climate summit begins negotiations in Geneva", source="cnn.com"),
            make_article("Global climate summit opens with disputes in Geneva", source="foxnews.com"),
        ]
        spin_map = {
            "cnn.com": (80.0, "left"),
            "foxnews.com": (30.0, "right"),
        }
        result = group_by_event(articles, spin_fn=lean_spin_fn(spin_map))
        assert result[0].spin_delta == pytest.approx(50.0)

    def test_delta_is_always_non_negative(self) -> None:
        """abs() ensures delta is non-negative even when right spin > left spin."""
        articles = [
            make_article("Global climate summit begins negotiations in Geneva", source="cnn.com"),
            make_article("Global climate summit opens with disputes in Geneva", source="foxnews.com"),
        ]
        spin_map = {
            "cnn.com": (20.0, "left"),
            "foxnews.com": (90.0, "right"),
        }
        result = group_by_event(articles, spin_fn=lean_spin_fn(spin_map))
        assert result[0].spin_delta >= 0.0

    def test_delta_averages_across_multiple_articles_per_side(self) -> None:
        """avg_left = (60+80)/2 = 70; avg_right = (30+50)/2 = 40; delta = 30."""
        articles = [
            make_article("Belfast ceasefire deal collapses amid violence today", source="cnn.com"),
            make_article("Belfast ceasefire deal under threat from militant groups", source="huffpost.com"),
            make_article("Belfast ceasefire deal opposed strongly by unionist leaders", source="foxnews.com"),
            make_article("Belfast ceasefire deal fails despite sustained international effort", source="breitbart.com"),
        ]
        spin_map = {
            "cnn.com": (60.0, "left"),
            "huffpost.com": (80.0, "left"),
            "foxnews.com": (30.0, "right"),
            "breitbart.com": (50.0, "right"),
        }
        result = group_by_event(articles, spin_fn=lean_spin_fn(spin_map))
        assert len(result) == 1
        assert result[0].spin_delta == pytest.approx(30.0)

    def test_single_left_only_delta_is_zero(self) -> None:
        """No right articles → no opposing framing → delta is 0.

        spin_delta measures divergence between LEFT and RIGHT framings. With only
        a left article there is no right side to diverge from; the absent bucket's
        0.0 average must not leak through as if the right framed the event at 0%.
        """
        article = make_article("Belfast peace talks stall amid tensions", source="cnn.com")
        result = group_by_event([article], spin_fn=fixed_spin(75.0, "left"))
        assert result[0].right_articles == []
        assert result[0].spin_delta == pytest.approx(0.0)

    def test_single_right_only_delta_is_zero(self) -> None:
        """No left articles → no opposing framing → delta is 0 (symmetric case)."""
        article = make_article("Senate tax reform package wins crucial approval", source="foxnews.com")
        result = group_by_event([article], spin_fn=fixed_spin(65.0, "right"))
        assert result[0].left_articles == []
        assert result[0].spin_delta == pytest.approx(0.0)

    def test_only_center_articles_delta_is_zero(self) -> None:
        """Center articles contribute to neither left nor right avg → delta = 0."""
        articles = [
            make_article("Interest rate decision causes market reaction today", source="reuters.com"),
            make_article("Interest rate decision sends markets higher today", source="bbc.com"),
        ]
        result = group_by_event(articles, spin_fn=fixed_spin(40.0, "center"))
        assert result[0].spin_delta == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# group_by_event: single-lens events (acceptance criterion)
# ---------------------------------------------------------------------------

class TestSingleLensEvent:
    def test_only_left_returns_valid_dual_lens_event(self) -> None:
        article = make_article("Belfast peace talks break down completely today", source="cnn.com")
        result = group_by_event([article], spin_fn=fixed_spin(80.0, "left"))
        assert isinstance(result[0], DualLensEvent)

    def test_only_left_right_articles_is_empty_list(self) -> None:
        articles = [
            make_article("Belfast peace process collapses amid latest talks", source="cnn.com"),
            make_article("Belfast peace process faces new obstacles today", source="huffpost.com"),
        ]
        result = group_by_event(articles, spin_fn=fixed_spin(70.0, "left"))
        assert result[0].right_articles == []

    def test_only_left_center_articles_is_empty_list(self) -> None:
        articles = [
            make_article("Belfast peace process collapses amid latest talks", source="cnn.com"),
            make_article("Belfast peace process faces new obstacles today", source="huffpost.com"),
        ]
        result = group_by_event(articles, spin_fn=fixed_spin(70.0, "left"))
        assert result[0].center_articles == []

    def test_only_left_contains_all_input_articles(self) -> None:
        articles = [
            make_article("Belfast peace process collapses amid latest talks", source="cnn.com"),
            make_article("Belfast peace process faces new obstacles today", source="huffpost.com"),
        ]
        result = group_by_event(articles, spin_fn=fixed_spin(70.0, "left"))
        assert len(result[0].left_articles) == 2

    def test_only_right_left_articles_is_empty_list(self) -> None:
        articles = [
            make_article("Senate passes sweeping tax reform package today", source="foxnews.com"),
            make_article("Senate tax reform package wins final approval vote", source="breitbart.com"),
        ]
        result = group_by_event(articles, spin_fn=fixed_spin(60.0, "right"))
        assert result[0].left_articles == []
        assert result[0].center_articles == []

    def test_only_center_both_sides_empty(self) -> None:
        articles = [
            make_article("Central bank raises interest rates amid inflation", source="reuters.com"),
            make_article("Central bank rates decision surprises financial markets", source="bbc.com"),
        ]
        result = group_by_event(articles, spin_fn=fixed_spin(25.0, "center"))
        event = result[0]
        assert event.left_articles == []
        assert event.right_articles == []
        assert len(event.center_articles) == 2


# ---------------------------------------------------------------------------
# Belfast scenario (acceptance criterion)
# ---------------------------------------------------------------------------

class TestBelfastScenario:
    """Two fixture articles about the same Belfast event, one from a left-lean source
    (high spin_pct) and one from a right-lean source (different framing).
    Both must appear in the same DualLensEvent.
    """

    LEFT_TITLE = (
        "Belfast peace process collapses as unionist leaders walk out of crucial talks"
    )
    RIGHT_TITLE = (
        "Belfast peace process derailed by republican demands at crucial negotiations"
    )

    def _left_article(self) -> Article:
        return Article(
            url="https://www.cnn.com/2026/06/13/uk/belfast-peace-left",
            title=self.LEFT_TITLE,
            source="cnn.com",
            body=(
                "The peace process in Belfast suffered a major blow today as unionist leaders "
                "abruptly walked out of talks, blaming the government for failing to address "
                "their core concerns about border arrangements."
            ),
            source_lean="left",
        )

    def _right_article(self) -> Article:
        return Article(
            url="https://www.foxnews.com/world/belfast-peace-right",
            title=self.RIGHT_TITLE,
            source="foxnews.com",
            body=(
                "Peace talks in Belfast have been derailed by escalating republican demands, "
                "sources say, with nationalist groups refusing to accept the latest compromise "
                "proposals tabled by mediators."
            ),
            source_lean="right",
        )

    def _spin_fn(self, article: Article) -> SpinResult:
        if "cnn" in article.source:
            return make_spin(85.0, "left")
        if "fox" in article.source:
            return make_spin(40.0, "right")
        return make_spin(50.0, "center")

    def test_both_articles_in_single_event(self) -> None:
        result = group_by_event([self._left_article(), self._right_article()], spin_fn=self._spin_fn)
        assert len(result) == 1, "Both Belfast articles must cluster into the same DualLensEvent"

    def test_cnn_article_in_left_bucket(self) -> None:
        result = group_by_event([self._left_article(), self._right_article()], spin_fn=self._spin_fn)
        left_sources = {aa.article.source for aa in result[0].left_articles}
        assert "cnn.com" in left_sources

    def test_fox_article_in_right_bucket(self) -> None:
        result = group_by_event([self._left_article(), self._right_article()], spin_fn=self._spin_fn)
        right_sources = {aa.article.source for aa in result[0].right_articles}
        assert "foxnews.com" in right_sources

    def test_spin_delta_reflects_framing_difference(self) -> None:
        """avg_left=85, avg_right=40 → delta=45."""
        result = group_by_event([self._left_article(), self._right_article()], spin_fn=self._spin_fn)
        assert result[0].spin_delta == pytest.approx(45.0)

    def test_center_bucket_empty(self) -> None:
        result = group_by_event([self._left_article(), self._right_article()], spin_fn=self._spin_fn)
        assert result[0].center_articles == []

    def test_left_article_source_lean_matches_bucket(self) -> None:
        """article.source_lean='left' aligns with placement in left_articles."""
        result = group_by_event([self._left_article(), self._right_article()], spin_fn=self._spin_fn)
        for aa in result[0].left_articles:
            assert aa.article.source_lean == "left"

    def test_right_article_source_lean_matches_bucket(self) -> None:
        """article.source_lean='right' aligns with placement in right_articles."""
        result = group_by_event([self._left_article(), self._right_article()], spin_fn=self._spin_fn)
        for aa in result[0].right_articles:
            assert aa.article.source_lean == "right"

    def test_annotated_article_carries_correct_spin(self) -> None:
        """AnnotatedArticle.spin must be the SpinResult returned by spin_fn."""
        result = group_by_event([self._left_article()], spin_fn=self._spin_fn)
        aa = result[0].left_articles[0]
        assert aa.spin.spin_pct == pytest.approx(85.0)
        assert aa.spin.lens == "left"

    def test_no_articles_lost(self) -> None:
        result = group_by_event([self._left_article(), self._right_article()], spin_fn=self._spin_fn)
        event = result[0]
        total = len(event.left_articles) + len(event.right_articles) + len(event.center_articles)
        assert total == 2

    def test_order_independence(self) -> None:
        """Swapping article order must not change cluster membership."""
        fwd = group_by_event([self._left_article(), self._right_article()], spin_fn=self._spin_fn)
        rev = group_by_event([self._right_article(), self._left_article()], spin_fn=self._spin_fn)
        assert len(fwd) == 1
        assert len(rev) == 1
        fwd_left = {aa.article.source for aa in fwd[0].left_articles}
        rev_left = {aa.article.source for aa in rev[0].left_articles}
        assert fwd_left == rev_left


# ---------------------------------------------------------------------------
# _stub_spin (default spin_fn)
# ---------------------------------------------------------------------------

class TestStubSpin:
    def test_known_left_source_returns_left_lens(self) -> None:
        article = make_article("Belfast peace process collapses", source="cnn.com")
        spin = _stub_spin(article)
        assert "left" in spin.lens

    def test_known_right_source_returns_right_lens(self) -> None:
        article = make_article("Tax reform bill approved", source="foxnews.com")
        spin = _stub_spin(article)
        assert "right" in spin.lens

    def test_known_center_source_returns_center_lens(self) -> None:
        article = make_article("Central bank decision", source="bbc.com")
        spin = _stub_spin(article)
        assert spin.lens == "center"

    def test_unknown_source_defaults_to_center_lens(self) -> None:
        article = make_article("Local news story", source="totally-obscure-outlet-xyz-2026.io")
        spin = _stub_spin(article)
        assert spin.lens == "center"

    def test_fixed_spin_pct_is_fifty(self) -> None:
        article = make_article("Climate summit opens", source="reuters.com")
        spin = _stub_spin(article)
        assert spin.spin_pct == pytest.approx(50.0)

    def test_returns_spin_result_instance(self) -> None:
        article = make_article("Economy report released", source="bloomberg.com")
        spin = _stub_spin(article)
        assert isinstance(spin, SpinResult)

    def test_default_spin_fn_buckets_cnn_as_left(self) -> None:
        """When spin_fn is omitted, cnn.com articles must land in left bucket."""
        article = make_article("Belfast peace process collapses under pressure", source="cnn.com")
        result = group_by_event([article])
        assert len(result[0].left_articles) == 1

    def test_default_spin_fn_buckets_bbc_as_center(self) -> None:
        """When spin_fn is omitted, bbc.com articles must land in center bucket."""
        article = make_article("Belfast peace process faces new challenges", source="bbc.com")
        result = group_by_event([article])
        assert len(result[0].center_articles) == 1


# ---------------------------------------------------------------------------
# Return type and invariant guarantees
# ---------------------------------------------------------------------------

class TestReturnTypeGuarantees:
    def test_each_element_is_dual_lens_event_instance(self) -> None:
        articles = [
            make_article("Economy report released today", source="reuters.com"),
            make_article("Space mission launches from Florida", source="bbc.com"),
        ]
        for item in group_by_event(articles):
            assert isinstance(item, DualLensEvent)

    def test_all_bucket_fields_are_lists(self) -> None:
        article = make_article("Belfast peace process latest update", source="cnn.com")
        event = group_by_event([article])[0]
        assert isinstance(event.left_articles, list)
        assert isinstance(event.right_articles, list)
        assert isinstance(event.center_articles, list)

    def test_spin_delta_is_float(self) -> None:
        article = make_article("Belfast peace process latest update", source="cnn.com")
        event = group_by_event([article])[0]
        assert isinstance(event.spin_delta, float)

    def test_total_articles_preserved_across_multiple_events(self) -> None:
        """Every input article must appear in exactly one bucket of exactly one event."""
        articles = [
            make_article("Federal Reserve raises interest rates sharply", source="reuters.com"),
            make_article("SpaceX launches rocket towards lunar orbit", source="bbc.com"),
            make_article("Federal Reserve rate hike impacts global markets", source="cnn.com"),
        ]
        result = group_by_event(articles)
        total = sum(
            len(e.left_articles) + len(e.right_articles) + len(e.center_articles)
            for e in result
        )
        assert total == 3

    def test_event_title_is_non_empty_string(self) -> None:
        article = make_article("Belfast peace process latest update today", source="cnn.com")
        event = group_by_event([article])[0]
        assert isinstance(event.event_title, str)
        assert len(event.event_title) > 0

    def test_annotated_article_links_back_to_original_article(self) -> None:
        original = make_article("Belfast peace process collapses", source="cnn.com")
        result = group_by_event([original], spin_fn=fixed_spin(70.0, "left"))
        aa = result[0].left_articles[0]
        assert aa.article is original

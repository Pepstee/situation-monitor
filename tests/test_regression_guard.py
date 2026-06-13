"""Regression guard: verifies all acceptance criteria and guards core code paths.

Tests:
  1. Module smoke test — every situation_monitor submodule imports without error.
  2. Acceptance script — exits 0, stdout contains 'Situation Monitor' + domain headers.
  3. Belfast constraint — at least one DualLensEvent has both left_articles and
     right_articles non-empty using real fixture RSS feeds.
  4. Core-flow integration — ingest→enrich→dual-lens→digest using fixture data.
  5. Edge-case regression guards for dedup, alerting, reliability, spin, digest.
"""

from __future__ import annotations

import importlib
import io
import json
import subprocess
import textwrap
import urllib.parse
from datetime import datetime
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


def _article(title: str, source: str = "example.com", source_lean: str | None = None, **kwargs):
    from situation_monitor.models import Article

    slug = urllib.parse.quote(title.lower()[:50], safe="")
    url = kwargs.pop("url", f"https://{source}/{slug}")
    a = Article(url=url, title=title, source=source, **kwargs)
    a.source_lean = source_lean
    return a


def _spin(pct: float, lens: str):
    from situation_monitor.models import SpinResult

    return SpinResult(spin_pct=pct, lens=lens, rubric={}, receipts="test")


class _LocalFileClient:
    def get(self, url: str) -> bytes:
        return Path(url).read_bytes()


# ---------------------------------------------------------------------------
# 1. Module smoke test — all submodules must be importable
# ---------------------------------------------------------------------------


class TestModuleImports:
    """Each situation_monitor module imports without raising ImportError."""

    MODULES = [
        "situation_monitor",
        "situation_monitor.models",
        "situation_monitor.config",
        "situation_monitor.bias",
        "situation_monitor.dual_lens",
        "situation_monitor.dedup",
        "situation_monitor.relevance",
        "situation_monitor.reliability",
        "situation_monitor.alerting",
        "situation_monitor.propaganda",
        "situation_monitor.digest",
        "situation_monitor.dashboard",
        "situation_monitor.llm",
        "situation_monitor.practical",
        "situation_monitor.polymarket",
        "situation_monitor.scheduler",
        "situation_monitor.__main__",
        "situation_monitor.ingestion",
        "situation_monitor.ingestion.base",
        "situation_monitor.ingestion.rss",
        "situation_monitor.ingestion.hn",
        "situation_monitor.ingestion.crypto",
        "situation_monitor.ingestion.github_trending",
    ]

    @pytest.mark.parametrize("module_name", MODULES)
    def test_module_importable(self, module_name: str) -> None:
        """Importing this module must not raise ImportError."""
        try:
            importlib.import_module(module_name)
        except ImportError as exc:
            pytest.fail(f"ImportError when importing {module_name!r}: {exc}")

    def test_package_exposes_dual_lens_symbols(self) -> None:
        """situation_monitor.__init__ re-exports AnnotatedArticle, DualLensEvent, group_by_event."""
        import situation_monitor as sm

        assert hasattr(sm, "AnnotatedArticle"), "AnnotatedArticle must be re-exported"
        assert hasattr(sm, "DualLensEvent"), "DualLensEvent must be re-exported"
        assert hasattr(sm, "group_by_event"), "group_by_event must be re-exported"

    def test_package_exposes_practical_symbols(self) -> None:
        """situation_monitor.__init__ re-exports PracticalMover and fetch functions."""
        import situation_monitor as sm

        assert hasattr(sm, "PracticalMover"), "PracticalMover must be re-exported"
        assert hasattr(sm, "fetch_practical_movers"), "fetch_practical_movers must be re-exported"
        assert hasattr(sm, "fetch_regulatory_movers"), "fetch_regulatory_movers must be re-exported"

    def test_version_attribute_present(self) -> None:
        import situation_monitor as sm

        assert hasattr(sm, "__version__"), "__version__ must be set"
        assert isinstance(sm.__version__, str) and sm.__version__, "__version__ must be a non-empty string"


# ---------------------------------------------------------------------------
# 2. Acceptance script regression guard
# ---------------------------------------------------------------------------


def _run_acceptance() -> subprocess.CompletedProcess:
    cmd = ACCEPTANCE_FILE.read_text().strip()
    return subprocess.run(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        timeout=30,
        cwd=PROJECT_ROOT,
    )


class TestAcceptanceScript:
    """Acceptance script must exit 0 and produce correct stdout content."""

    def test_acceptance_file_present(self) -> None:
        assert ACCEPTANCE_FILE.exists(), "acceptance file must exist at project root"

    def test_acceptance_file_non_empty(self) -> None:
        assert ACCEPTANCE_FILE.read_text().strip(), "acceptance file must not be empty"

    def test_acceptance_exits_zero(self) -> None:
        result = _run_acceptance()
        assert result.returncode == 0, (
            f"acceptance script exited {result.returncode}; "
            f"stdout={result.stdout[:300]!r}"
        )

    def test_acceptance_stdout_contains_situation_monitor(self) -> None:
        result = _run_acceptance()
        assert b"Situation Monitor" in result.stdout, (
            "acceptance stdout must contain 'Situation Monitor'"
        )

    def test_acceptance_stdout_contains_at_least_one_domain_header(self) -> None:
        """Stdout must contain at least one domain section header: WORLD, MARKETS, or AI."""
        result = _run_acceptance()
        stdout = result.stdout.decode(errors="replace")
        assert any(d in stdout for d in ("WORLD", "MARKETS", "AI")), (
            "acceptance stdout must contain at least one domain header (WORLD, MARKETS, AI)"
        )

    def test_acceptance_stdout_contains_article_url(self) -> None:
        """At least one HTTP URL must appear in the digest output."""
        result = _run_acceptance()
        stdout = result.stdout.decode(errors="replace")
        assert "http" in stdout, "acceptance stdout must contain at least one URL"

    def test_acceptance_stdout_does_not_contain_traceback(self) -> None:
        """No Python traceback should appear in the acceptance output."""
        result = _run_acceptance()
        stdout = result.stdout.decode(errors="replace")
        assert "Traceback" not in stdout, "acceptance stdout must not contain a traceback"

    def test_acceptance_produces_markdown_heading(self) -> None:
        """Stdout must begin with a Markdown heading (# ...)."""
        result = _run_acceptance()
        stdout = result.stdout.decode(errors="replace")
        heading_lines = [l for l in stdout.splitlines() if l.startswith("#")]
        assert heading_lines, "acceptance stdout must contain at least one Markdown heading"


# ---------------------------------------------------------------------------
# 3. Belfast constraint regression guard
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def belfast_articles():
    from situation_monitor.config import SourceDef
    from situation_monitor.ingestion.rss import RSSFetcher
    from situation_monitor.models import Domain

    client = _LocalFileClient()
    fetcher = RSSFetcher(client=client)

    left_sd = SourceDef(
        url=str(FIXTURES / "rss_left.xml"),
        name="Left News Feed",
        domain=Domain.WORLD,
        lens="left",
    )
    right_sd = SourceDef(
        url=str(FIXTURES / "rss_right.xml"),
        name="Right News Feed",
        domain=Domain.WORLD,
        lens="right",
    )

    articles = []
    articles.extend(fetcher.fetch(left_sd.url, source_def=left_sd))
    articles.extend(fetcher.fetch(right_sd.url, source_def=right_sd))
    assert articles, "Fixture files must produce articles"
    return articles


@pytest.fixture(scope="module")
def belfast_events(belfast_articles):
    from situation_monitor.dual_lens import group_by_event

    return group_by_event(belfast_articles)


class TestBelfastConstraint:
    """Core Belfast acceptance criterion: both lens columns populated for a shared event."""

    def test_both_left_and_right_articles_present_in_event(self, belfast_events) -> None:
        """At least one DualLensEvent must have both left_articles AND right_articles non-empty."""
        dual = [e for e in belfast_events if e.left_articles and e.right_articles]
        assert dual, (
            "Belfast constraint FAILED: no DualLensEvent has both left_articles "
            "AND right_articles non-empty"
        )

    def test_left_column_non_empty_across_all_events(self, belfast_events) -> None:
        all_left = [aa for e in belfast_events for aa in e.left_articles]
        assert all_left, "At least one left-leaning article must appear across all events"

    def test_right_column_non_empty_across_all_events(self, belfast_events) -> None:
        all_right = [aa for e in belfast_events for aa in e.right_articles]
        assert all_right, "At least one right-leaning article must appear across all events"

    def test_no_article_is_lost(self, belfast_articles, belfast_events) -> None:
        """Every ingested article must appear in exactly one event bucket."""
        total = sum(
            len(e.left_articles) + len(e.right_articles) + len(e.center_articles)
            for e in belfast_events
        )
        assert total == len(belfast_articles), (
            f"Article count mismatch: ingested {len(belfast_articles)}, "
            f"placed in events {total}"
        )

    def test_climate_event_has_both_columns(self, belfast_events) -> None:
        """The 'climate policy reform' event must have articles in both left and right columns."""
        climate = [
            e
            for e in belfast_events
            if any(
                "climate" in aa.article.title.lower()
                for aa in e.left_articles + e.right_articles + e.center_articles
            )
        ]
        assert climate, "No climate-related DualLensEvent found"
        event = climate[0]
        assert event.left_articles, "Climate event must have left_articles"
        assert event.right_articles, "Climate event must have right_articles"

    def test_spin_delta_non_negative(self, belfast_events) -> None:
        """spin_delta must never be negative."""
        for event in belfast_events:
            assert event.spin_delta >= 0.0, (
                f"spin_delta must be ≥ 0; got {event.spin_delta!r} for {event.event_title!r}"
            )

    def test_event_title_is_non_empty_string(self, belfast_events) -> None:
        for event in belfast_events:
            assert isinstance(event.event_title, str) and event.event_title.strip(), (
                f"event_title must be a non-empty string; got {event.event_title!r}"
            )

    def test_left_articles_carry_left_lean(self, belfast_events) -> None:
        """Articles in left_articles must have a 'left' lens in their SpinResult."""
        for event in belfast_events:
            for aa in event.left_articles:
                assert "left" in aa.spin.lens, (
                    f"Left-bucket article has unexpected lens: {aa.spin.lens!r}"
                )

    def test_right_articles_carry_right_lean(self, belfast_events) -> None:
        for event in belfast_events:
            for aa in event.right_articles:
                assert "right" in aa.spin.lens, (
                    f"Right-bucket article has unexpected lens: {aa.spin.lens!r}"
                )

    def test_annotated_article_has_receipts(self, belfast_events) -> None:
        for event in belfast_events:
            for aa in event.left_articles + event.right_articles + event.center_articles:
                assert aa.spin.receipts, "SpinResult.receipts must be a non-empty string"


# ---------------------------------------------------------------------------
# 4. group_by_event edge cases
# ---------------------------------------------------------------------------


class TestGroupByEventEdgeCases:
    def test_empty_input_returns_empty_list(self) -> None:
        from situation_monitor.dual_lens import group_by_event

        assert group_by_event([]) == []

    def test_single_article_becomes_single_event(self) -> None:
        from situation_monitor.dual_lens import group_by_event

        a = _article("Breaking news about the Federal Reserve interest rates", "reuters.com")
        events = group_by_event([a])
        assert len(events) == 1
        total = sum(
            len(e.left_articles) + len(e.right_articles) + len(e.center_articles)
            for e in events
        )
        assert total == 1

    def test_unrelated_articles_form_separate_events(self) -> None:
        from situation_monitor.dual_lens import group_by_event

        a1 = _article("Federal Reserve raises interest rates again sharply")
        a2 = _article("Hurricane makes landfall along southern Florida coast")
        events = group_by_event([a1, a2])
        assert len(events) == 2, (
            "Unrelated articles must not be merged into one event"
        )

    def test_related_articles_merged_into_one_event(self) -> None:
        from situation_monitor.dual_lens import group_by_event

        a1 = _article("Trump signs executive order on immigration policy reform")
        a2 = _article("Trump executive order immigration policy faces court challenge")
        events = group_by_event([a1, a2])
        assert len(events) == 1, (
            "Articles sharing ≥2 significant words must merge into one DualLensEvent"
        )

    def test_custom_spin_fn_overrides_default(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import SpinResult

        call_log: list[str] = []

        def custom_spin(article) -> SpinResult:
            call_log.append(article.title)
            return SpinResult(spin_pct=99.0, lens="right", rubric={}, receipts="custom")

        articles = [_article(f"Unique article title number {i}") for i in range(3)]
        events = group_by_event(articles, spin_fn=custom_spin)
        assert len(call_log) == 3, "spin_fn must be called once per article"
        for event in events:
            all_aa = event.left_articles + event.right_articles + event.center_articles
            for aa in all_aa:
                assert aa.spin.spin_pct == 99.0

    def test_lean_bucket_determines_column(self) -> None:
        """Articles with left/right source_lean end up in left_articles/right_articles."""
        from situation_monitor.dual_lens import group_by_event

        left_art = _article("Climate reform backed by scientists experts endorse policy", source_lean="left")
        right_art = _article("Climate reform threatens economic growth jobs policy experts", source_lean="right")
        events = group_by_event([left_art, right_art])
        dual = [e for e in events if e.left_articles and e.right_articles]
        assert dual, "Left and right articles about climate must land in a shared DualLensEvent"

    def test_all_articles_accounted_for(self) -> None:
        from situation_monitor.dual_lens import group_by_event

        articles = [_article(f"Article about topic {chr(65 + i)} specific unique words", url=f"https://example.com/{i}") for i in range(5)]
        events = group_by_event(articles)
        total = sum(
            len(e.left_articles) + len(e.right_articles) + len(e.center_articles)
            for e in events
        )
        assert total == len(articles)

    def test_spin_delta_equals_abs_diff_of_avg_spins(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import SpinResult

        sides = iter([
            SpinResult(spin_pct=80.0, lens="left", rubric={}, receipts="l"),
            SpinResult(spin_pct=20.0, lens="right", rubric={}, receipts="r"),
        ])

        def alternating_spin(article):
            return next(sides)

        a1 = _article("Global trade policy reform tariff economic impact debate", source_lean="left", url="https://left.com/1")
        a2 = _article("Global trade policy reform tariff economic harm businesses", source_lean="right", url="https://right.com/2")
        events = group_by_event([a1, a2], spin_fn=alternating_spin)
        dual = [e for e in events if e.left_articles and e.right_articles]
        assert dual
        assert dual[0].spin_delta == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# 5. Deduplication edge cases
# ---------------------------------------------------------------------------


class TestDeduplicationEdgeCases:
    def test_exact_url_duplicates_removed(self) -> None:
        from situation_monitor.dedup import deduplicate

        a1 = _article("Breaking news story about markets", url="https://example.com/story")
        a2 = _article("Different title but same URL", url="https://example.com/story")
        result = deduplicate([a1, a2])
        assert len(result) == 1
        assert result[0].title == a1.title

    def test_near_duplicate_titles_deduplicated(self) -> None:
        from situation_monitor.dedup import deduplicate

        a1 = _article("Federal Reserve raises interest rates to combat inflation")
        a2 = _article("Federal reserve raises interest rates to combat high inflation", url="https://example.com/2")
        result = deduplicate([a1, a2])
        assert len(result) == 1

    def test_distinct_articles_all_kept(self) -> None:
        from situation_monitor.dedup import deduplicate

        articles = [
            _article("Federal Reserve raises interest rates", url="https://a.com/1"),
            _article("Hurricane strikes Florida coastline hard", url="https://a.com/2"),
            _article("AI breakthrough announced by researchers", url="https://a.com/3"),
        ]
        result = deduplicate(articles)
        assert len(result) == 3

    def test_empty_list_returns_empty(self) -> None:
        from situation_monitor.dedup import deduplicate

        assert deduplicate([]) == []

    def test_single_article_returned_unchanged(self) -> None:
        from situation_monitor.dedup import deduplicate

        a = _article("Single unique article about nothing in particular")
        result = deduplicate([a])
        assert len(result) == 1
        assert result[0] is a

    def test_first_article_wins_on_url_collision(self) -> None:
        from situation_monitor.dedup import deduplicate

        a1 = _article("FIRST article", url="https://example.com/dup")
        a2 = _article("SECOND article", url="https://example.com/dup")
        result = deduplicate([a1, a2])
        assert result[0].title == "FIRST article"

    def test_short_title_prefix_dedup(self) -> None:
        """Titles shorter than 6 words use all words as the prefix key."""
        from situation_monitor.dedup import deduplicate

        a1 = _article("Fed hikes rates", url="https://a.com/1")
        a2 = _article("Fed hikes rates", url="https://a.com/2")
        result = deduplicate([a1, a2])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# 6. Alerting edge cases
# ---------------------------------------------------------------------------


class TestAlertingEdgeCases:
    def test_alert_fires_at_exact_threshold(self) -> None:
        from situation_monitor.alerting import check_and_emit_alerts

        a = _article("Alert-worthy story")
        a.relevance_score = 0.8
        out = io.StringIO()
        alerted = check_and_emit_alerts([a], threshold=0.8, output_file=out)
        assert a in alerted

    def test_alert_does_not_fire_below_threshold(self) -> None:
        from situation_monitor.alerting import check_and_emit_alerts

        a = _article("Low-relevance story")
        a.relevance_score = 0.79
        out = io.StringIO()
        alerted = check_and_emit_alerts([a], threshold=0.8, output_file=out)
        assert a not in alerted

    def test_no_alerts_for_none_relevance_score(self) -> None:
        from situation_monitor.alerting import check_and_emit_alerts

        a = _article("Score not set story")
        a.relevance_score = None
        out = io.StringIO()
        alerted = check_and_emit_alerts([a], threshold=0.5, output_file=out)
        assert alerted == []

    def test_stringio_accepted_as_output_file(self) -> None:
        from situation_monitor.alerting import check_and_emit_alerts

        a = _article("High-relevance article for testing")
        a.relevance_score = 1.0
        buf = io.StringIO()
        check_and_emit_alerts([a], threshold=0.5, output_file=buf)
        output = buf.getvalue()
        assert "ALERT" in output

    def test_returns_only_alerted_articles(self) -> None:
        from situation_monitor.alerting import check_and_emit_alerts

        high = _article("High relevance news story today", url="https://a.com/1")
        high.relevance_score = 0.9
        low = _article("Low relevance story about nothing important", url="https://a.com/2")
        low.relevance_score = 0.2
        out = io.StringIO()
        alerted = check_and_emit_alerts([high, low], threshold=0.8, output_file=out)
        assert high in alerted
        assert low not in alerted

    def test_alert_output_contains_title_and_score(self) -> None:
        from situation_monitor.alerting import check_and_emit_alerts

        a = _article("Specific title for alert test")
        a.relevance_score = 1.0
        buf = io.StringIO()
        check_and_emit_alerts([a], threshold=0.5, output_file=buf)
        output = buf.getvalue()
        assert "Specific title for alert test" in output
        assert "1.0" in output


# ---------------------------------------------------------------------------
# 7. ReliabilityTracker edge cases
# ---------------------------------------------------------------------------


class TestReliabilityTracker:
    def test_unknown_source_returns_none(self) -> None:
        from situation_monitor.reliability import ReliabilityTracker

        t = ReliabilityTracker()
        assert t.get_tracked_reliability("unknown-source") is None

    def test_high_avg_yields_high_label(self) -> None:
        from situation_monitor.reliability import ReliabilityTracker

        t = ReliabilityTracker()
        t.record_fetch("reuters.com", 10)  # avg=10 → high
        assert t.get_tracked_reliability("reuters.com") == "high"

    def test_medium_avg_yields_medium_label(self) -> None:
        from situation_monitor.reliability import ReliabilityTracker

        t = ReliabilityTracker()
        t.record_fetch("small-blog.com", 3)  # avg=3 → medium
        assert t.get_tracked_reliability("small-blog.com") == "medium"

    def test_low_avg_yields_low_label(self) -> None:
        from situation_monitor.reliability import ReliabilityTracker

        t = ReliabilityTracker()
        t.record_fetch("empty-feed.com", 0)  # avg=0 → low
        assert t.get_tracked_reliability("empty-feed.com") == "low"

    def test_accumulates_across_multiple_fetches(self) -> None:
        from situation_monitor.reliability import ReliabilityTracker

        t = ReliabilityTracker()
        t.record_fetch("feed.com", 0)
        t.record_fetch("feed.com", 10)
        # avg = 5 → high
        assert t.get_tracked_reliability("feed.com") == "high"

    def test_save_and_load_roundtrip(self, tmp_path) -> None:
        from situation_monitor.reliability import ReliabilityTracker

        t = ReliabilityTracker()
        t.record_fetch("bbc.com", 7)
        path = str(tmp_path / "rel.json")
        t.save(path)

        t2 = ReliabilityTracker()
        t2.load(path)
        assert t2.get_tracked_reliability("bbc.com") == "high"

    def test_load_nonexistent_file_is_silent(self, tmp_path) -> None:
        from situation_monitor.reliability import ReliabilityTracker

        t = ReliabilityTracker()
        t.load(str(tmp_path / "does_not_exist.json"))
        assert t.get_tracked_reliability("any") is None


# ---------------------------------------------------------------------------
# 8. SpinEstimator edge cases
# ---------------------------------------------------------------------------


class TestSpinEstimatorEdgeCases:
    def test_fallback_on_unparseable_llm_response(self) -> None:
        from situation_monitor.bias import SpinEstimator

        estimator = SpinEstimator()
        a = _article("Some article about economy and finance trends")

        result = estimator.estimate_spin(a, llm_client=lambda _: "NOT JSON AT ALL")
        assert result.spin_pct == 50.0
        assert "unparseable" in result.receipts.lower()

    def test_fallback_returns_prior_lean_in_receipts(self) -> None:
        from situation_monitor.bias import SpinEstimator

        estimator = SpinEstimator()
        a = _article("BBC World news headline about global summit meeting")
        a.source = "bbc.com"

        result = estimator.estimate_spin(a, llm_client=lambda _: "{bad json}")
        # bbc.com is in CURATED_BIAS with lean='center'
        assert "bbc.com" in result.receipts or "center" in result.receipts

    def test_valid_llm_response_yields_correct_spin_pct(self) -> None:
        from situation_monitor.bias import SpinEstimator

        estimator = SpinEstimator()
        a = _article("Fox News headline about immigration policy crackdown")

        def mock_llm(_: str) -> str:
            return json.dumps({
                "spin_pct": 75.0,
                "lens": "right",
                "rubric": {"loaded_language": 0.8, "omission": 0.2, "sourcing_asymmetry": 0.1, "emotional_framing": 0.5},
                "hype_vs_substance": None,
                "vendor_pr": None,
            })

        result = estimator.estimate_spin(a, llm_client=mock_llm)
        assert result.spin_pct == pytest.approx(75.0)
        assert result.lens == "right"

    def test_ai_domain_populates_hype_vs_substance(self) -> None:
        from situation_monitor.bias import SpinEstimator
        from situation_monitor.models import Domain

        estimator = SpinEstimator()
        a = _article("GPT-5 achieves human-level performance on benchmarks")
        a.domain = Domain.AI

        def mock_llm(_: str) -> str:
            return json.dumps({
                "spin_pct": 80.0,
                "lens": "center",
                "rubric": {},
                "hype_vs_substance": 0.9,
                "vendor_pr": True,
            })

        result = estimator.estimate_spin(a, llm_client=mock_llm)
        assert result.hype_vs_substance == pytest.approx(0.9)
        assert result.vendor_pr is True

    def test_non_ai_domain_leaves_hype_vs_substance_none(self) -> None:
        from situation_monitor.bias import SpinEstimator
        from situation_monitor.models import Domain

        estimator = SpinEstimator()
        a = _article("Markets reaction to Fed interest rate decision today")
        a.domain = Domain.MARKETS

        def mock_llm(_: str) -> str:
            return json.dumps({
                "spin_pct": 50.0,
                "lens": "center",
                "rubric": {},
                "hype_vs_substance": 0.7,
                "vendor_pr": False,
            })

        result = estimator.estimate_spin(a, llm_client=mock_llm)
        assert result.hype_vs_substance is None
        assert result.vendor_pr is None

    def test_spin_pct_above_threshold_fires_rubric_receipts(self) -> None:
        from situation_monitor.bias import SpinEstimator

        estimator = SpinEstimator()
        a = _article("CNN headline with loaded language and emotional framing")

        def mock_llm(_: str) -> str:
            return json.dumps({
                "spin_pct": 70.0,
                "lens": "left",
                "rubric": {"loaded_language": 0.8, "omission": 0.1, "sourcing_asymmetry": 0.05, "emotional_framing": 0.9},
                "hype_vs_substance": None,
                "vendor_pr": None,
            })

        result = estimator.estimate_spin(a, llm_client=mock_llm)
        # Both loaded_language and emotional_framing fired (> 0.3)
        assert "Loaded Language" in result.receipts
        assert "Emotional Framing" in result.receipts

    def test_no_fired_rubric_produces_clean_receipts(self) -> None:
        from situation_monitor.bias import SpinEstimator

        estimator = SpinEstimator()
        a = _article("Reuters factual report about OPEC production decision")

        def mock_llm(_: str) -> str:
            return json.dumps({
                "spin_pct": 15.0,
                "lens": "center",
                "rubric": {"loaded_language": 0.1, "omission": 0.1, "sourcing_asymmetry": 0.05, "emotional_framing": 0.05},
                "hype_vs_substance": None,
                "vendor_pr": None,
            })

        result = estimator.estimate_spin(a, llm_client=mock_llm)
        assert "No strong spin signals" in result.receipts


# ---------------------------------------------------------------------------
# 9. Digest assembly edge cases
# ---------------------------------------------------------------------------


class TestDigestAssembly:
    def test_empty_events_emits_no_events_line(self) -> None:
        from situation_monitor.digest import daily_digest

        text = daily_digest(events=[], movers=[])
        assert "_No events found._" in text

    def test_non_empty_events_emits_top_stories(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.dual_lens import DualLensEvent

        event = DualLensEvent(event_title="Central bank raises rates by 50 basis points", spin_delta=10.0)
        text = daily_digest(events=[event], movers=[])
        assert "Top Stories" in text
        assert "Central bank raises rates" in text

    def test_spin_delta_annotation_appears_when_above_5(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.dual_lens import DualLensEvent

        event = DualLensEvent(event_title="Major event with high spin delta", spin_delta=15.0)
        text = daily_digest(events=[event], movers=[])
        assert "↕15%" in text

    def test_spin_delta_annotation_absent_when_at_or_below_5(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.dual_lens import DualLensEvent

        event = DualLensEvent(event_title="Low spin delta event title here", spin_delta=5.0)
        text = daily_digest(events=[event], movers=[])
        assert "↕" not in text

    def test_market_movers_section_present_when_movers_given(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.dual_lens import DualLensEvent
        from situation_monitor.practical import PracticalMover

        mover = PracticalMover(
            asset="EUR/USD",
            change_pct=1.5,
            direction="up",
            who_it_affects="traders",
            what_to_watch="ECB",
            source_url="https://ecb.europa.eu",
        )
        text = daily_digest(events=[], movers=[mover])
        assert "Market Movers" in text
        assert "EUR/USD" in text
        assert "▲" in text

    def test_market_mover_down_uses_down_arrow(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.practical import PracticalMover

        mover = PracticalMover(
            asset="WTI Crude Oil",
            change_pct=-2.3,
            direction="down",
            who_it_affects="energy sector",
            what_to_watch="OPEC",
            source_url="https://example.com/oil",
        )
        text = daily_digest(events=[], movers=[mover])
        assert "▼" in text

    def test_as_of_datetime_appears_in_output(self) -> None:
        from situation_monitor.digest import daily_digest

        ts = datetime(2025, 6, 13, 7, 0, 0)
        text = daily_digest(events=[], movers=[], as_of=ts)
        assert "2025-06-13" in text

    def test_top_n_limits_events(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.dual_lens import DualLensEvent

        events = [DualLensEvent(event_title=f"Event number {i} unique title", spin_delta=0.0) for i in range(20)]
        text = daily_digest(events=events, movers=[], top_n=3)
        # Only 3 should be included
        included = [e for e in events[:3] if e.event_title in text]
        excluded = [e for e in events[3:] if e.event_title in text]
        assert len(included) == 3
        assert not excluded


# ---------------------------------------------------------------------------
# 10. Article domain model invariants
# ---------------------------------------------------------------------------


class TestArticleDomainModel:
    def test_article_requires_url(self) -> None:
        from situation_monitor.models import Article

        with pytest.raises(ValueError, match="url"):
            Article(url="", title="Title", source="source")

    def test_article_requires_title(self) -> None:
        from situation_monitor.models import Article

        with pytest.raises(ValueError, match="title"):
            Article(url="https://example.com", title="", source="source")

    def test_article_requires_source(self) -> None:
        from situation_monitor.models import Article

        with pytest.raises(ValueError, match="source"):
            Article(url="https://example.com", title="Title", source="")

    def test_default_propaganda_flags_is_empty_list(self) -> None:
        from situation_monitor.models import Article

        a = Article(url="https://x.com/1", title="T", source="S")
        assert a.propaganda_flags == []

    def test_default_reliability_unknown(self) -> None:
        from situation_monitor.models import Article, SourceReliability

        a = Article(url="https://x.com/1", title="T", source="S")
        assert a.reliability is SourceReliability.UNKNOWN

    def test_digest_entry_requires_list_articles(self) -> None:
        from situation_monitor.models import DigestEntry

        with pytest.raises(TypeError, match="list"):
            DigestEntry(articles="not a list", summary="summary")  # type: ignore[arg-type]

    def test_spin_result_fields_accessible(self) -> None:
        from situation_monitor.models import SpinResult

        s = SpinResult(spin_pct=42.0, lens="left", rubric={"loaded_language": 0.7}, receipts="ok")
        assert s.spin_pct == 42.0
        assert s.lens == "left"
        assert s.rubric["loaded_language"] == 0.7
        assert s.receipts == "ok"
        assert s.hype_vs_substance is None
        assert s.vendor_pr is None


# ---------------------------------------------------------------------------
# 11. Config loading
# ---------------------------------------------------------------------------


class TestConfigLoading:
    def test_from_defaults_has_sensible_poll_interval(self) -> None:
        from situation_monitor.config import Config

        c = Config.from_defaults()
        assert c.poll_interval_seconds > 0

    def test_from_defaults_llm_backend_is_claude(self) -> None:
        from situation_monitor.config import Config

        c = Config.from_defaults()
        assert c.llm_backend == "claude"

    def test_from_file_parses_source_defs(self) -> None:
        from situation_monitor.config import Config

        path = FIXTURES / "acceptance_source_defs.json"
        assert path.exists(), "acceptance_source_defs.json fixture must exist"
        c = Config.from_file(path)
        assert len(c.source_defs) >= 1, "Config from file must have at least one source_def"

    def test_source_def_domain_mapping(self) -> None:
        from situation_monitor.config import Config
        from situation_monitor.models import Domain

        path = FIXTURES / "acceptance_source_defs.json"
        c = Config.from_file(path)
        domains = {sd.domain for sd in c.source_defs}
        assert Domain.WORLD in domains, "Config must include a WORLD source_def"

    def test_from_env_applies_sm_llm_backend(self, monkeypatch) -> None:
        from situation_monitor.config import Config

        monkeypatch.setenv("SM_LLM_BACKEND", "stub")
        c = Config.from_env()
        assert c.llm_backend == "stub"

    def test_from_env_applies_sm_max_articles(self, monkeypatch) -> None:
        from situation_monitor.config import Config

        monkeypatch.setenv("SM_MAX_ARTICLES", "5")
        c = Config.from_env()
        assert c.max_articles_per_digest == 5


# ---------------------------------------------------------------------------
# 12. Bias lookups
# ---------------------------------------------------------------------------


class TestBiasLookups:
    def test_bbc_has_center_lean(self) -> None:
        from situation_monitor.bias import get_source_lean

        assert get_source_lean("bbc.com") == "center"

    def test_foxnews_has_right_lean(self) -> None:
        from situation_monitor.bias import get_source_lean

        assert get_source_lean("foxnews.com") == "right"

    def test_cnn_has_left_lean(self) -> None:
        from situation_monitor.bias import get_source_lean

        assert get_source_lean("cnn.com") == "left"

    def test_unknown_source_returns_none(self) -> None:
        from situation_monitor.bias import get_source_lean

        assert get_source_lean("completely-unknown-domain-xyz.io") is None

    def test_bbc_has_high_reliability(self) -> None:
        from situation_monitor.bias import get_source_reliability

        assert get_source_reliability("bbc.com") == "high"

    def test_breitbart_has_low_reliability(self) -> None:
        from situation_monitor.bias import get_source_reliability

        assert get_source_reliability("breitbart.com") == "low"

    def test_prior_lean_falls_back_to_center(self) -> None:
        from situation_monitor.bias import _prior_lean

        assert _prior_lean("never-heard-of-this.com") == "center"


# ---------------------------------------------------------------------------
# 13. RSS ingestion from fixture
# ---------------------------------------------------------------------------


class TestRSSIngestionFromFixture:
    def test_rss_sample_fixture_produces_articles(self) -> None:
        from situation_monitor.ingestion.rss import RSSFetcher

        fetcher = RSSFetcher(client=_LocalFileClient())
        articles = fetcher.fetch(str(FIXTURES / "rss_sample.xml"))
        assert len(articles) >= 1

    def test_rss_articles_have_non_empty_title_and_url(self) -> None:
        from situation_monitor.ingestion.rss import RSSFetcher

        fetcher = RSSFetcher(client=_LocalFileClient())
        articles = fetcher.fetch(str(FIXTURES / "rss_sample.xml"))
        for a in articles:
            assert a.title, "RSS article must have a non-empty title"
            assert a.url, "RSS article must have a non-empty URL"

    def test_source_def_lens_propagated_to_articles(self) -> None:
        from situation_monitor.config import SourceDef
        from situation_monitor.ingestion.rss import RSSFetcher
        from situation_monitor.models import Domain

        sd = SourceDef(str(FIXTURES / "rss_left.xml"), "TestLeft", Domain.WORLD, "left")
        fetcher = RSSFetcher(client=_LocalFileClient())
        articles = fetcher.fetch(sd.url, source_def=sd)
        assert all(a.source_lean == "left" for a in articles), (
            "source_def.lens must be propagated to article.source_lean"
        )

    def test_source_def_domain_propagated_to_articles(self) -> None:
        from situation_monitor.config import SourceDef
        from situation_monitor.ingestion.rss import RSSFetcher
        from situation_monitor.models import Domain

        sd = SourceDef(str(FIXTURES / "rss_sample.xml"), "TestWorld", Domain.MARKETS, "centre")
        fetcher = RSSFetcher(client=_LocalFileClient())
        articles = fetcher.fetch(sd.url, source_def=sd)
        assert all(a.domain is Domain.MARKETS for a in articles), (
            "source_def.domain must be propagated to article.domain"
        )

    def test_missing_item_title_or_link_skipped(self) -> None:
        """RSS items without a title or link must be silently skipped."""
        from situation_monitor.ingestion.rss import RSSFetcher

        bad_rss = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <rss version="2.0">
              <channel>
                <title>Test</title>
                <item><title>Good article</title><link>https://example.com/good</link></item>
                <item><title/><link>https://example.com/notitle</link></item>
                <item><title>No link article</title></item>
              </channel>
            </rss>
        """).encode()

        class _InMemClient:
            def get(self, url: str) -> bytes:
                return bad_rss

        fetcher = RSSFetcher(client=_InMemClient())
        articles = fetcher.fetch("https://fake.url")
        assert len(articles) == 1
        assert articles[0].title == "Good article"

    def test_rss_channel_without_channel_element_returns_empty(self) -> None:
        from situation_monitor.ingestion.rss import RSSFetcher

        no_channel = b'<?xml version="1.0"?><rss version="2.0"></rss>'

        class _InMemClient:
            def get(self, url: str) -> bytes:
                return no_channel

        fetcher = RSSFetcher(client=_InMemClient())
        result = fetcher.fetch("https://fake.url")
        assert result == []


# ---------------------------------------------------------------------------
# 14. LLM stub client
# ---------------------------------------------------------------------------


class TestLLMStubClient:
    def test_stub_backend_returns_json_score(self) -> None:
        from situation_monitor.config import Config
        from situation_monitor.llm import get_llm_client

        config = Config.from_defaults()
        config.llm_backend = "stub"
        client = get_llm_client(config)
        response = client("any prompt here")
        data = json.loads(response)
        assert "score" in data
        assert 0.0 <= float(data["score"]) <= 1.0

    def test_override_callback_used_when_provided(self) -> None:
        from situation_monitor.config import Config
        from situation_monitor.llm import get_llm_client

        calls: list[str] = []

        def my_llm(prompt: str) -> str:
            calls.append(prompt)
            return '{"score": 0.99}'

        config = Config.from_defaults()
        client = get_llm_client(config, _override=my_llm)
        result = client("test prompt")
        assert calls == ["test prompt"]
        assert result == '{"score": 0.99}'


# ---------------------------------------------------------------------------
# 15. PolymarketMatcher edge cases
# ---------------------------------------------------------------------------


class TestPolymarketMatcherEdgeCases:
    def test_keyword_match_returns_odds(self) -> None:
        from situation_monitor.polymarket import PolymarketMatcher

        matcher = PolymarketMatcher()
        a = _article("Bitcoin price surges past 100000 milestone")
        markets = [{"keywords": ["bitcoin", "BTC"], "odds": 0.75}]
        result = matcher.match(a, markets)
        assert result == pytest.approx(0.75)

    def test_no_keyword_match_returns_none(self) -> None:
        from situation_monitor.polymarket import PolymarketMatcher

        matcher = PolymarketMatcher()
        a = _article("Federal Reserve interest rate decision this week")
        markets = [{"keywords": ["bitcoin"], "odds": 0.6}]
        result = matcher.match(a, markets)
        assert result is None

    def test_empty_markets_returns_none(self) -> None:
        from situation_monitor.polymarket import PolymarketMatcher

        matcher = PolymarketMatcher()
        a = _article("Any article at all")
        assert matcher.match(a, []) is None

    def test_case_insensitive_keyword_matching(self) -> None:
        from situation_monitor.polymarket import PolymarketMatcher

        matcher = PolymarketMatcher()
        a = _article("BITCOIN hits new all-time high record today")
        markets = [{"keywords": ["bitcoin"], "odds": 0.55}]
        result = matcher.match(a, markets)
        assert result == pytest.approx(0.55)


# ---------------------------------------------------------------------------
# 16. Dashboard API endpoints
# ---------------------------------------------------------------------------


class TestDashboardAPIEndpoints:
    @pytest.fixture
    def app_with_data(self, belfast_articles, belfast_events):
        from situation_monitor.dashboard import make_app

        return make_app(lambda: belfast_articles, lambda: belfast_events)

    def test_root_returns_200(self, app_with_data) -> None:
        with app_with_data.test_client() as c:
            resp = c.get("/")
        assert resp.status_code == 200

    def test_root_html_contains_situation_monitor(self, app_with_data) -> None:
        with app_with_data.test_client() as c:
            html = c.get("/").data.decode()
        assert "Situation Monitor" in html

    def test_root_html_contains_dual_lens_section(self, app_with_data) -> None:
        with app_with_data.test_client() as c:
            html = c.get("/").data.decode()
        assert "Dual-Lens Events" in html

    def test_api_events_returns_list(self, app_with_data) -> None:
        with app_with_data.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_api_events_schema_has_required_keys(self, app_with_data) -> None:
        with app_with_data.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        for entry in data:
            assert "event_title" in entry
            assert "spin_delta" in entry
            assert "left_articles" in entry
            assert "right_articles" in entry
            assert "center_articles" in entry

    def test_api_events_left_articles_non_empty_for_climate(self, app_with_data) -> None:
        with app_with_data.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        events_with_left = [e for e in data if e["left_articles"]]
        assert events_with_left, "API must expose at least one event with left articles"

    def test_api_events_right_articles_non_empty_for_climate(self, app_with_data) -> None:
        with app_with_data.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        events_with_right = [e for e in data if e["right_articles"]]
        assert events_with_right, "API must expose at least one event with right articles"

    def test_api_practical_returns_list_when_no_data(self) -> None:
        from situation_monitor.dashboard import make_app

        app = make_app(lambda: [], lambda: [], lambda: [])
        with app.test_client() as c:
            data = json.loads(c.get("/api/practical").data)
        assert data == []

    def test_rationale_endpoint_returns_404_for_out_of_range(self, app_with_data) -> None:
        with app_with_data.test_client() as c:
            resp = c.get("/api/events/9999/rationale")
        assert resp.status_code == 404

    def test_rationale_endpoint_returns_404_for_non_integer(self, app_with_data) -> None:
        with app_with_data.test_client() as c:
            resp = c.get("/api/events/notanumber/rationale")
        assert resp.status_code == 404

    def test_rationale_endpoint_returns_event_title_for_valid_index(self, app_with_data, belfast_events) -> None:
        with app_with_data.test_client() as c:
            data = json.loads(c.get("/api/events/0/rationale").data)
        assert "event_title" in data
        assert data["event_title"] == belfast_events[0].event_title

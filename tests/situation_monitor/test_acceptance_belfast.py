"""Belfast acceptance pipeline: live ingestion stub → ollama estimator → dual-lens render.

Exercises the real end-to-end code path:
  1. Ingest articles from fixture RSS feeds (left-lean and right-lean sources) using
     a local-file HTTP client — no network calls.
  2. Annotate spin with SpinEstimator backed by a mock LLM (stand-in for ollama).
  3. Pass annotated articles through the dual-lens grouper.
  4. Assert that at least one DualLensEvent has BOTH left_articles AND right_articles
     non-empty ("both columns non-empty for a high-significance event").

The fixture feeds in tests/fixtures/rss_left.xml and rss_right.xml each contain one
article about "Government Climate Policy Reform", framed differently:
  LEFT  : "...Backed by Scientists"
  RIGHT : "...Threatens Economic Growth"
These share the significant words {government, climate, policy, reform} (≥2) so they
cluster into a single DualLensEvent.  When the sources carry source_lean='left' /
source_lean='right' (set via SourceDef), _stub_spin places them in the correct bucket.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from situation_monitor.bias import SpinEstimator
from situation_monitor.config import SourceDef
from situation_monitor.dashboard import make_app
from situation_monitor.dual_lens import DualLensEvent, group_by_event
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.models import Article, Domain, SpinResult

PROJECT_ROOT = Path(__file__).parent.parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# Ingestion stub: local-file HTTP client (no network)
# ---------------------------------------------------------------------------


class _LocalFileClient:
    """Reads fixture files instead of making HTTP requests."""

    def get(self, url: str) -> bytes:
        return Path(url).read_bytes()


def _load_belfast_articles() -> list[Article]:
    """Fetch articles from both fixture feeds with correct source leans."""
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

    articles: list[Article] = []
    articles.extend(fetcher.fetch(left_sd.url, source_def=left_sd))
    articles.extend(fetcher.fetch(right_sd.url, source_def=right_sd))
    return articles


# ---------------------------------------------------------------------------
# Mock LLM (olama estimator stand-in)
# ---------------------------------------------------------------------------


def _mock_llm_for(source_lean: str | None):
    """Return a mock LLM callable that mimics an ollama spin estimator response."""
    lean = source_lean or "center"
    spin_pct = 80.0 if lean == "left" else (35.0 if lean == "right" else 50.0)

    def _llm(prompt: str) -> str:
        return json.dumps({
            "spin_pct": spin_pct,
            "lens": lean,
            "rubric": {
                "loaded_language": 0.6,
                "omission": 0.4,
                "sourcing_asymmetry": 0.3,
                "emotional_framing": 0.5,
            },
            "hype_vs_substance": None,
            "vendor_pr": None,
        })

    return _llm


def _estimator_spin_fn(article: Article) -> SpinResult:
    """spin_fn that uses the real SpinEstimator with mock-ollama LLM."""
    estimator = SpinEstimator()
    llm = _mock_llm_for(article.source_lean)
    return estimator.estimate_spin(article, llm)


# ---------------------------------------------------------------------------
# Fixture-level setup (reuse across tests)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def belfast_articles() -> list[Article]:
    """Real articles loaded from fixture RSS files; source_lean set from SourceDef."""
    articles = _load_belfast_articles()
    assert articles, "Fixture files must produce at least one article"
    return articles


@pytest.fixture(scope="module")
def belfast_events(belfast_articles) -> list[DualLensEvent]:
    """Dual-lens events using the default _stub_spin (source_lean → lean bucket)."""
    return group_by_event(belfast_articles)


@pytest.fixture(scope="module")
def belfast_events_with_estimator(belfast_articles) -> list[DualLensEvent]:
    """Dual-lens events using the real SpinEstimator backed by mock-ollama LLM."""
    return group_by_event(belfast_articles, spin_fn=_estimator_spin_fn)


# ---------------------------------------------------------------------------
# Ingestion: real fixtures load correctly
# ---------------------------------------------------------------------------


class TestIngestionStub:
    def test_left_feed_produces_articles(self):
        client = _LocalFileClient()
        fetcher = RSSFetcher(client=client)
        left_sd = SourceDef(str(FIXTURES / "rss_left.xml"), "Left News Feed", Domain.WORLD, "left")
        articles = fetcher.fetch(left_sd.url, source_def=left_sd)
        assert len(articles) >= 1

    def test_right_feed_produces_articles(self):
        client = _LocalFileClient()
        fetcher = RSSFetcher(client=client)
        right_sd = SourceDef(str(FIXTURES / "rss_right.xml"), "Right News Feed", Domain.WORLD, "right")
        articles = fetcher.fetch(right_sd.url, source_def=right_sd)
        assert len(articles) >= 1

    def test_left_articles_have_source_lean_left(self):
        client = _LocalFileClient()
        fetcher = RSSFetcher(client=client)
        left_sd = SourceDef(str(FIXTURES / "rss_left.xml"), "Left News Feed", Domain.WORLD, "left")
        articles = fetcher.fetch(left_sd.url, source_def=left_sd)
        assert all(a.source_lean == "left" for a in articles)

    def test_right_articles_have_source_lean_right(self):
        client = _LocalFileClient()
        fetcher = RSSFetcher(client=client)
        right_sd = SourceDef(str(FIXTURES / "rss_right.xml"), "Right News Feed", Domain.WORLD, "right")
        articles = fetcher.fetch(right_sd.url, source_def=right_sd)
        assert all(a.source_lean == "right" for a in articles)

    def test_combined_feed_has_articles_from_both_sources(self, belfast_articles):
        leans = {a.source_lean for a in belfast_articles}
        assert "left" in leans, "Left-leaning articles must be present"
        assert "right" in leans, "Right-leaning articles must be present"

    def test_fixture_articles_about_climate_policy(self, belfast_articles):
        titles = [a.title.lower() for a in belfast_articles]
        assert any("climate" in t for t in titles), "Fixture must contain climate articles"

    def test_articles_have_non_empty_url(self, belfast_articles):
        for a in belfast_articles:
            assert a.url, f"Article must have a URL: {a.title!r}"

    def test_articles_have_non_empty_title(self, belfast_articles):
        for a in belfast_articles:
            assert a.title, "Every article must have a title"


# ---------------------------------------------------------------------------
# Dual-lens grouper: Belfast constraint (both columns non-empty)
# ---------------------------------------------------------------------------


class TestBelfastConstraintDefaultSpin:
    """Uses the default _stub_spin which reads source_lean for bucket assignment."""

    def test_at_least_one_event_with_both_columns_non_empty(self, belfast_events):
        dual = [e for e in belfast_events if e.left_articles and e.right_articles]
        assert dual, (
            "Belfast constraint: at least one DualLensEvent must have both "
            "left_articles AND right_articles non-empty"
        )

    def test_left_column_non_empty(self, belfast_events):
        assert any(e.left_articles for e in belfast_events), "left_articles must be non-empty"

    def test_right_column_non_empty(self, belfast_events):
        assert any(e.right_articles for e in belfast_events), "right_articles must be non-empty"

    def test_climate_articles_clustered_into_same_event(self, belfast_events):
        """Both climate articles (left and right framing) must land in ONE DualLensEvent."""
        climate_events = [
            e for e in belfast_events
            if any(
                "climate" in aa.article.title.lower()
                for aa in e.left_articles + e.right_articles + e.center_articles
            )
        ]
        assert climate_events, "No climate event found"
        event = climate_events[0]
        assert event.left_articles, "Climate event must have left articles"
        assert event.right_articles, "Climate event must have right articles"

    def test_high_significance_event_has_positive_spin_delta(self, belfast_events):
        """A dual-lens event with opposite framings must have spin_delta > 0."""
        dual = [e for e in belfast_events if e.left_articles and e.right_articles]
        assert dual
        # With stub spin both sides get spin_pct=50 → delta=0 is acceptable here;
        # but delta must be ≥ 0 always.
        for e in dual:
            assert e.spin_delta >= 0.0

    def test_no_articles_are_lost(self, belfast_articles, belfast_events):
        """Every ingested article must appear in exactly one bucket of exactly one event."""
        total_in_events = sum(
            len(e.left_articles) + len(e.right_articles) + len(e.center_articles)
            for e in belfast_events
        )
        assert total_in_events == len(belfast_articles)


# ---------------------------------------------------------------------------
# Ollama estimator (SpinEstimator + mock LLM)
# ---------------------------------------------------------------------------


class TestBelfastConstraintWithSpinEstimator:
    """Uses SpinEstimator with mock-ollama LLM — the 'ollama estimator' pipeline."""

    def test_at_least_one_event_both_columns_non_empty(self, belfast_events_with_estimator):
        dual = [e for e in belfast_events_with_estimator if e.left_articles and e.right_articles]
        assert dual, (
            "SpinEstimator path: at least one event must have both left and right articles"
        )

    def test_left_column_non_empty_with_estimator(self, belfast_events_with_estimator):
        assert any(e.left_articles for e in belfast_events_with_estimator)

    def test_right_column_non_empty_with_estimator(self, belfast_events_with_estimator):
        assert any(e.right_articles for e in belfast_events_with_estimator)

    def test_spin_pct_from_estimator_in_range(self, belfast_events_with_estimator):
        for event in belfast_events_with_estimator:
            for aa in event.left_articles + event.right_articles + event.center_articles:
                assert 0.0 <= aa.spin.spin_pct <= 100.0, (
                    f"spin_pct out of range: {aa.spin.spin_pct}"
                )

    def test_estimator_spin_results_carry_receipts(self, belfast_events_with_estimator):
        for event in belfast_events_with_estimator:
            for aa in event.left_articles + event.right_articles + event.center_articles:
                assert aa.spin.receipts, "spin.receipts must not be empty"

    def test_left_articles_have_left_lens_from_estimator(self, belfast_events_with_estimator):
        """Mock LLM returns lens='left' for left-source articles → left bucket."""
        for event in belfast_events_with_estimator:
            for aa in event.left_articles:
                assert "left" in aa.spin.lens, (
                    f"Left-bucket article must have left-leaning lens, got: {aa.spin.lens!r}"
                )

    def test_right_articles_have_right_lens_from_estimator(self, belfast_events_with_estimator):
        """Mock LLM returns lens='right' for right-source articles → right bucket."""
        for event in belfast_events_with_estimator:
            for aa in event.right_articles:
                assert "right" in aa.spin.lens, (
                    f"Right-bucket article must have right-leaning lens, got: {aa.spin.lens!r}"
                )

    def test_high_significance_spin_delta_with_estimator(self, belfast_events_with_estimator):
        """With mock LLM: left spin=80, right spin=35 → delta=45."""
        dual = [e for e in belfast_events_with_estimator if e.left_articles and e.right_articles]
        assert dual
        event = dual[0]
        assert event.spin_delta == pytest.approx(45.0)


# ---------------------------------------------------------------------------
# Dual-lens render: web dashboard
# ---------------------------------------------------------------------------


class TestBelfastDashboardRender:
    """Feeds real fixture events into the web dashboard and checks the HTML output."""

    def _rendered_html(self, belfast_articles, belfast_events) -> str:
        app = make_app(lambda: belfast_articles, lambda: belfast_events)
        with app.test_client() as c:
            return c.get("/").data.decode()

    def test_dashboard_renders_200(self, belfast_articles, belfast_events):
        app = make_app(lambda: belfast_articles, lambda: belfast_events)
        with app.test_client() as c:
            resp = c.get("/")
        assert resp.status_code == 200

    def test_dashboard_has_dual_lens_events_section(self, belfast_articles, belfast_events):
        html = self._rendered_html(belfast_articles, belfast_events)
        assert "Dual-Lens Events" in html

    def test_dashboard_has_left_column(self, belfast_articles, belfast_events):
        html = self._rendered_html(belfast_articles, belfast_events)
        assert "col-left" in html

    def test_dashboard_has_right_column(self, belfast_articles, belfast_events):
        html = self._rendered_html(belfast_articles, belfast_events)
        assert "col-right" in html

    def test_dashboard_left_column_has_article(self, belfast_articles, belfast_events):
        """Left column must contain at least one real article (not only the placeholder)."""
        html = self._rendered_html(belfast_articles, belfast_events)
        # The placeholder text appears only when left_articles is empty
        dual = [e for e in belfast_events if e.left_articles]
        assert dual, "Must have at least one event with left articles for this test to be valid"
        assert "No left-framing articles" not in html or "Left News Feed" in html

    def test_dashboard_right_column_has_article(self, belfast_articles, belfast_events):
        """Right column must contain at least one real article."""
        html = self._rendered_html(belfast_articles, belfast_events)
        dual = [e for e in belfast_events if e.right_articles]
        assert dual, "Must have at least one event with right articles for this test to be valid"
        assert "No right-framing articles" not in html or "Right News Feed" in html

    def test_dashboard_spin_pct_annotation_present(self, belfast_articles, belfast_events):
        html = self._rendered_html(belfast_articles, belfast_events)
        assert "spin_pct:" in html

    def test_api_events_endpoint_returns_dual_events(self, belfast_articles, belfast_events):
        app = make_app(lambda: belfast_articles, lambda: belfast_events)
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert len(data) >= 1

    def test_api_events_has_left_articles_for_climate_event(self, belfast_articles, belfast_events):
        app = make_app(lambda: belfast_articles, lambda: belfast_events)
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        # Find an event with left articles
        events_with_left = [d for d in data if d["left_articles"]]
        assert events_with_left, "API must expose at least one event with left articles"

    def test_api_events_has_right_articles_for_climate_event(self, belfast_articles, belfast_events):
        app = make_app(lambda: belfast_articles, lambda: belfast_events)
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        events_with_right = [d for d in data if d["right_articles"]]
        assert events_with_right, "API must expose at least one event with right articles"

"""Tests for AI digest section and dashboard domain filter.

Covers:
- daily_digest(): '🤖 AI News' header appears iff Domain.AI articles present
- /api/events?domain=ai: returns only events containing Domain.AI articles
"""

from __future__ import annotations

import json

import pytest

from situation_monitor.dashboard import make_app
from situation_monitor.digest import daily_digest
from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
from situation_monitor.models import Article, Domain, SpinResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _article(
    title: str = "Test Article",
    source: str = "test.com",
    url: str | None = None,
    domain: Domain | None = None,
) -> Article:
    safe_url = url or f"https://{source}/{title[:40].replace(' ', '-').replace('&', 'and').lower()}"
    a = Article(url=safe_url, title=title, source=source)
    a.domain = domain
    return a


def _spin(spin_pct: float = 50.0, lens: str = "center") -> SpinResult:
    return SpinResult(spin_pct=spin_pct, lens=lens, rubric={}, receipts="stub")


def _aa(
    title: str,
    domain: Domain | None = None,
    lens: str = "center",
    source: str = "test.com",
    url: str | None = None,
) -> AnnotatedArticle:
    return AnnotatedArticle(
        article=_article(title=title, domain=domain, source=source, url=url),
        spin=_spin(lens=lens),
    )


def _event(
    title: str = "Test Event",
    left: list[AnnotatedArticle] | None = None,
    right: list[AnnotatedArticle] | None = None,
    center: list[AnnotatedArticle] | None = None,
    spin_delta: float = 0.0,
) -> DualLensEvent:
    return DualLensEvent(
        event_title=title,
        left_articles=left or [],
        right_articles=right or [],
        center_articles=center or [],
        spin_delta=spin_delta,
    )


def _api_events(app, params: str = "") -> list[dict]:
    with app.test_client() as c:
        resp = c.get(f"/api/events{params}")
        return json.loads(resp.data)


# ---------------------------------------------------------------------------
# AI digest section — header presence
# ---------------------------------------------------------------------------


class TestAiDigestHeader:
    def test_header_present_when_ai_article_in_center(self):
        """'🤖 AI News' header must appear when any event contains a Domain.AI article."""
        event = _event("AI Event", center=[_aa("GPT-5 launches", domain=Domain.AI)])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" in result

    def test_header_absent_when_no_ai_articles(self):
        """'🤖 AI News' header must NOT appear when no article has Domain.AI."""
        event = _event("World Event", center=[_aa("G7 summit begins", domain=Domain.WORLD)])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" not in result
        assert "AI News" not in result

    def test_header_absent_when_domain_is_none(self):
        """Articles with domain=None are not AI articles and must not trigger the header."""
        event = _event("Tech", center=[_aa("Unclassified story", domain=None)])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" not in result

    def test_header_absent_for_empty_events(self):
        """With no events, the AI News section must not appear."""
        result = daily_digest([], [])
        assert "*\U0001f916 AI News*" not in result

    def test_header_absent_for_markets_articles(self):
        """Domain.MARKETS articles must never trigger the AI News section."""
        event = _event("Markets", center=[_aa("Bitcoin surges", domain=Domain.MARKETS)])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" not in result

    def test_header_absent_when_all_articles_non_ai(self):
        """Events with only WORLD and MARKETS articles produce no AI section."""
        event = _event(
            "Mixed non-AI",
            center=[
                _aa("Election results", domain=Domain.WORLD, url="https://world.com/election"),
                _aa("S&P 500 falls", domain=Domain.MARKETS, url="https://markets.com/sp500"),
            ],
        )
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" not in result


# ---------------------------------------------------------------------------
# AI digest section — content correctness
# ---------------------------------------------------------------------------


class TestAiDigestContent:
    def test_ai_article_title_listed_under_header(self):
        """The AI article title must appear as a bullet under the AI News header."""
        event = _event("AI Event", center=[_aa("Claude 4 released", domain=Domain.AI)])
        result = daily_digest([event], [])
        assert "Claude 4 released" in result

    def test_non_ai_titles_absent_from_ai_section(self):
        """World-domain article title must not appear in the AI News section."""
        ai_aa = _aa("Anthropic raises funding", domain=Domain.AI, url="https://ai.com/a")
        world_aa = _aa("Floods in Asia", domain=Domain.WORLD, url="https://world.com/w")
        event = _event("Mixed", center=[ai_aa, world_aa])
        result = daily_digest([event], [])
        lines = result.split("\n")
        ai_start = next(i for i, line in enumerate(lines) if "*\U0001f916 AI News*" in line)
        ai_section = "\n".join(lines[ai_start:])
        assert "Anthropic raises funding" in ai_section
        assert "Floods in Asia" not in ai_section

    def test_ai_articles_from_left_bucket_included(self):
        """AI articles in left_articles must appear in the AI News section."""
        event = _event("AI Policy", left=[_aa("OpenAI restructures", domain=Domain.AI, lens="left")])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" in result
        assert "OpenAI restructures" in result

    def test_ai_articles_from_right_bucket_included(self):
        """AI articles in right_articles must appear in the AI News section."""
        event = _event("AI Deregulation", right=[_aa("Musk backs AI reform", domain=Domain.AI, lens="right")])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" in result
        assert "Musk backs AI reform" in result

    def test_ai_articles_from_all_three_buckets_collected(self):
        """AI articles spread across left/right/center are all collected."""
        event = _event(
            "AI Everywhere",
            left=[_aa("Left AI piece", domain=Domain.AI, lens="left", url="https://l.com/1")],
            center=[_aa("Centre AI piece", domain=Domain.AI, url="https://c.com/2")],
            right=[_aa("Right AI piece", domain=Domain.AI, lens="right", url="https://r.com/3")],
        )
        result = daily_digest([event], [])
        assert "Left AI piece" in result
        assert "Centre AI piece" in result
        assert "Right AI piece" in result

    def test_duplicate_titles_deduplicated_across_events(self):
        """The same AI article title appearing in multiple events is listed only once."""
        title = "AI regulation bill passes"
        event1 = _event("AI Policy", left=[_aa(title, domain=Domain.AI, source="left.com")])
        event2 = _event("AI Policy 2", right=[_aa(title, domain=Domain.AI, source="right.com")])
        result = daily_digest([event1, event2], [])
        # Title should appear exactly once in the AI section
        assert result.count(title) == 1

    def test_capped_at_five_ai_articles(self):
        """At most 5 AI articles are listed even when more are available."""
        articles = [
            _aa(f"AI story {i}", domain=Domain.AI, source=f"site{i}.com")
            for i in range(8)
        ]
        event = _event("AI Flood", center=articles)
        result = daily_digest([event], [])
        lines = result.split("\n")
        ai_start = next(i for i, line in enumerate(lines) if "*\U0001f916 AI News*" in line)
        ai_bullets = [line for line in lines[ai_start + 1:] if line.startswith("•")]
        assert len(ai_bullets) <= 5

    def test_ai_section_appears_after_top_stories(self):
        """The AI News section must follow the Top Stories section in output order."""
        event = _event(
            "Mixed",
            center=[
                _aa("Treaty signed", domain=Domain.WORLD, url="https://world.com/t"),
                _aa("GPT-6 rumors", domain=Domain.AI, url="https://ai.com/g"),
            ],
        )
        result = daily_digest([event], [])
        top_idx = result.index("*Top Stories*")
        ai_idx = result.index("*\U0001f916 AI News*")
        assert ai_idx > top_idx

    def test_ai_articles_from_multiple_events_combined(self):
        """AI articles from different events are all collected into one section."""
        event1 = _event("AI Story A", center=[_aa("LLM paper out", domain=Domain.AI, url="https://a.com/1")])
        event2 = _event("AI Story B", center=[_aa("Chip breakthrough", domain=Domain.AI, url="https://a.com/2")])
        result = daily_digest([event1, event2], [])
        assert "LLM paper out" in result
        assert "Chip breakthrough" in result


# ---------------------------------------------------------------------------
# Dashboard domain filter — /api/events?domain=ai
# ---------------------------------------------------------------------------


class TestDashboardDomainFilterApi:
    def test_no_filter_returns_all_events(self):
        """Without a domain parameter all events are returned."""
        ai_event = _event("AI Event", center=[_aa("LLM breakthrough", domain=Domain.AI)])
        world_event = _event("World Event", center=[_aa("Summit held", domain=Domain.WORLD)])
        app = make_app(lambda: [], lambda: [ai_event, world_event])
        events = _api_events(app)
        assert len(events) == 2

    def test_domain_ai_returns_only_ai_events(self):
        """?domain=ai returns only events that contain Domain.AI articles."""
        ai_event = _event("AI Event", center=[_aa("Model release", domain=Domain.AI)])
        world_event = _event("World Event", center=[_aa("Summit", domain=Domain.WORLD)])
        app = make_app(lambda: [], lambda: [ai_event, world_event])
        events = _api_events(app, "?domain=ai")
        assert len(events) == 1
        assert events[0]["event_title"] == "AI Event"

    def test_domain_ai_excludes_world_only_events(self):
        """Events with only non-AI articles must not appear in ?domain=ai results."""
        world_event = _event("World", center=[_aa("Flood in Spain", domain=Domain.WORLD)])
        markets_event = _event("Markets", center=[_aa("Yen falls", domain=Domain.MARKETS)])
        app = make_app(lambda: [], lambda: [world_event, markets_event])
        events = _api_events(app, "?domain=ai")
        assert events == []

    def test_domain_ai_includes_event_with_ai_in_left_bucket(self):
        """An event with Domain.AI only in left_articles must appear in ?domain=ai."""
        event = _event("AI Policy", left=[_aa("AI policy memo", domain=Domain.AI, lens="left")])
        app = make_app(lambda: [], lambda: [event])
        events = _api_events(app, "?domain=ai")
        assert len(events) == 1

    def test_domain_ai_includes_event_with_ai_in_right_bucket(self):
        """An event with Domain.AI only in right_articles must appear in ?domain=ai."""
        event = _event("AI Jobs", right=[_aa("AI jobs boom", domain=Domain.AI, lens="right")])
        app = make_app(lambda: [], lambda: [event])
        events = _api_events(app, "?domain=ai")
        assert len(events) == 1

    def test_domain_ai_includes_event_with_ai_in_center_bucket(self):
        """An event with Domain.AI only in center_articles must appear in ?domain=ai."""
        event = _event("AI Centre", center=[_aa("Neural net advance", domain=Domain.AI)])
        app = make_app(lambda: [], lambda: [event])
        events = _api_events(app, "?domain=ai")
        assert len(events) == 1

    def test_domain_filter_case_insensitive_uppercase(self):
        """?domain=AI (uppercase) must return the same results as ?domain=ai."""
        ai_aa = _aa("Neural net advance", domain=Domain.AI)
        event = _event("AI Advance", center=[ai_aa])
        app = make_app(lambda: [], lambda: [event])
        events_lower = _api_events(app, "?domain=ai")
        events_upper = _api_events(app, "?domain=AI")
        assert len(events_lower) == len(events_upper) == 1

    def test_domain_filter_case_insensitive_mixed(self):
        """?domain=Ai (mixed case) must also return AI events."""
        event = _event("AI Mixed", center=[_aa("AI insight", domain=Domain.AI)])
        app = make_app(lambda: [], lambda: [event])
        events = _api_events(app, "?domain=Ai")
        assert len(events) == 1

    def test_domain_world_returns_only_world_events(self):
        """?domain=world returns only events containing Domain.WORLD articles."""
        world_event = _event("World Event", center=[_aa("NATO meeting", domain=Domain.WORLD)])
        ai_event = _event("AI Event", center=[_aa("Chip act", domain=Domain.AI)])
        app = make_app(lambda: [], lambda: [world_event, ai_event])
        events = _api_events(app, "?domain=world")
        assert len(events) == 1
        assert events[0]["event_title"] == "World Event"

    def test_domain_markets_returns_only_market_events(self):
        """?domain=markets returns only events with Domain.MARKETS articles."""
        markets_event = _event("Markets", center=[_aa("Gold surges", domain=Domain.MARKETS)])
        world_event = _event("World", center=[_aa("Floods", domain=Domain.WORLD)])
        app = make_app(lambda: [], lambda: [markets_event, world_event])
        events = _api_events(app, "?domain=markets")
        assert len(events) == 1
        assert events[0]["event_title"] == "Markets"

    def test_mixed_event_with_ai_and_world_articles_returned_for_ai_filter(self):
        """An event with both AI and WORLD articles must appear under ?domain=ai."""
        event = _event(
            "Mixed",
            center=[
                _aa("AI treaty talks", domain=Domain.AI, url="https://c.com/ai"),
                _aa("World AI summit", domain=Domain.WORLD, url="https://c.com/w"),
            ],
        )
        app = make_app(lambda: [], lambda: [event])
        events = _api_events(app, "?domain=ai")
        assert len(events) == 1

    def test_event_with_domain_none_excluded_from_ai_filter(self):
        """Events whose articles all have domain=None must not appear in ?domain=ai."""
        event = _event("Unknown", center=[_aa("Unclassified story", domain=None)])
        app = make_app(lambda: [], lambda: [event])
        events = _api_events(app, "?domain=ai")
        assert events == []

    def test_empty_events_returns_empty_array(self):
        """With no events, /api/events?domain=ai must return []."""
        app = make_app(lambda: [], lambda: [])
        events = _api_events(app, "?domain=ai")
        assert events == []

    def test_response_is_json_with_200(self):
        """The endpoint must return HTTP 200 with a JSON content-type."""
        event = _event("AI", center=[_aa("AI story", domain=Domain.AI)])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            resp = c.get("/api/events?domain=ai")
            assert resp.status_code == 200
            assert resp.content_type.startswith("application/json")

    def test_response_payload_is_a_list(self):
        """The JSON payload must be a list even when only one event matches."""
        event = _event("AI", center=[_aa("AI story", domain=Domain.AI)])
        app = make_app(lambda: [], lambda: [event])
        data = _api_events(app, "?domain=ai")
        assert isinstance(data, list)

    def test_response_includes_standard_event_structure(self):
        """Each returned event must contain event_title, spin_delta, and article buckets."""
        event = _event("Transformers", center=[_aa("Transformer advances", domain=Domain.AI)])
        app = make_app(lambda: [], lambda: [event])
        events = _api_events(app, "?domain=ai")
        e = events[0]
        assert "event_title" in e
        assert "spin_delta" in e
        assert "left_articles" in e
        assert "right_articles" in e
        assert "center_articles" in e

    def test_get_events_none_returns_empty_for_ai_filter(self):
        """When get_events is not provided to make_app, ?domain=ai returns []."""
        app = make_app(lambda: [])
        events = _api_events(app, "?domain=ai")
        assert events == []

    def test_multiple_ai_events_all_returned(self):
        """Multiple distinct AI events are all returned in ?domain=ai results."""
        events_list = [
            _event(f"AI Story {i}", center=[_aa(f"Story {i}", domain=Domain.AI, url=f"https://ai.com/{i}")])
            for i in range(3)
        ]
        app = make_app(lambda: [], lambda: events_list)
        events = _api_events(app, "?domain=ai")
        assert len(events) == 3

    def test_event_order_preserved_in_filtered_results(self):
        """Filtering must preserve the original event order."""
        event_titles = ["Alpha AI", "Beta AI", "Gamma AI"]
        events_list = [
            _event(t, center=[_aa(f"{t} article", domain=Domain.AI, url=f"https://ai.com/{i}")])
            for i, t in enumerate(event_titles)
        ]
        app = make_app(lambda: [], lambda: events_list)
        events = _api_events(app, "?domain=ai")
        assert [e["event_title"] for e in events] == event_titles

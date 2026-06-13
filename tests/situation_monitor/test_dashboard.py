"""Tests for dual-lens rendering in the web dashboard (situation_monitor/dashboard.py).

Covers: left/right column HTML structure, inline spin-badge estimator annotations,
event-card layout, spin_delta display, API endpoints for events and rationale.
"""

from __future__ import annotations

import json

import pytest

from situation_monitor.dashboard import _event_to_dict, make_app
from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
from situation_monitor.models import Article, SpinResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _article(
    title: str = "Default Title",
    url: str = "http://example.com/x",
    source: str = "example.com",
    source_lean: str | None = None,
) -> Article:
    a = Article(url=url, title=title, source=source)
    a.source_lean = source_lean
    return a


def _spin(spin_pct: float, lens: str, receipts: str = "stub") -> SpinResult:
    return SpinResult(spin_pct=spin_pct, lens=lens, rubric={}, receipts=receipts)


def _aa(title: str, url: str, source: str, spin_pct: float, lens: str) -> AnnotatedArticle:
    return AnnotatedArticle(
        article=_article(title=title, url=url, source=source),
        spin=_spin(spin_pct=spin_pct, lens=lens),
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


def _render(app, path: str = "/") -> str:
    with app.test_client() as c:
        return c.get(path).data.decode()


# ---------------------------------------------------------------------------
# Dual-lens column HTML structure
# ---------------------------------------------------------------------------


class TestDualLensColumnStructure:
    def test_col_left_class_present(self):
        """Left column must carry CSS class 'col-left'."""
        aa = _aa("Left view", "http://left.com/x", "l-src", 75.0, "left")
        app = make_app(lambda: [], lambda: [_event(left=[aa])])
        assert "col-left" in _render(app)

    def test_col_right_class_present(self):
        """Right column must carry CSS class 'col-right'."""
        aa = _aa("Right view", "http://right.com/x", "r-src", 35.0, "right")
        app = make_app(lambda: [], lambda: [_event(right=[aa])])
        assert "col-right" in _render(app)

    def test_left_h4_heading_rendered(self):
        """LEFT heading must appear as an h4 element."""
        aa = _aa("Left view", "http://l.com/x", "l-src", 70.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "<h4>LEFT</h4>" in html

    def test_right_h4_heading_rendered(self):
        """RIGHT heading must appear as an h4 element."""
        aa = _aa("Right view", "http://r.com/x", "r-src", 40.0, "right")
        html = _render(make_app(lambda: [], lambda: [_event(right=[aa])]))
        assert "<h4>RIGHT</h4>" in html

    def test_dual_cols_class_wraps_both_columns(self):
        """The dual-cols flex container must be present when events exist."""
        aa = _aa("Left", "http://l.com/x", "l-src", 70.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "dual-cols" in html

    def test_both_columns_present_for_dual_lens_event(self):
        left_aa = _aa("Left framing", "http://l.com/x", "l-src", 80.0, "left")
        right_aa = _aa("Right framing", "http://r.com/x", "r-src", 35.0, "right")
        html = _render(make_app(lambda: [], lambda: [_event(left=[left_aa], right=[right_aa])]))
        assert "col-left" in html
        assert "col-right" in html

    def test_event_card_class_present(self):
        """Each event must be wrapped in an 'event-card' div."""
        aa = _aa("Left view", "http://l.com/x", "l-src", 70.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "event-card" in html

    def test_event_title_appears_in_html(self):
        aa = _aa("Article about Belfast", "http://l.com/belfast", "src", 70.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event("The Belfast Peace Process", left=[aa])]))
        assert "The Belfast Peace Process" in html

    def test_multiple_events_all_rendered(self):
        aa1 = _aa("Belfast left", "http://l.com/1", "l-src", 75.0, "left")
        aa2 = _aa("Climate left", "http://l.com/2", "l-src", 65.0, "left")
        html = _render(make_app(lambda: [], lambda: [
            _event("Belfast Peace Talks", left=[aa1]),
            _event("Climate Summit", left=[aa2]),
        ]))
        assert "Belfast Peace Talks" in html
        assert "Climate Summit" in html

    def test_no_events_section_absent_when_event_list_empty(self):
        html = _render(make_app(lambda: [], lambda: []))
        assert "Dual-Lens Events" not in html

    def test_dual_lens_events_heading_present_when_events_exist(self):
        aa = _aa("Left view", "http://l.com/x", "l-src", 70.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "Dual-Lens Events" in html

    def test_no_events_callback_renders_without_error(self):
        """make_app without get_events callback must still return 200."""
        app = make_app(lambda: [])
        with app.test_client() as c:
            resp = c.get("/")
        assert resp.status_code == 200

    def test_article_url_appears_as_href_in_left_column(self):
        aa = _aa("Left article", "http://uniqueleft.example.com/story-77", "l-src", 70.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "http://uniqueleft.example.com/story-77" in html

    def test_article_url_appears_as_href_in_right_column(self):
        aa = _aa("Right article", "http://uniqueright.example.com/story-88", "r-src", 40.0, "right")
        html = _render(make_app(lambda: [], lambda: [_event(right=[aa])]))
        assert "http://uniqueright.example.com/story-88" in html

    def test_article_source_appears_in_left_column(self):
        aa = _aa("Left article", "http://l.com/x", "the-guardian.com", 70.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "the-guardian.com" in html

    def test_multiple_left_articles_all_appear(self):
        aa1 = _aa("Left view one", "http://l.com/1", "cnn.com", 80.0, "left")
        aa2 = _aa("Left view two", "http://l.com/2", "msnbc.com", 70.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa1, aa2])]))
        assert "cnn.com" in html
        assert "msnbc.com" in html

    def test_empty_left_shows_placeholder_text(self):
        """When left_articles is empty the template shows 'No left-framing articles'."""
        aa = _aa("Right only", "http://r.com/x", "r-src", 40.0, "right")
        html = _render(make_app(lambda: [], lambda: [_event(right=[aa])]))
        assert "No left-framing articles" in html

    def test_empty_right_shows_placeholder_text(self):
        """When right_articles is empty the template shows 'No right-framing articles'."""
        aa = _aa("Left only", "http://l.com/x", "l-src", 80.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "No right-framing articles" in html

    def test_non_empty_left_does_not_show_left_placeholder(self):
        aa = _aa("Left article", "http://l.com/x", "l-src", 75.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "No left-framing articles" not in html

    def test_non_empty_right_does_not_show_right_placeholder(self):
        aa = _aa("Right article", "http://r.com/x", "r-src", 40.0, "right")
        html = _render(make_app(lambda: [], lambda: [_event(right=[aa])]))
        assert "No right-framing articles" not in html


# ---------------------------------------------------------------------------
# Inline spin estimator annotations (spin-badge)
# ---------------------------------------------------------------------------


class TestSpinBadgeAnnotations:
    def test_spin_badge_class_present_in_left_column(self):
        """spin-badge span must appear in the article card."""
        aa = _aa("Left view", "http://l.com/x", "l-src", 73.5, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "spin-badge" in html

    def test_spin_pct_label_present(self):
        """The text 'spin_pct:' must appear in the article card."""
        aa = _aa("Left view", "http://l.com/x", "l-src", 73.5, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "spin_pct:" in html

    def test_spin_pct_value_formatted_one_decimal(self):
        """73.5 must appear as '73.5%' in the badge."""
        aa = _aa("Left view", "http://l.com/x", "l-src", 73.5, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "73.5%" in html

    def test_spin_pct_in_right_column(self):
        aa = _aa("Right view", "http://r.com/x", "r-src", 42.0, "right")
        html = _render(make_app(lambda: [], lambda: [_event(right=[aa])]))
        assert "42.0%" in html

    def test_spin_pct_zero_formatted_correctly(self):
        aa = _aa("Neutral left", "http://l.com/x", "l-src", 0.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "0.0%" in html

    def test_spin_pct_100_formatted_correctly(self):
        aa = _aa("Max spin", "http://l.com/x", "l-src", 100.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa])]))
        assert "100.0%" in html

    def test_two_articles_have_two_spin_badges(self):
        """Each article card gets its own badge regardless of values."""
        aa1 = _aa("First", "http://l.com/1", "l-src1", 60.0, "left")
        aa2 = _aa("Second", "http://l.com/2", "l-src2", 80.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa1, aa2])]))
        assert html.count("spin_pct:") == 2

    def test_spin_delta_class_present(self):
        aa = _aa("Left", "http://l.com/x", "l-src", 80.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa], spin_delta=80.0)]))
        assert "spin-delta" in html

    def test_spin_delta_value_rendered(self):
        """spin_delta must appear in the page with one decimal place."""
        left_aa = _aa("Left view", "http://l.com/x", "l-src", 80.0, "left")
        right_aa = _aa("Right view", "http://r.com/x", "r-src", 30.0, "right")
        html = _render(make_app(lambda: [], lambda: [
            _event(left=[left_aa], right=[right_aa], spin_delta=50.0)
        ]))
        assert "spin_delta:" in html
        assert "50.0" in html

    def test_spin_delta_zero_rendered(self):
        aa = _aa("Balanced", "http://l.com/x", "l-src", 50.0, "left")
        html = _render(make_app(lambda: [], lambda: [_event(left=[aa], spin_delta=0.0)]))
        assert "spin_delta:" in html


# ---------------------------------------------------------------------------
# /api/events JSON endpoint
# ---------------------------------------------------------------------------


class TestApiEventsEndpoint:
    def test_returns_200(self):
        app = make_app(lambda: [], lambda: [])
        with app.test_client() as c:
            assert c.get("/api/events").status_code == 200

    def test_empty_list_when_no_events(self):
        app = make_app(lambda: [], lambda: [])
        with app.test_client() as c:
            assert json.loads(c.get("/api/events").data) == []

    def test_returns_list_with_one_event(self):
        aa = _aa("Left view", "http://l.com/x", "l-src", 75.0, "left")
        event = _event("Belfast talks", left=[aa], spin_delta=75.0)
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert len(data) == 1
        assert data[0]["event_title"] == "Belfast talks"

    def test_event_dict_contains_left_and_right_articles(self):
        left_aa = _aa("Left", "http://l.com/x", "l-src", 75.0, "left")
        right_aa = _aa("Right", "http://r.com/x", "r-src", 35.0, "right")
        event = _event(left=[left_aa], right=[right_aa], spin_delta=40.0)
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert len(data[0]["left_articles"]) == 1
        assert len(data[0]["right_articles"]) == 1

    def test_spin_delta_in_response(self):
        left_aa = _aa("Left", "http://l.com/x", "l-src", 80.0, "left")
        right_aa = _aa("Right", "http://r.com/x", "r-src", 30.0, "right")
        event = _event(left=[left_aa], right=[right_aa], spin_delta=50.0)
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert pytest.approx(50.0) == data[0]["spin_delta"]

    def test_article_dict_contains_spin_pct(self):
        aa = _aa("Left view", "http://l.com/x", "l-src", 73.5, "left")
        event = _event(left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert pytest.approx(73.5) == data[0]["left_articles"][0]["spin_pct"]

    def test_article_dict_contains_spin_lens(self):
        aa = _aa("Left view", "http://l.com/x", "l-src", 73.5, "left")
        event = _event(left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert data[0]["left_articles"][0]["spin_lens"] == "left"

    def test_article_dict_contains_spin_receipts(self):
        aa = AnnotatedArticle(
            article=_article("Left view", "http://l.com/x", "l-src"),
            spin=_spin(75.0, "left", receipts="Spin signal: loaded language"),
        )
        event = _event(left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert "Spin signal" in data[0]["left_articles"][0]["spin_receipts"]

    def test_article_dict_contains_title_and_url(self):
        aa = _aa("Test Title", "http://test-url.com/story", "test-src", 60.0, "left")
        event = _event(left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        art = data[0]["left_articles"][0]
        assert art["title"] == "Test Title"
        assert art["url"] == "http://test-url.com/story"

    def test_multiple_events_all_in_response(self):
        aa1 = _aa("Left 1", "http://l.com/1", "s1", 70.0, "left")
        aa2 = _aa("Left 2", "http://l.com/2", "s2", 65.0, "left")
        app = make_app(lambda: [], lambda: [
            _event("Event A", left=[aa1]),
            _event("Event B", left=[aa2]),
        ])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert len(data) == 2
        titles = {d["event_title"] for d in data}
        assert titles == {"Event A", "Event B"}

    def test_no_get_events_callback_returns_empty_list(self):
        app = make_app(lambda: [])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert data == []

    def test_center_articles_in_response(self):
        center_aa = _aa("Center", "http://c.com/x", "c-src", 50.0, "center")
        event = _event(center=[center_aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events").data)
        assert len(data[0]["center_articles"]) == 1


# ---------------------------------------------------------------------------
# /api/events/<cluster_id>/rationale endpoint
# ---------------------------------------------------------------------------


class TestApiEventRationale:
    def test_returns_200_for_valid_index(self):
        aa = _aa("Left view", "http://l.com/x", "l-src", 75.0, "left")
        event = _event(left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            assert c.get("/api/events/0/rationale").status_code == 200

    def test_contains_event_title(self):
        aa = _aa("Left view", "http://l.com/x", "l-src", 75.0, "left")
        event = _event("Belfast Talks Analysis", left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events/0/rationale").data)
        assert data["event_title"] == "Belfast Talks Analysis"

    def test_receipts_field_present(self):
        aa = AnnotatedArticle(
            article=_article("Left view", "http://l.com/x", "l-src"),
            spin=_spin(75.0, "left", receipts="Spin signals fired: Loaded Language (0.80)"),
        )
        event = _event(left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events/0/rationale").data)
        assert "receipts" in data
        assert any("Spin signals fired" in r["receipts"] for r in data["receipts"])

    def test_receipts_includes_all_articles(self):
        left_aa = _aa("Left", "http://l.com/1", "l-src", 75.0, "left")
        right_aa = _aa("Right", "http://r.com/1", "r-src", 35.0, "right")
        event = _event(left=[left_aa], right=[right_aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events/0/rationale").data)
        assert len(data["receipts"]) == 2

    def test_out_of_range_index_returns_404(self):
        app = make_app(lambda: [], lambda: [])
        with app.test_client() as c:
            assert c.get("/api/events/0/rationale").status_code == 404

    def test_negative_index_returns_404(self):
        aa = _aa("Left view", "http://l.com/x", "l-src", 75.0, "left")
        event = _event(left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            assert c.get("/api/events/-1/rationale").status_code == 404

    def test_non_integer_cluster_id_returns_404(self):
        aa = _aa("Left view", "http://l.com/x", "l-src", 75.0, "left")
        event = _event(left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            assert c.get("/api/events/not-a-number/rationale").status_code == 404

    def test_too_large_index_returns_404(self):
        aa = _aa("Left view", "http://l.com/x", "l-src", 75.0, "left")
        event = _event(left=[aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            assert c.get("/api/events/99/rationale").status_code == 404

    def test_center_articles_included_in_receipts(self):
        center_aa = _aa("Center", "http://c.com/x", "c-src", 50.0, "center")
        event = _event(center=[center_aa])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            data = json.loads(c.get("/api/events/0/rationale").data)
        assert len(data["receipts"]) == 1


# ---------------------------------------------------------------------------
# /api/practical endpoint
# ---------------------------------------------------------------------------


class TestApiPractical:
    def test_returns_200_without_callback(self):
        app = make_app(lambda: [])
        with app.test_client() as c:
            assert c.get("/api/practical").status_code == 200

    def test_returns_empty_list_without_callback(self):
        app = make_app(lambda: [])
        with app.test_client() as c:
            assert json.loads(c.get("/api/practical").data) == []

    def test_returns_empty_list_when_callback_returns_empty(self):
        app = make_app(lambda: [], get_practical=lambda: [])
        with app.test_client() as c:
            assert json.loads(c.get("/api/practical").data) == []


# ---------------------------------------------------------------------------
# _event_to_dict helper
# ---------------------------------------------------------------------------


class TestEventToDict:
    def test_event_title_in_dict(self):
        event = _event("My Event Title")
        d = _event_to_dict(event)
        assert d["event_title"] == "My Event Title"

    def test_spin_delta_in_dict(self):
        event = _event(spin_delta=42.5)
        d = _event_to_dict(event)
        assert pytest.approx(42.5) == d["spin_delta"]

    def test_left_articles_list_in_dict(self):
        aa = _aa("Left", "http://l.com/x", "l-src", 70.0, "left")
        event = _event(left=[aa])
        d = _event_to_dict(event)
        assert len(d["left_articles"]) == 1

    def test_right_articles_list_in_dict(self):
        aa = _aa("Right", "http://r.com/x", "r-src", 40.0, "right")
        event = _event(right=[aa])
        d = _event_to_dict(event)
        assert len(d["right_articles"]) == 1

    def test_center_articles_list_in_dict(self):
        aa = _aa("Center", "http://c.com/x", "c-src", 50.0, "center")
        event = _event(center=[aa])
        d = _event_to_dict(event)
        assert len(d["center_articles"]) == 1

    def test_article_dict_has_required_keys(self):
        aa = _aa("Title", "http://x.com/x", "src", 60.0, "left")
        event = _event(left=[aa])
        d = _event_to_dict(event)
        art = d["left_articles"][0]
        for key in ("url", "title", "source", "spin_pct", "spin_lens", "spin_receipts"):
            assert key in art, f"Missing key: {key}"

    def test_empty_event_all_article_lists_empty(self):
        event = _event()
        d = _event_to_dict(event)
        assert d["left_articles"] == []
        assert d["right_articles"] == []
        assert d["center_articles"] == []

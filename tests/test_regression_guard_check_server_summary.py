"""Regression guard: check_server.py improvements and run_summary.txt content.

Acceptance criteria under test (distinct from existing test files):
  1. check_server.py subprocess → exits 0 + prints 'web-server-smoke: PASS'
  2. run_summary.txt written by check_server.py contains DUAL_LENS/SPIN/WEB PASS entries
  3. make_app(get_events=...) renders 'Dual-Lens Events' in the HTML body
  4. Flask /api/events endpoint returns valid JSON with event data
  5. Flask /api/events/<id>/rationale returns event rationale JSON
  6. acceptance cmd1 ('once') exits 0; stdout contains '## DUAL-LENS EVENTS' and 'spin_pct:'
  7. Dashboard domain-filter route works for world/markets/ai filters

Independent tester: the unit under test is NEVER mocked.
Every assertion CAN fail on a genuine regression.
No subprocess invocation of pytest (project memory: recursive pytest hangs the suite).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"
RUN_SUMMARY = PROJECT_ROOT / "run_summary.txt"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"
RSS_LEFT = FIXTURES / "rss_left.xml"
RSS_RIGHT = FIXTURES / "rss_right.xml"

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _offline_env(**extra: str) -> dict[str, str]:
    return {**os.environ, "SM_LLM_BACKEND": "offline", "SM_SOURCES": str(RSS_FIXTURE), **extra}


def _make_article(title: str, url: str = "", source: str = "test.com", source_lean: str | None = None):
    from situation_monitor.models import Article

    url = url or f"http://test.example.com/{title.lower().replace(' ', '-')[:40]}"
    a = Article(url=url, title=title, source=source)
    a.source_lean = source_lean
    return a


def _make_spin(pct: float, lens: str):
    from situation_monitor.models import SpinResult

    return SpinResult(spin_pct=pct, lens=lens, rubric={}, receipts=f"receipt for {lens}")


def _make_annotated(title: str, lean: str, spin_pct: float = 50.0):
    from situation_monitor.dual_lens import AnnotatedArticle

    return AnnotatedArticle(
        article=_make_article(title, source_lean=lean),
        spin=_make_spin(spin_pct, lean),
    )


def _make_dual_lens_event(
    title: str,
    left: list | None = None,
    right: list | None = None,
    spin_delta: float = 0.0,
):
    from situation_monitor.dual_lens import DualLensEvent

    return DualLensEvent(
        event_title=title,
        left_articles=left or [],
        right_articles=right or [],
        center_articles=[],
        spin_delta=spin_delta,
    )


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixtures — each expensive process runs once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def check_server_result() -> subprocess.CompletedProcess:
    """Run check_server.py with SM_LLM_BACKEND=offline; capture stdout and exit code."""
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    return subprocess.run(
        [sys.executable, str(CHECK_SERVER)],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=120,
    )


@pytest.fixture(scope="module")
def check_server_stdout(check_server_result: subprocess.CompletedProcess) -> str:
    return check_server_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def check_server_stderr(check_server_result: subprocess.CompletedProcess) -> str:
    return check_server_result.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def once_proc() -> subprocess.CompletedProcess:
    """Acceptance cmd1: 'once' with offline LLM and fixture source defs."""
    return subprocess.run(
        [sys.executable, "-m", "situation_monitor", "once",
         "--config", str(ACCEPTANCE_SOURCE_DEFS)],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def once_stdout(once_proc: subprocess.CompletedProcess) -> str:
    return once_proc.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# 1. check_server.py subprocess — exit code and PASS marker
# ---------------------------------------------------------------------------


class TestCheckServerSubprocess:
    """check_server.py must exit 0 and print 'web-server-smoke: PASS'."""

    def test_exits_zero(self, check_server_result: subprocess.CompletedProcess) -> None:
        stderr = check_server_result.stderr.decode(errors="replace")
        assert check_server_result.returncode == 0, (
            f"check_server.py exited {check_server_result.returncode}.\n"
            f"stderr:\n{stderr[-800:]}"
        )

    def test_stdout_contains_pass_marker(self, check_server_stdout: str) -> None:
        assert "web-server-smoke: PASS" in check_server_stdout, (
            "check_server.py must print 'web-server-smoke: PASS'.\n"
            f"stdout:\n{check_server_stdout!r}"
        )

    def test_pass_marker_is_standalone_line(self, check_server_stdout: str) -> None:
        lines = check_server_stdout.splitlines()
        assert any(line == "web-server-smoke: PASS" for line in lines), (
            "'web-server-smoke: PASS' must appear as a complete standalone line.\n"
            f"Lines: {lines}"
        )

    def test_no_traceback_in_stdout(self, check_server_stdout: str) -> None:
        assert "Traceback" not in check_server_stdout, (
            "check_server.py stdout must not contain a Python Traceback"
        )

    def test_no_traceback_in_stderr(self, check_server_stderr: str) -> None:
        assert "Traceback" not in check_server_stderr, (
            "check_server.py stderr must not contain a Python Traceback"
        )

    def test_stdout_is_non_empty(self, check_server_stdout: str) -> None:
        assert check_server_stdout.strip(), "check_server.py must produce non-empty stdout"


# ---------------------------------------------------------------------------
# 2. run_summary.txt — content written by check_server.py
# ---------------------------------------------------------------------------


class TestRunSummaryFile:
    """run_summary.txt must be created by check_server.py with the correct PASS entries."""

    def test_run_summary_exists_after_check_server(
        self, check_server_result: subprocess.CompletedProcess
    ) -> None:
        """After check_server.py runs successfully, run_summary.txt must exist."""
        assert check_server_result.returncode == 0, (
            "check_server.py must exit 0 for run_summary.txt to be written; "
            "skipping run_summary.txt checks because the script failed"
        )
        assert RUN_SUMMARY.exists(), (
            f"run_summary.txt not found at {RUN_SUMMARY} after check_server.py ran.\n"
            "check_server.py must write this file before exiting."
        )

    def test_run_summary_contains_dual_lens_pass(
        self, check_server_result: subprocess.CompletedProcess
    ) -> None:
        assert check_server_result.returncode == 0
        content = RUN_SUMMARY.read_text(errors="replace")
        assert "DUAL_LENS: PASS" in content, (
            f"run_summary.txt must contain 'DUAL_LENS: PASS'.\nContent:\n{content}"
        )

    def test_run_summary_contains_spin_pass(
        self, check_server_result: subprocess.CompletedProcess
    ) -> None:
        assert check_server_result.returncode == 0
        content = RUN_SUMMARY.read_text(errors="replace")
        assert "SPIN: PASS" in content, (
            f"run_summary.txt must contain 'SPIN: PASS'.\nContent:\n{content}"
        )

    def test_run_summary_contains_web_pass(
        self, check_server_result: subprocess.CompletedProcess
    ) -> None:
        assert check_server_result.returncode == 0
        content = RUN_SUMMARY.read_text(errors="replace")
        assert "WEB: PASS" in content, (
            f"run_summary.txt must contain 'WEB: PASS'.\nContent:\n{content}"
        )

    def test_run_summary_has_no_fail_entries(
        self, check_server_result: subprocess.CompletedProcess
    ) -> None:
        """No line should contain FAIL — all three checks must pass."""
        assert check_server_result.returncode == 0
        content = RUN_SUMMARY.read_text(errors="replace")
        fail_lines = [l for l in content.splitlines() if ": FAIL" in l]
        assert not fail_lines, (
            f"run_summary.txt must not contain any FAIL entries.\n"
            f"Failing lines: {fail_lines}"
        )

    def test_run_summary_is_non_empty(
        self, check_server_result: subprocess.CompletedProcess
    ) -> None:
        assert check_server_result.returncode == 0
        content = RUN_SUMMARY.read_text(errors="replace")
        assert content.strip(), "run_summary.txt must not be empty after check_server.py runs"

    def test_run_summary_pass_entries_are_on_separate_lines(
        self, check_server_result: subprocess.CompletedProcess
    ) -> None:
        """DUAL_LENS, SPIN, and WEB PASS entries must each occupy their own line."""
        assert check_server_result.returncode == 0
        lines = [l.rstrip() for l in RUN_SUMMARY.read_text(errors="replace").splitlines()]
        assert any("DUAL_LENS: PASS" in l for l in lines), (
            "'DUAL_LENS: PASS' must appear on its own line in run_summary.txt"
        )
        assert any("SPIN: PASS" in l for l in lines), (
            "'SPIN: PASS' must appear on its own line in run_summary.txt"
        )
        assert any("WEB: PASS" in l for l in lines), (
            "'WEB: PASS' must appear on its own line in run_summary.txt"
        )


# ---------------------------------------------------------------------------
# 3. check_server.py source structure — the new 'Dual-Lens Events' assertion
# ---------------------------------------------------------------------------


class TestCheckServerSourceStructure:
    """check_server.py source must assert the Dual-Lens Events section, use group_by_event, etc."""

    def _source(self) -> str:
        return CHECK_SERVER.read_text(errors="replace")

    def test_check_server_exists(self) -> None:
        assert CHECK_SERVER.exists(), f"check_server.py not found at {CHECK_SERVER}"

    def test_check_server_asserts_dual_lens_events_in_body(self) -> None:
        """check_server.py must assert 'Dual-Lens Events' appears in the response body."""
        source = self._source()
        assert "Dual-Lens Events" in source, (
            "check_server.py must assert 'Dual-Lens Events' in the HTTP response body.\n"
            "The dashboard renders this section when events are non-empty."
        )

    def test_check_server_asserts_situation_monitor_in_body(self) -> None:
        """check_server.py must assert 'Situation Monitor' appears in the response body."""
        source = self._source()
        assert "Situation Monitor" in source, (
            "check_server.py must assert 'Situation Monitor' in the response body"
        )

    def test_check_server_asserts_http_200(self) -> None:
        source = self._source()
        assert "200" in source, "check_server.py must assert HTTP 200 from the test client"

    def test_check_server_imports_group_by_event(self) -> None:
        """check_server.py must import and use group_by_event from dual_lens."""
        source = self._source()
        assert "group_by_event" in source, (
            "check_server.py must import/use group_by_event from situation_monitor.dual_lens.\n"
            "Without it the events parameter to make_app would always be empty."
        )

    def test_check_server_passes_get_events_to_make_app(self) -> None:
        """check_server.py must pass get_events= kwarg to make_app."""
        source = self._source()
        assert "get_events" in source, (
            "check_server.py must pass get_events= to make_app so the dashboard\n"
            "renders the dual-lens events section in the HTML."
        )

    def test_check_server_writes_dual_lens_pass_to_summary(self) -> None:
        source = self._source()
        assert "DUAL_LENS: PASS" in source, (
            "check_server.py must write 'DUAL_LENS: PASS' to run_summary.txt"
        )

    def test_check_server_writes_spin_pass_to_summary(self) -> None:
        source = self._source()
        assert "SPIN: PASS" in source, (
            "check_server.py must write 'SPIN: PASS' to run_summary.txt"
        )

    def test_check_server_writes_web_pass_to_summary(self) -> None:
        source = self._source()
        assert "WEB: PASS" in source, (
            "check_server.py must write 'WEB: PASS' to run_summary.txt"
        )

    def test_check_server_calls_ingest_and_enrich(self) -> None:
        source = self._source()
        assert "_ingest_and_enrich" in source, (
            "check_server.py must call _ingest_and_enrich to produce real articles.\n"
            "A hard-coded empty list would not exercise the ingest pipeline."
        )

    def test_check_server_prints_pass_marker(self) -> None:
        source = self._source()
        assert "web-server-smoke: PASS" in source, (
            "check_server.py must print the literal string 'web-server-smoke: PASS'"
        )


# ---------------------------------------------------------------------------
# 4. make_app with get_events — 'Dual-Lens Events' renders in HTML
# ---------------------------------------------------------------------------


class TestMakeAppWithDualLensEvents:
    """make_app(get_events=...) must render the 'Dual-Lens Events' section in HTML."""

    def _render(self, path: str = "/", **make_app_kwargs) -> str:
        from situation_monitor.dashboard import make_app

        app = make_app(**make_app_kwargs)
        with app.test_client() as client:
            return client.get(path).data.decode(errors="replace")

    def _climate_event(self):
        left_aa = _make_annotated(
            "Climate Policy Reform Backed by Scientists", lean="left", spin_pct=43.4
        )
        right_aa = _make_annotated(
            "Climate Policy Reform Threatens Economic Growth", lean="right", spin_pct=68.2
        )
        return _make_dual_lens_event(
            "Climate Policy Reform",
            left=[left_aa],
            right=[right_aa],
            spin_delta=24.8,
        )

    def test_dual_lens_events_heading_present_with_events(self) -> None:
        """When events are provided via get_events, 'Dual-Lens Events' must appear in HTML."""
        event = self._climate_event()
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "Dual-Lens Events" in html, (
            "'Dual-Lens Events' section must appear in HTML when get_events returns events.\n"
            "This is the HTML heading rendered by the dashboard template."
        )

    def test_dual_lens_events_absent_when_no_events(self) -> None:
        """Without events, the 'Dual-Lens Events' section must not appear in HTML."""
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [],
        )
        assert "Dual-Lens Events" not in html, (
            "'Dual-Lens Events' section must NOT appear when get_events returns empty list"
        )

    def test_dual_lens_events_absent_when_get_events_omitted(self) -> None:
        """Without get_events kwarg (None default), no dual-lens section in HTML."""
        html = self._render(get_stories=lambda: [])
        assert "Dual-Lens Events" not in html, (
            "'Dual-Lens Events' section must NOT appear when get_events kwarg is omitted"
        )

    def test_event_title_rendered_in_html(self) -> None:
        event = self._climate_event()
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "Climate Policy Reform" in html, (
            "Event title must appear in the HTML body when events are rendered"
        )

    def test_spin_pct_badge_rendered_in_html(self) -> None:
        event = self._climate_event()
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "spin_pct:" in html, (
            "'spin_pct:' label must appear in the HTML dashboard when events are present"
        )

    def test_spin_delta_rendered_in_html(self) -> None:
        event = self._climate_event()
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "spin_delta:" in html, (
            "'spin_delta:' annotation must appear in the HTML event card"
        )

    def test_left_column_rendered_in_html(self) -> None:
        event = self._climate_event()
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "LEFT" in html, "LEFT column heading must appear in the HTML event card"

    def test_right_column_rendered_in_html(self) -> None:
        event = self._climate_event()
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "RIGHT" in html, "RIGHT column heading must appear in the HTML event card"

    def test_left_article_title_in_left_column(self) -> None:
        event = self._climate_event()
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "Climate Policy Reform Backed by Scientists" in html, (
            "Left article title must appear in the HTML dual-lens section"
        )

    def test_right_article_title_in_right_column(self) -> None:
        event = self._climate_event()
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "Climate Policy Reform Threatens Economic Growth" in html, (
            "Right article title must appear in the HTML dual-lens section"
        )

    def test_spin_pct_value_is_numeric_in_html(self) -> None:
        event = self._climate_event()
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        # The template formats with '%.1f' format
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", html)
        assert matches, "spin_pct: N.N% pattern must appear in HTML with numeric value"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, f"spin_pct {val} is outside [0, 100] range"

    def test_multiple_events_both_rendered(self) -> None:
        e1 = _make_dual_lens_event(
            "Federal Reserve Rate Hike",
            left=[_make_annotated("Guardian: rate hike hurts workers", lean="left")],
            right=[_make_annotated("Fox: rate hike fights inflation", lean="right")],
        )
        e2 = _make_dual_lens_event(
            "Immigration Bill Vote",
            left=[_make_annotated("CNN: immigration bill humanitarian", lean="left")],
            right=[_make_annotated("Fox: immigration bill porous border", lean="right")],
        )
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [e1, e2],
        )
        assert "Federal Reserve Rate Hike" in html, "First event title must be in HTML"
        assert "Immigration Bill Vote" in html, "Second event title must be in HTML"

    def test_empty_left_shows_no_left_articles_placeholder(self) -> None:
        """When left_articles is empty, the template shows 'No left-framing articles'."""
        event = _make_dual_lens_event(
            "One-sided Report",
            right=[_make_annotated("Fox only story", lean="right")],
        )
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "No left-framing articles" in html, (
            "Dashboard must show 'No left-framing articles' placeholder when left column is empty"
        )

    def test_empty_right_shows_no_right_articles_placeholder(self) -> None:
        event = _make_dual_lens_event(
            "One-sided Left Report",
            left=[_make_annotated("Guardian only story", lean="left")],
        )
        html = self._render(
            get_stories=lambda: [],
            get_events=lambda: [event],
        )
        assert "No right-framing articles" in html, (
            "Dashboard must show 'No right-framing articles' placeholder when right column is empty"
        )

    def test_make_app_with_real_fixture_articles_renders_dual_lens(self, monkeypatch) -> None:
        """End-to-end: ingest fixture articles → group_by_event → make_app → HTML has dual-lens."""
        monkeypatch.setenv("SM_LLM_BACKEND", "offline")
        monkeypatch.setenv("SM_SOURCES", str(RSS_FIXTURE))
        from situation_monitor.config import Config
        from situation_monitor.dashboard import make_app
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.__main__ import _ingest_and_enrich

        config = Config.from_file(str(ACCEPTANCE_SOURCE_DEFS))
        config.llm_backend = "offline"
        articles = _ingest_and_enrich(config)
        events = group_by_event(articles)

        assert events, "group_by_event must return at least one event from fixture articles"

        app = make_app(lambda: articles, get_events=lambda: events)
        with app.test_client() as client:
            resp = client.get("/")
            body = resp.data.decode(errors="replace")

        assert resp.status_code == 200, f"Expected HTTP 200; got {resp.status_code}"
        assert "Dual-Lens Events" in body, (
            "Dashboard must render 'Dual-Lens Events' section when fixture articles "
            "produce at least one dual-lens event via group_by_event"
        )


# ---------------------------------------------------------------------------
# 5. Flask /api/events endpoint — JSON contract
# ---------------------------------------------------------------------------


class TestFlaskApiEventsEndpoint:
    """/api/events must return valid JSON with the correct event structure."""

    def _app_with_events(self):
        from situation_monitor.dashboard import make_app

        left_aa = _make_annotated("Guardian: climate deal hailed", lean="left", spin_pct=45.0)
        right_aa = _make_annotated("Fox: climate deal costly", lean="right", spin_pct=72.0)
        event = _make_dual_lens_event(
            "Climate Deal Summit",
            left=[left_aa],
            right=[right_aa],
            spin_delta=27.0,
        )
        return make_app(get_stories=lambda: [], get_events=lambda: [event])

    def _app_empty(self):
        from situation_monitor.dashboard import make_app

        return make_app(get_stories=lambda: [], get_events=lambda: [])

    def test_api_events_returns_200(self) -> None:
        app = self._app_with_events()
        with app.test_client() as client:
            resp = client.get("/api/events")
        assert resp.status_code == 200, f"/api/events returned {resp.status_code}"

    def test_api_events_returns_json_content_type(self) -> None:
        app = self._app_with_events()
        with app.test_client() as client:
            resp = client.get("/api/events")
        assert resp.content_type.startswith("application/json"), (
            f"/api/events must return application/json; got {resp.content_type!r}"
        )

    def test_api_events_empty_returns_empty_list(self) -> None:
        app = self._app_empty()
        with app.test_client() as client:
            resp = client.get("/api/events")
        data = json.loads(resp.data)
        assert data == [], f"/api/events with no events must return []; got {data!r}"

    def test_api_events_returns_list_with_one_event(self) -> None:
        app = self._app_with_events()
        with app.test_client() as client:
            resp = client.get("/api/events")
        data = json.loads(resp.data)
        assert isinstance(data, list), f"/api/events must return a JSON array; got {type(data)}"
        assert len(data) == 1, f"Expected 1 event in /api/events response; got {len(data)}"

    def test_api_events_event_has_event_title(self) -> None:
        app = self._app_with_events()
        with app.test_client() as client:
            resp = client.get("/api/events")
        data = json.loads(resp.data)
        assert data[0]["event_title"] == "Climate Deal Summit", (
            f"event_title must be 'Climate Deal Summit'; got {data[0].get('event_title')!r}"
        )

    def test_api_events_event_has_spin_delta(self) -> None:
        app = self._app_with_events()
        with app.test_client() as client:
            resp = client.get("/api/events")
        data = json.loads(resp.data)
        assert "spin_delta" in data[0], "/api/events event must have 'spin_delta' key"
        assert float(data[0]["spin_delta"]) >= 0.0, "spin_delta must be non-negative"

    def test_api_events_event_has_left_articles(self) -> None:
        app = self._app_with_events()
        with app.test_client() as client:
            resp = client.get("/api/events")
        data = json.loads(resp.data)
        assert "left_articles" in data[0], "/api/events event must have 'left_articles' key"
        assert len(data[0]["left_articles"]) == 1, "Expected 1 left article in /api/events"

    def test_api_events_event_has_right_articles(self) -> None:
        app = self._app_with_events()
        with app.test_client() as client:
            resp = client.get("/api/events")
        data = json.loads(resp.data)
        assert "right_articles" in data[0], "/api/events event must have 'right_articles' key"
        assert len(data[0]["right_articles"]) == 1, "Expected 1 right article in /api/events"

    def test_api_events_article_has_spin_pct(self) -> None:
        app = self._app_with_events()
        with app.test_client() as client:
            resp = client.get("/api/events")
        data = json.loads(resp.data)
        left = data[0]["left_articles"][0]
        assert "spin_pct" in left, "Left article in /api/events must have 'spin_pct' key"
        val = float(left["spin_pct"])
        assert 0.0 <= val <= 100.0, f"spin_pct {val} must be in [0, 100]"

    def test_api_events_article_has_title(self) -> None:
        app = self._app_with_events()
        with app.test_client() as client:
            resp = client.get("/api/events")
        data = json.loads(resp.data)
        left = data[0]["left_articles"][0]
        assert "title" in left, "Left article in /api/events must have 'title' key"
        assert left["title"], "Left article title must be non-empty"


# ---------------------------------------------------------------------------
# 6. Flask /api/events/<id>/rationale endpoint
# ---------------------------------------------------------------------------


class TestFlaskApiEventRationale:
    """/api/events/<id>/rationale must return event rationale JSON."""

    def _app_with_receipt_event(self):
        from situation_monitor.dashboard import make_app
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa_left = AnnotatedArticle(
            article=_make_article("Guardian: immigration reform praised", source_lean="left"),
            spin=SpinResult(
                spin_pct=60.0, lens="left", rubric={},
                receipts="Spin signals fired — Loaded Language: reform"
            ),
        )
        event = DualLensEvent(
            event_title="Immigration Reform Bill",
            left_articles=[aa_left],
            right_articles=[],
            center_articles=[],
            spin_delta=0.0,
        )
        return make_app(get_stories=lambda: [], get_events=lambda: [event])

    def test_rationale_endpoint_returns_200_for_valid_index(self) -> None:
        app = self._app_with_receipt_event()
        with app.test_client() as client:
            resp = client.get("/api/events/0/rationale")
        assert resp.status_code == 200, (
            f"/api/events/0/rationale must return 200 for a valid event; got {resp.status_code}"
        )

    def test_rationale_endpoint_returns_json(self) -> None:
        app = self._app_with_receipt_event()
        with app.test_client() as client:
            resp = client.get("/api/events/0/rationale")
        assert resp.content_type.startswith("application/json"), (
            "/api/events/0/rationale must return application/json"
        )

    def test_rationale_json_has_event_title(self) -> None:
        app = self._app_with_receipt_event()
        with app.test_client() as client:
            resp = client.get("/api/events/0/rationale")
        data = json.loads(resp.data)
        assert "event_title" in data, "Rationale JSON must have 'event_title' key"
        assert data["event_title"] == "Immigration Reform Bill", (
            f"event_title must be 'Immigration Reform Bill'; got {data.get('event_title')!r}"
        )

    def test_rationale_json_has_receipts(self) -> None:
        app = self._app_with_receipt_event()
        with app.test_client() as client:
            resp = client.get("/api/events/0/rationale")
        data = json.loads(resp.data)
        assert "receipts" in data, "Rationale JSON must have 'receipts' key"
        assert isinstance(data["receipts"], list), "receipts must be a list"

    def test_rationale_receipt_has_title_and_receipts_fields(self) -> None:
        app = self._app_with_receipt_event()
        with app.test_client() as client:
            resp = client.get("/api/events/0/rationale")
        data = json.loads(resp.data)
        assert data["receipts"], "receipts list must not be empty"
        receipt = data["receipts"][0]
        assert "title" in receipt, "Each receipt must have 'title' key"
        assert "receipts" in receipt, "Each receipt must have 'receipts' key"

    def test_rationale_endpoint_returns_404_for_out_of_range_index(self) -> None:
        app = self._app_with_receipt_event()
        with app.test_client() as client:
            resp = client.get("/api/events/999/rationale")
        assert resp.status_code == 404, (
            "/api/events/999/rationale must return 404 for out-of-range index; "
            f"got {resp.status_code}"
        )

    def test_rationale_endpoint_returns_404_for_non_integer_id(self) -> None:
        app = self._app_with_receipt_event()
        with app.test_client() as client:
            resp = client.get("/api/events/not-an-int/rationale")
        assert resp.status_code == 404, (
            "/api/events/not-an-int/rationale must return 404 for non-integer cluster_id; "
            f"got {resp.status_code}"
        )

    def test_rationale_endpoint_returns_404_for_negative_index(self) -> None:
        app = self._app_with_receipt_event()
        with app.test_client() as client:
            resp = client.get("/api/events/-1/rationale")
        # Negative index: should be 404 (idx < 0 check) or 404 from non-integer route
        assert resp.status_code == 404, (
            "/api/events/-1/rationale must return 404; got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# 7. Flask domain filtering
# ---------------------------------------------------------------------------


class TestFlaskDomainFiltering:
    """Dashboard must filter stories by domain when ?domain= is provided."""

    def _app_with_domain_articles(self):
        from situation_monitor.dashboard import make_app
        from situation_monitor.models import Domain

        world_article = _make_article("Brexit deal update", source="bbc.com")
        world_article.domain = Domain.WORLD
        ai_article = _make_article("New LLM released", source="techcrunch.com")
        ai_article.domain = Domain.AI
        markets_article = _make_article("SP500 hits record high", source="wsj.com")
        markets_article.domain = Domain.MARKETS

        return make_app(
            get_stories=lambda: [world_article, ai_article, markets_article],
            get_events=lambda: [],
        )

    def test_world_filter_includes_world_articles(self) -> None:
        app = self._app_with_domain_articles()
        with app.test_client() as client:
            html = client.get("/?domain=world").data.decode()
        assert "Brexit deal update" in html, (
            "World article must appear when domain=world filter is applied"
        )

    def test_world_filter_excludes_ai_articles(self) -> None:
        app = self._app_with_domain_articles()
        with app.test_client() as client:
            html = client.get("/?domain=world").data.decode()
        assert "New LLM released" not in html, (
            "AI article must NOT appear when domain=world filter is applied"
        )

    def test_ai_filter_includes_ai_articles(self) -> None:
        app = self._app_with_domain_articles()
        with app.test_client() as client:
            html = client.get("/?domain=ai").data.decode()
        assert "New LLM released" in html, (
            "AI article must appear when domain=ai filter is applied"
        )

    def test_ai_filter_excludes_markets_articles(self) -> None:
        app = self._app_with_domain_articles()
        with app.test_client() as client:
            html = client.get("/?domain=ai").data.decode()
        assert "SP500 hits record high" not in html, (
            "Markets article must NOT appear when domain=ai filter is applied"
        )

    def test_no_filter_returns_all_articles(self) -> None:
        app = self._app_with_domain_articles()
        with app.test_client() as client:
            html = client.get("/").data.decode()
        assert "Brexit deal update" in html
        assert "New LLM released" in html
        assert "SP500 hits record high" in html

    def test_domain_filter_http_200(self) -> None:
        app = self._app_with_domain_articles()
        with app.test_client() as client:
            resp = client.get("/?domain=markets")
        assert resp.status_code == 200, (
            f"?domain=markets must return HTTP 200; got {resp.status_code}"
        )

    def test_unknown_domain_returns_empty_table_not_error(self) -> None:
        """An unrecognised domain filter must not crash — it returns 200 with no matching rows."""
        app = self._app_with_domain_articles()
        with app.test_client() as client:
            resp = client.get("/?domain=sports")
        assert resp.status_code == 200, (
            f"Unknown domain filter must return 200, not an error; got {resp.status_code}"
        )


# ---------------------------------------------------------------------------
# 8. Acceptance cmd1 ('once') — primary criteria
# ---------------------------------------------------------------------------


class TestAcceptanceCmdOneGuard:
    """Acceptance cmd1: 'once' exits 0, stdout contains '## DUAL-LENS EVENTS' and 'spin_pct:'."""

    def test_cmd1_exits_zero(self, once_proc: subprocess.CompletedProcess) -> None:
        assert once_proc.returncode == 0, (
            f"Acceptance cmd1 ('once') exited {once_proc.returncode}; expected 0.\n"
            f"stderr tail:\n{once_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_cmd1_stdout_contains_dual_lens_events(self, once_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in once_stdout, (
            "Acceptance cmd1 stdout must contain '## DUAL-LENS EVENTS'.\n"
            "Left and right fixture articles must cluster into a dual-lens event.\n"
            f"stdout (first 2000):\n{once_stdout[:2000]}"
        )

    def test_cmd1_stdout_contains_spin_pct(self, once_stdout: str) -> None:
        assert "spin_pct:" in once_stdout, (
            "Acceptance cmd1 stdout must contain 'spin_pct:' per-article annotations.\n"
            f"stdout (first 2000):\n{once_stdout[:2000]}"
        )

    def test_cmd1_spin_pct_values_in_range(self, once_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", once_stdout)
        assert matches, (
            "No 'spin_pct: N.N%' patterns found in cmd1 stdout.\n"
            "The dual-lens block must contain at least one article with a spin annotation."
        )
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct {val}% is outside the valid [0, 100] range"
            )

    def test_cmd1_dual_lens_block_comes_after_domain_sections(
        self, once_stdout: str
    ) -> None:
        ai_idx = once_stdout.find("## AI")
        dual_idx = once_stdout.find("## DUAL-LENS EVENTS")
        assert ai_idx >= 0, "'## AI' section missing from cmd1 stdout"
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' block missing from cmd1 stdout"
        assert ai_idx < dual_idx, (
            "'## DUAL-LENS EVENTS' must appear AFTER '## AI' in cmd1 output"
        )

    def test_cmd1_spin_pct_appears_inside_dual_lens_block(self, once_stdout: str) -> None:
        dual_idx = once_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found in cmd1 stdout"
        block_after = once_stdout[dual_idx:]
        assert "spin_pct:" in block_after, (
            "'spin_pct:' must appear inside the '## DUAL-LENS EVENTS' block, not before it.\n"
            "Spin annotations belong to article bullets within the dual-lens render."
        )

    def test_cmd1_has_left_and_right_columns(self, once_stdout: str) -> None:
        assert "#### LEFT" in once_stdout, "'#### LEFT' column must appear in cmd1 stdout"
        assert "#### RIGHT" in once_stdout, "'#### RIGHT' column must appear in cmd1 stdout"

    def test_cmd1_spin_pct_has_decimal_format(self, once_stdout: str) -> None:
        """spin_pct must use one-decimal format (N.N%), not integer N%."""
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", once_stdout)
        assert matches, "No spin_pct values in cmd1 stdout"
        for raw in matches:
            assert "." in raw, (
                f"spin_pct {raw!r} must contain a decimal point (format :.1f)"
            )

    def test_cmd1_stdout_non_empty(self, once_stdout: str) -> None:
        assert once_stdout.strip(), "cmd1 ('once') must produce non-empty stdout"

    def test_cmd1_no_traceback(self, once_stdout: str) -> None:
        assert "Traceback" not in once_stdout, (
            "cmd1 stdout must not contain a Python Traceback"
        )


# ---------------------------------------------------------------------------
# 9. check_server.py and acceptance cmd1 pass simultaneously
# ---------------------------------------------------------------------------


class TestOmnibusGuard:
    """Both check_server.py and acceptance cmd1 must pass simultaneously."""

    def test_check_server_and_cmd1_both_exit_zero(
        self,
        check_server_result: subprocess.CompletedProcess,
        once_proc: subprocess.CompletedProcess,
    ) -> None:
        failures = []
        if check_server_result.returncode != 0:
            failures.append(
                f"check_server.py exited {check_server_result.returncode};\n"
                f"stderr: {check_server_result.stderr.decode(errors='replace')[-300:]}"
            )
        if once_proc.returncode != 0:
            failures.append(
                f"cmd1 ('once') exited {once_proc.returncode};\n"
                f"stderr: {once_proc.stderr.decode(errors='replace')[-300:]}"
            )
        assert not failures, "One or more commands failed:\n" + "\n".join(failures)

    def test_check_server_stdout_and_cmd1_stdout_are_distinct(
        self, check_server_stdout: str, once_stdout: str
    ) -> None:
        """check_server.py and cmd1 must produce different outputs — they are distinct commands."""
        assert check_server_stdout != once_stdout, (
            "check_server.py and 'once' must produce different stdout.\n"
            "check_server.py emits 'web-server-smoke: PASS'; 'once' emits a Markdown digest."
        )

    def test_check_server_pass_marker_and_cmd1_dual_lens_present(
        self, check_server_stdout: str, once_stdout: str
    ) -> None:
        """Together: check_server has 'web-server-smoke: PASS' and cmd1 has '## DUAL-LENS EVENTS'."""
        assert "web-server-smoke: PASS" in check_server_stdout, (
            "check_server.py must print 'web-server-smoke: PASS'"
        )
        assert "## DUAL-LENS EVENTS" in once_stdout, (
            "cmd1 ('once') must print '## DUAL-LENS EVENTS'"
        )

    def test_check_server_does_not_print_dual_lens_events_to_stdout(
        self, check_server_stdout: str
    ) -> None:
        """check_server.py checks the Flask app; it must not echo 'DUAL-LENS EVENTS' to stdout."""
        assert "DUAL-LENS EVENTS" not in check_server_stdout, (
            "check_server.py stdout must not contain 'DUAL-LENS EVENTS' (that belongs in cmd1).\n"
            "check_server.py only prints 'web-server-smoke: PASS'."
        )

    def test_no_recursive_pytest_in_this_file(self) -> None:
        """Structural guard: no line in this file invokes pytest as a subprocess argument."""
        source = Path(__file__).read_text(errors="replace")
        for lineno, line in enumerate(source.splitlines(), start=1):
            if line.strip().startswith("#"):
                continue
            if '"pytest"' in line and re.search(
                r"subprocess\.(run|Popen|call|check_output|check_call)", line
            ):
                pytest.fail(
                    f"Line {lineno} invokes pytest as a subprocess: {line.rstrip()!r}\n"
                    "Recursive pytest invocations hang the suite."
                )

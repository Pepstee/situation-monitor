"""Independent tests for check_server.py (via subprocess) and the acceptance file.

Acceptance criteria verified here:
  1. make_app + Flask test client with articles from rss_left.xml + rss_right.xml
     → HTTP 200 and 'Situation Monitor' in body.
  2. check_server.py as subprocess (SM_LLM_BACKEND=offline) → returncode 0,
     stdout contains 'web-server-smoke: PASS'.
  3. The acceptance file has exactly 4 non-comment lines and the 4th contains
     'check_server'.

Import isolation: no test module in this file imports from check_server.py.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from situation_monitor.dashboard import make_app
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.models import Article

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"


# ---------------------------------------------------------------------------
# Local-file RSS loader (mirrors the _LocalFileClient in __main__.py)
# ---------------------------------------------------------------------------

class _LocalFileClient:
    def get(self, url: str) -> bytes:
        return Path(url).read_bytes()


def _load_fixture_articles(*fixture_paths: str) -> list[Article]:
    """Parse one or more local RSS fixture files and return all articles."""
    client = _LocalFileClient()
    fetcher = RSSFetcher(client=client)
    articles: list[Article] = []
    for path in fixture_paths:
        articles.extend(fetcher.fetch(path))
    return articles


# ---------------------------------------------------------------------------
# 1. make_app with rss_left.xml + rss_right.xml
# ---------------------------------------------------------------------------

class TestMakeAppWithFixtureArticles:
    """Criterion 1: make_app + test client with fixture articles from left + right feeds."""

    def _make_client_and_articles(self):
        articles = _load_fixture_articles(
            str(FIXTURES / "rss_left.xml"),
            str(FIXTURES / "rss_right.xml"),
        )
        app = make_app(lambda: articles)
        return app.test_client(), articles

    def test_status_200(self):
        client, _ = self._make_client_and_articles()
        resp = client.get("/")
        assert resp.status_code == 200, f"Expected HTTP 200, got {resp.status_code}"

    def test_situation_monitor_in_body(self):
        client, _ = self._make_client_and_articles()
        body = client.get("/").data.decode()
        assert "Situation Monitor" in body

    def test_both_fixture_files_contribute_articles(self):
        """rss_left.xml and rss_right.xml each contain 1 article; both must appear."""
        articles = _load_fixture_articles(
            str(FIXTURES / "rss_left.xml"),
            str(FIXTURES / "rss_right.xml"),
        )
        assert len(articles) >= 2, (
            f"Expected at least 2 articles from the two fixtures, got {len(articles)}"
        )

    def test_left_article_title_in_response(self):
        """The left-fixture article title must appear in the rendered page."""
        articles = _load_fixture_articles(
            str(FIXTURES / "rss_left.xml"),
            str(FIXTURES / "rss_right.xml"),
        )
        app = make_app(lambda: articles)
        body = app.test_client().get("/").data.decode()
        left_title = "Government Climate Policy Reform Backed by Scientists"
        assert left_title in body, "Left-fixture article title missing from dashboard"

    def test_right_article_title_in_response(self):
        """The right-fixture article title must appear in the rendered page."""
        articles = _load_fixture_articles(
            str(FIXTURES / "rss_left.xml"),
            str(FIXTURES / "rss_right.xml"),
        )
        app = make_app(lambda: articles)
        body = app.test_client().get("/").data.decode()
        right_title = "Government Climate Policy Reform Threatens Economic Growth"
        assert right_title in body, "Right-fixture article title missing from dashboard"

    def test_get_callable_is_a_lambda(self):
        """make_app must accept any zero-argument callable, including a lambda."""
        articles = _load_fixture_articles(str(FIXTURES / "rss_left.xml"))
        app = make_app(lambda: articles)
        resp = app.test_client().get("/")
        assert resp.status_code == 200

    def test_empty_articles_lambda_returns_200(self):
        """Edge case: even with an empty article list the dashboard must return 200."""
        app = make_app(lambda: [])
        resp = app.test_client().get("/")
        assert resp.status_code == 200

    def test_story_count_matches_fixture_articles(self):
        """The page should reflect the correct count of stories from both fixtures."""
        articles = _load_fixture_articles(
            str(FIXTURES / "rss_left.xml"),
            str(FIXTURES / "rss_right.xml"),
        )
        app = make_app(lambda: articles)
        body = app.test_client().get("/").data.decode()
        count = len(articles)
        assert str(count) in body, (
            f"Expected story count '{count}' in response body"
        )

    def test_rss_left_xml_fixture_exists(self):
        assert (FIXTURES / "rss_left.xml").exists(), "rss_left.xml fixture is missing"

    def test_rss_right_xml_fixture_exists(self):
        assert (FIXTURES / "rss_right.xml").exists(), "rss_right.xml fixture is missing"


# ---------------------------------------------------------------------------
# 2. check_server.py subprocess (import isolation — never imported directly)
# ---------------------------------------------------------------------------

class TestCheckServerSubprocess:
    """Criterion 2: run check_server.py as a subprocess, verify exit code and output."""

    @pytest.fixture(scope="class")
    def check_server_result(self):
        env = os.environ.copy()
        env["SM_LLM_BACKEND"] = "offline"
        return subprocess.run(
            [sys.executable, str(CHECK_SERVER)],
            capture_output=True,
            timeout=60,
            cwd=PROJECT_ROOT,
            env=env,
        )

    def test_returncode_is_zero(self, check_server_result):
        proc = check_server_result
        stderr_text = proc.stderr.decode(errors="replace")
        assert proc.returncode == 0, (
            f"check_server.py exited {proc.returncode}. stderr: {stderr_text!r}"
        )

    def test_stdout_contains_pass_marker(self, check_server_result):
        stdout = check_server_result.stdout.decode(errors="replace")
        assert "web-server-smoke: PASS" in stdout, (
            f"'web-server-smoke: PASS' not in stdout. Got: {stdout!r}"
        )

    def test_stdout_is_nonempty(self, check_server_result):
        assert check_server_result.stdout.strip(), "check_server.py produced no stdout"

    def test_check_server_script_exists(self):
        assert CHECK_SERVER.exists(), f"check_server.py not found at {CHECK_SERVER}"

    def test_sm_llm_backend_offline_prevents_network(self, check_server_result):
        """With SM_LLM_BACKEND=offline the run must still exit 0 (no LLM needed)."""
        assert check_server_result.returncode == 0

    def test_no_import_from_check_server_in_this_module(self):
        """Import-isolation guard: check_server must never be directly imported."""
        import sys as _sys
        assert "check_server" not in _sys.modules, (
            "check_server was imported into the test process — import isolation violated"
        )


# ---------------------------------------------------------------------------
# 3. Acceptance file structure: 4 non-comment lines, 4th contains 'check_server'
# ---------------------------------------------------------------------------

class TestAcceptanceFileStructure:
    """Criterion 3: acceptance file has exactly 4 non-comment lines; 4th → check_server."""

    @pytest.fixture(scope="class")
    def non_comment_lines(self):
        text = ACCEPTANCE_FILE.read_text()
        return [
            line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

    def test_acceptance_file_exists(self):
        assert ACCEPTANCE_FILE.exists(), f"acceptance file not found at {ACCEPTANCE_FILE}"

    def test_acceptance_file_has_four_non_comment_lines(self):
        """Acceptance file must reference four commands (Cmd 1..4 or four _run calls)."""
        content = ACCEPTANCE_FILE.read_text()
        cmd_count = sum(1 for line in content.splitlines() if line.strip().startswith("# Cmd "))
        assert cmd_count >= 4, (
            f"Expected at least 4 '# Cmd N:' comment markers in acceptance file, found {cmd_count}.\n"
            "The acceptance script must run four commands: once, digest-dry-run, carrier, check_server."
        )

    def test_fourth_line_contains_check_server(self):
        """Acceptance file must reference check_server as the 4th command."""
        content = ACCEPTANCE_FILE.read_text()
        assert "check_server" in content, (
            "Acceptance file does not reference 'check_server'. "
            "The 4th command must invoke check_server.py."
        )

    def test_first_three_lines_do_not_contain_check_server(self, non_comment_lines):
        """check_server must appear only in the 4th line, not earlier."""
        for i, line in enumerate(non_comment_lines[:3]):
            assert "check_server" not in line, (
                f"'check_server' found unexpectedly in line {i + 1}: {line!r}"
            )

    def test_first_line_references_situation_monitor(self):
        """Acceptance file must invoke situation_monitor (cmd1 uses it)."""
        content = ACCEPTANCE_FILE.read_text()
        assert "situation_monitor" in content or "situation-monitor" in content, (
            "Acceptance file does not reference situation_monitor. "
            "All four commands must invoke 'python -m situation_monitor' or check_server."
        )

    def test_all_non_comment_lines_reference_sm_llm_backend_offline(self):
        """Acceptance file must set SM_LLM_BACKEND=offline for determinism."""
        content = ACCEPTANCE_FILE.read_text()
        assert "SM_LLM_BACKEND" in content, (
            "Acceptance file does not reference SM_LLM_BACKEND. "
            "The offline backend must be set for reproducible runs."
        )
        assert "offline" in content, (
            "Acceptance file does not set offline mode (SM_LLM_BACKEND=offline)."
        )

    def test_fourth_line_contains_python_invocation(self):
        """The check_server.py command must be invoked via Python."""
        content = ACCEPTANCE_FILE.read_text()
        # Find the line(s) referencing check_server and verify they invoke python
        check_server_lines = [l for l in content.splitlines() if "check_server" in l]
        assert check_server_lines, "No line references check_server in acceptance file"
        # At least one reference must use python/sys.executable (not bare shell)
        has_python = any(
            "python" in l.lower() or "sys.executable" in l or "subprocess" in l
            for l in check_server_lines
        )
        assert has_python, (
            f"check_server reference does not appear to use python/sys.executable:\n"
            + "\n".join(check_server_lines)
        )

    def test_no_blank_lines_counted_as_non_comment(self, non_comment_lines):
        """Blank lines must be excluded from the 4-line count."""
        for line in non_comment_lines:
            assert line.strip(), f"Blank line slipped through filter: {line!r}"

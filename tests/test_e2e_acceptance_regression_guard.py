"""End-to-end acceptance regression guard.

Acceptance criteria under test (verbatim from task spec):
  1. SM_LLM_BACKEND=offline python3 acceptance.py exits 0
     AND stdout contains 'DUAL_LENS: PASS'
     AND stdout contains 'MARKET: PASS'
  2. check_server.py exits 0 AND stdout contains 'web-server-smoke: PASS'
  3. No recursive pytest invocation in any test_*.py file (incl. this one)

Independent tester perspective: acceptance.py and check_server.py are the units
under test — they are NEVER mocked here.  Mocking would make the tests prove
nothing.  Every assertion CAN fail on a real regression:
  - 'DUAL_LENS: PASS' absent → criterion 1 fails.
  - 'MARKET: PASS' absent → criterion 1 fails.
  - 'web-server-smoke: PASS' absent → criterion 2 fails.
  - Either process exits non-zero → the corresponding criterion fails.

Design constraints:
  - No recursive pytest subprocess invocation (project memory: they hang the suite).
  - sys.executable is used for all subprocess calls (not 'python' or 'python3').
  - Module-scoped fixtures ensure each heavyweight subprocess runs exactly once.
  - SM_LLM_BACKEND=offline is passed explicitly on every subprocess invocation.
"""

from __future__ import annotations

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
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


def _offline_env(**extra: str) -> dict[str, str]:
    """Return env dict with SM_LLM_BACKEND forced to 'offline'."""
    return {**os.environ, "SM_LLM_BACKEND": "offline", **extra}


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixtures — each runs exactly once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_proc() -> subprocess.CompletedProcess:
    """Run: SM_LLM_BACKEND=offline sys.executable acceptance.py (cwd=project root)."""
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        timeout=300,
    )


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acceptance_stderr(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def check_server_proc() -> subprocess.CompletedProcess:
    """Run: SM_LLM_BACKEND=offline sys.executable check_server.py (cwd=project root)."""
    return subprocess.run(
        [sys.executable, str(CHECK_SERVER)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        timeout=60,
    )


@pytest.fixture(scope="module")
def check_server_stdout(check_server_proc: subprocess.CompletedProcess) -> str:
    return check_server_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def check_server_stderr(check_server_proc: subprocess.CompletedProcess) -> str:
    return check_server_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 1a: acceptance.py exits 0
# ---------------------------------------------------------------------------


class TestAcceptanceExitsZero:
    """acceptance.py must exit with returncode 0 when SM_LLM_BACKEND=offline."""

    def test_returncode_is_exactly_zero(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        stderr = acceptance_proc.stderr.decode(errors="replace")
        stdout_tail = acceptance_proc.stdout.decode(errors="replace")[-600:]
        assert acceptance_proc.returncode == 0, (
            f"acceptance.py exited {acceptance_proc.returncode} (expected 0).\n"
            f"stderr:\n{stderr[:2000]}\n"
            f"stdout (last 600 chars):\n{stdout_tail}"
        )

    def test_returncode_is_not_negative(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """A negative returncode means the process was killed by a signal."""
        assert acceptance_proc.returncode >= 0, (
            f"acceptance.py was killed by signal {-acceptance_proc.returncode}.\n"
            f"stderr:\n{acceptance_proc.stderr.decode(errors='replace')[:1000]}"
        )

    def test_no_unhandled_exception_in_stderr(self, acceptance_stderr: str) -> None:
        """An unhandled exception emits a Traceback — incompatible with exit 0."""
        assert "Traceback (most recent call last)" not in acceptance_stderr, (
            "acceptance.py raised an unhandled exception.\n"
            f"stderr:\n{acceptance_stderr[:2000]}"
        )

    def test_no_unhandled_exception_in_stdout(self, acceptance_stdout: str) -> None:
        """Tracebacks must not bleed into stdout either."""
        assert "Traceback (most recent call last)" not in acceptance_stdout, (
            "acceptance.py stdout contains a Python Traceback.\n"
            f"stdout (first 2000):\n{acceptance_stdout[:2000]}"
        )

    def test_no_live_api_error_in_stderr(self, acceptance_stderr: str) -> None:
        """SM_LLM_BACKEND=offline must suppress all live API calls."""
        live_api_markers = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "RateLimitError",
            "APIConnectionError",
        ]
        for marker in live_api_markers:
            assert marker not in acceptance_stderr, (
                f"acceptance stderr contains API error {marker!r} — "
                "the offline backend should prevent all live LLM calls.\n"
                f"stderr:\n{acceptance_stderr[:1000]}"
            )

    def test_stdout_is_non_empty(self, acceptance_stdout: str) -> None:
        """Empty stdout means the digest was never emitted — a silent failure."""
        assert acceptance_stdout.strip(), (
            "acceptance.py produced empty stdout; the 'once' digest must be emitted."
        )


# ---------------------------------------------------------------------------
# Criterion 1b: acceptance stdout contains 'DUAL_LENS: PASS'
# ---------------------------------------------------------------------------


class TestDualLensPassMarker:
    """acceptance stdout must contain the exact gate marker 'DUAL_LENS: PASS'."""

    def test_dual_lens_pass_present(self, acceptance_stdout: str) -> None:
        assert "DUAL_LENS: PASS" in acceptance_stdout, (
            "'DUAL_LENS: PASS' not found in acceptance.py stdout.\n"
            "This marker is emitted only when the dual-lens block is present and valid.\n"
            f"stdout (last 800 chars):\n{acceptance_stdout[-800:]}"
        )

    def test_dual_lens_fail_absent(self, acceptance_stdout: str) -> None:
        """'DUAL_LENS: FAIL' means the dual-lens section was missing — must never appear."""
        assert "DUAL_LENS: FAIL" not in acceptance_stdout, (
            "'DUAL_LENS: FAIL' found in acceptance.py stdout — dual-lens check failed.\n"
            f"stdout (last 800 chars):\n{acceptance_stdout[-800:]}"
        )

    def test_dual_lens_pass_on_its_own_line(self, acceptance_stdout: str) -> None:
        """The marker must be a complete line — not buried mid-sentence."""
        lines = acceptance_stdout.splitlines()
        assert any(line.strip() == "DUAL_LENS: PASS" for line in lines), (
            "'DUAL_LENS: PASS' must appear as a standalone line, not embedded in prose.\n"
            f"Lines containing 'DUAL_LENS':\n"
            + "\n".join(l for l in lines if "DUAL_LENS" in l)
        )

    def test_dual_lens_pass_format_exact(self, acceptance_stdout: str) -> None:
        """Format must be exactly 'DUAL_LENS: PASS' — colon, space, PASS (no trailing text)."""
        pattern = re.compile(r"^DUAL_LENS: PASS$", re.MULTILINE)
        assert pattern.search(acceptance_stdout), (
            "No line matching '^DUAL_LENS: PASS$' found.\n"
            "Format must be 'DUAL_LENS: PASS' (colon, space, PASS) with no extra trailing text.\n"
            f"Lines containing 'DUAL_LENS':\n"
            + "\n".join(
                l for l in acceptance_stdout.splitlines() if "DUAL_LENS" in l
            )
        )

    def test_dual_lens_events_section_precedes_marker(
        self, acceptance_stdout: str
    ) -> None:
        """The '## DUAL-LENS EVENTS' section must appear before the gate marker."""
        marker_pos = acceptance_stdout.find("DUAL_LENS: PASS")
        section_pos = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert section_pos != -1, (
            "'## DUAL-LENS EVENTS' section absent — acceptance cannot emit DUAL_LENS: PASS.\n"
            f"stdout (last 600):\n{acceptance_stdout[-600:]}"
        )
        assert section_pos < marker_pos, (
            "'## DUAL-LENS EVENTS' must appear BEFORE the 'DUAL_LENS: PASS' gate marker."
        )

    def test_left_and_right_lenses_present(self, acceptance_stdout: str) -> None:
        """Both '#### LEFT' and '#### RIGHT' must appear — a single lens is not dual-lens."""
        assert "#### LEFT" in acceptance_stdout, (
            "'#### LEFT' missing — dual-lens requires both left and right perspectives."
        )
        assert "#### RIGHT" in acceptance_stdout, (
            "'#### RIGHT' missing — dual-lens requires both left and right perspectives."
        )

    def test_spin_pct_annotation_present(self, acceptance_stdout: str) -> None:
        """The spin_pct annotation is required for dual-lens validity."""
        assert re.search(r"spin_pct:\s*[\d.]+%", acceptance_stdout), (
            "No 'spin_pct: <number>%' annotation found in acceptance stdout.\n"
            "The spin estimator must run for DUAL_LENS: PASS to be valid."
        )


# ---------------------------------------------------------------------------
# Criterion 1c: acceptance stdout contains 'MARKET: PASS'
# ---------------------------------------------------------------------------


class TestMarketPassMarker:
    """acceptance stdout must contain the exact gate marker 'MARKET: PASS'."""

    def test_market_pass_present(self, acceptance_stdout: str) -> None:
        assert "MARKET: PASS" in acceptance_stdout, (
            "'MARKET: PASS' not found in acceptance.py stdout.\n"
            "This marker is emitted only when '## MARKETS' appears in cmd1 output.\n"
            f"stdout (last 800 chars):\n{acceptance_stdout[-800:]}"
        )

    def test_market_fail_absent(self, acceptance_stdout: str) -> None:
        """'MARKET: FAIL' means the MARKETS section was missing — must never appear."""
        assert "MARKET: FAIL" not in acceptance_stdout, (
            "'MARKET: FAIL' found in acceptance.py stdout — market check failed.\n"
            f"stdout (last 800 chars):\n{acceptance_stdout[-800:]}"
        )

    def test_market_pass_on_its_own_line(self, acceptance_stdout: str) -> None:
        """The marker must be a complete line — not embedded mid-sentence."""
        lines = acceptance_stdout.splitlines()
        assert any(line.strip() == "MARKET: PASS" for line in lines), (
            "'MARKET: PASS' must appear as a standalone line, not embedded in prose.\n"
            f"Lines containing 'MARKET':\n"
            + "\n".join(l for l in lines if "MARKET" in l)
        )

    def test_market_pass_format_exact(self, acceptance_stdout: str) -> None:
        """Format must be exactly 'MARKET: PASS' with no trailing text."""
        pattern = re.compile(r"^MARKET: PASS$", re.MULTILINE)
        assert pattern.search(acceptance_stdout), (
            "No line matching '^MARKET: PASS$' found.\n"
            "Format must be 'MARKET: PASS' (colon, space, PASS) with no extra text.\n"
            f"Lines containing 'MARKET':\n"
            + "\n".join(
                l for l in acceptance_stdout.splitlines() if "MARKET" in l
            )
        )

    def test_markets_section_precedes_marker(self, acceptance_stdout: str) -> None:
        """The '## MARKETS' section must appear before the gate marker."""
        marker_pos = acceptance_stdout.find("MARKET: PASS")
        section_pos = acceptance_stdout.find("## MARKETS")
        assert section_pos != -1, (
            "'## MARKETS' section absent — acceptance cannot emit MARKET: PASS.\n"
            f"stdout (first 2000):\n{acceptance_stdout[:2000]}"
        )
        assert section_pos < marker_pos, (
            "'## MARKETS' must appear BEFORE the 'MARKET: PASS' gate marker."
        )

    def test_market_articles_in_output(self, acceptance_stdout: str) -> None:
        """The MARKETS section must contain at least one article title."""
        markets_start = acceptance_stdout.find("## MARKETS")
        if markets_start == -1:
            pytest.fail("'## MARKETS' section missing from acceptance stdout")
        # Find next section after MARKETS
        after_markets = acceptance_stdout[markets_start + len("## MARKETS"):]
        next_section = re.search(r"^## ", after_markets, re.MULTILINE)
        markets_block = after_markets[:next_section.start()] if next_section else after_markets
        assert markets_block.strip(), (
            "The '## MARKETS' section is empty — at least one article must appear."
        )


# ---------------------------------------------------------------------------
# Criterion 1d: gate markers ordering
# ---------------------------------------------------------------------------


class TestGateMarkersOrdering:
    """DUAL_LENS: PASS and MARKET: PASS must both appear and in the correct part of output."""

    def test_both_markers_present(self, acceptance_stdout: str) -> None:
        """Both markers must be present — one alone is insufficient for the gate."""
        has_dual = "DUAL_LENS: PASS" in acceptance_stdout
        has_market = "MARKET: PASS" in acceptance_stdout
        assert has_dual and has_market, (
            f"Gate requires both markers. "
            f"DUAL_LENS: PASS present={has_dual}, MARKET: PASS present={has_market}.\n"
            f"stdout (last 600):\n{acceptance_stdout[-600:]}"
        )

    def test_markers_appear_after_digest_content(self, acceptance_stdout: str) -> None:
        """Gate markers are printed at the end of acceptance.py, after the digest content."""
        dual_pos = acceptance_stdout.find("DUAL_LENS: PASS")
        market_pos = acceptance_stdout.find("MARKET: PASS")
        world_pos = acceptance_stdout.find("## WORLD")
        assert world_pos != -1, "## WORLD section must appear before gate markers"
        assert world_pos < dual_pos, "## WORLD must appear before 'DUAL_LENS: PASS'"
        assert world_pos < market_pos, "## WORLD must appear before 'MARKET: PASS'"

    def test_dual_lens_marker_precedes_or_equals_market_marker(
        self, acceptance_stdout: str
    ) -> None:
        """In acceptance.py, DUAL_LENS: PASS is printed before MARKET: PASS."""
        dual_pos = acceptance_stdout.find("DUAL_LENS: PASS")
        market_pos = acceptance_stdout.find("MARKET: PASS")
        assert dual_pos != -1, "'DUAL_LENS: PASS' missing"
        assert market_pos != -1, "'MARKET: PASS' missing"
        assert dual_pos <= market_pos, (
            "Expected 'DUAL_LENS: PASS' to appear before 'MARKET: PASS' in stdout.\n"
            f"DUAL_LENS: PASS at offset {dual_pos}, MARKET: PASS at offset {market_pos}."
        )

    def test_spin_pct_marker_between_dual_lens_and_market(
        self, acceptance_stdout: str
    ) -> None:
        """acceptance.py prints: DUAL_LENS: PASS, SPIN_PCT: N%, MARKET: PASS — in that order."""
        dual_pos = acceptance_stdout.find("DUAL_LENS: PASS")
        market_pos = acceptance_stdout.find("MARKET: PASS")
        spin_match = re.search(r"SPIN_PCT: [\d.]+%", acceptance_stdout)
        assert spin_match, "SPIN_PCT: <number>% gate marker missing from stdout"
        spin_pos = spin_match.start()
        assert dual_pos < spin_pos < market_pos, (
            "Expected order: DUAL_LENS: PASS, then SPIN_PCT: N%, then MARKET: PASS.\n"
            f"Offsets — DUAL_LENS: {dual_pos}, SPIN_PCT: {spin_pos}, MARKET: {market_pos}"
        )


# ---------------------------------------------------------------------------
# Criterion 2: check_server.py exits 0 + 'web-server-smoke: PASS'
# ---------------------------------------------------------------------------


class TestCheckServerExitsZero:
    """check_server.py must exit 0 when SM_LLM_BACKEND=offline."""

    def test_returncode_is_exactly_zero(
        self, check_server_proc: subprocess.CompletedProcess
    ) -> None:
        stderr = check_server_proc.stderr.decode(errors="replace")
        assert check_server_proc.returncode == 0, (
            f"check_server.py exited {check_server_proc.returncode} (expected 0).\n"
            f"stderr:\n{stderr[:2000]}"
        )

    def test_returncode_is_not_negative(
        self, check_server_proc: subprocess.CompletedProcess
    ) -> None:
        """Negative returncode means killed by a signal — not a clean exit."""
        assert check_server_proc.returncode >= 0, (
            f"check_server.py killed by signal {-check_server_proc.returncode}.\n"
            f"stderr:\n{check_server_proc.stderr.decode(errors='replace')[:500]}"
        )

    def test_no_unhandled_exception_in_stderr(self, check_server_stderr: str) -> None:
        assert "Traceback (most recent call last)" not in check_server_stderr, (
            "check_server.py raised an unhandled exception.\n"
            f"stderr:\n{check_server_stderr[:2000]}"
        )

    def test_stdout_is_non_empty(self, check_server_stdout: str) -> None:
        assert check_server_stdout.strip(), (
            "check_server.py produced empty stdout — smoke test never completed."
        )


class TestWebServerSmokePassMarker:
    """check_server.py stdout must contain 'web-server-smoke: PASS'."""

    def test_web_server_smoke_pass_present(self, check_server_stdout: str) -> None:
        assert "web-server-smoke: PASS" in check_server_stdout, (
            "'web-server-smoke: PASS' not found in check_server.py stdout.\n"
            f"stdout: {check_server_stdout!r}"
        )

    def test_web_server_smoke_fail_absent(self, check_server_stdout: str) -> None:
        """A FAIL marker means the Flask app did not return HTTP 200."""
        assert "web-server-smoke: FAIL" not in check_server_stdout, (
            "'web-server-smoke: FAIL' found — Flask app returned non-200 or assertion failed.\n"
            f"stdout: {check_server_stdout!r}"
        )

    def test_web_server_smoke_marker_on_its_own_line(
        self, check_server_stdout: str
    ) -> None:
        """The marker must be a complete line, not embedded mid-sentence."""
        lines = check_server_stdout.splitlines()
        assert any(line.strip() == "web-server-smoke: PASS" for line in lines), (
            "'web-server-smoke: PASS' must be a standalone line.\n"
            f"Lines containing 'web-server-smoke':\n"
            + "\n".join(l for l in lines if "web-server-smoke" in l)
        )

    def test_web_server_smoke_format_exact(self, check_server_stdout: str) -> None:
        """Format must be exactly 'web-server-smoke: PASS' — colon, space, PASS."""
        pattern = re.compile(r"^web-server-smoke: PASS$", re.MULTILINE)
        assert pattern.search(check_server_stdout), (
            "No line matching '^web-server-smoke: PASS$' found in check_server.py stdout.\n"
            f"stdout: {check_server_stdout!r}"
        )

    def test_offline_backend_still_passes(
        self, check_server_proc: subprocess.CompletedProcess, check_server_stdout: str
    ) -> None:
        """check_server.py must work without a live LLM (offline backend suffices)."""
        assert check_server_proc.returncode == 0, (
            "check_server.py failed with SM_LLM_BACKEND=offline — "
            "the offline backend must be sufficient for the Flask smoke test."
        )
        assert "web-server-smoke: PASS" in check_server_stdout


# ---------------------------------------------------------------------------
# Criterion 3: no recursive pytest invocation in any test_*.py file
# ---------------------------------------------------------------------------


class TestNoRecursivePytestInvocation:
    """No test_*.py file may spawn pytest as a subprocess — this hangs the suite.

    Evidence is structural: we scan every test file for subprocess calls whose
    args include 'pytest'.  Passing this test IS the evidence that criterion 3
    is satisfied — no recursive subprocess invocation needed.
    """

    _PYTEST_SUBPROCESS_PATTERN = re.compile(
        r'''\bsubprocess\.(run|Popen|call|check_output|check_call)\b'''
    )
    _PYTEST_ARG_PATTERN = re.compile(r'''["']pytest["']''')

    def _collect_recursive_pytest_calls(self) -> list[str]:
        test_dir = PROJECT_ROOT / "tests"
        bad: list[str] = []
        for tf in sorted(test_dir.glob("test_*.py")):
            content = tf.read_text(errors="replace")
            for lineno, raw in enumerate(content.splitlines(), start=1):
                stripped = raw.strip()
                if stripped.startswith("#"):
                    continue
                if self._PYTEST_SUBPROCESS_PATTERN.search(raw) and self._PYTEST_ARG_PATTERN.search(raw):
                    bad.append(f"{tf.name}:{lineno}: {raw.rstrip()}")
        return bad

    def test_no_test_file_spawns_pytest_subprocess(self) -> None:
        """Recursive pytest subprocess calls hang the suite — zero tolerance."""
        bad = self._collect_recursive_pytest_calls()
        assert not bad, (
            "Recursive pytest subprocess calls found — these hang the entire test suite:\n"
            + "\n".join(bad[:15])
        )

    def test_this_file_does_not_spawn_pytest_subprocess(self) -> None:
        """Self-check: this test file must not contain a recursive pytest call."""
        this_file = Path(__file__).read_text(errors="replace")
        for lineno, raw in enumerate(this_file.splitlines(), start=1):
            stripped = raw.strip()
            if stripped.startswith("#"):
                continue
            if (
                self._PYTEST_SUBPROCESS_PATTERN.search(raw)
                and self._PYTEST_ARG_PATTERN.search(raw)
            ):
                pytest.fail(
                    f"This file contains a recursive pytest subprocess call at line {lineno}:\n"
                    f"  {raw.rstrip()}"
                )

    def test_acceptance_py_does_not_spawn_pytest(self) -> None:
        """The acceptance script itself must not invoke pytest — that would be recursive."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "pytest" not in content, (
            "acceptance.py must not invoke pytest — recursive pytest calls hang the suite."
        )

    def test_check_server_py_does_not_spawn_pytest(self) -> None:
        """check_server.py must not invoke pytest either."""
        content = CHECK_SERVER.read_text(errors="replace")
        assert "pytest" not in content, (
            "check_server.py must not invoke pytest — recursive pytest calls hang the suite."
        )

    def test_test_corpus_is_non_trivial(self) -> None:
        """A near-empty suite exits 0 vacuously — the suite must be substantive."""
        test_files = list((PROJECT_ROOT / "tests").glob("test_*.py"))
        assert len(test_files) >= 10, (
            f"Expected ≥10 test_*.py files; found {len(test_files)}. "
            "A near-empty suite exits 0 without verifying anything."
        )


# ---------------------------------------------------------------------------
# Structural prerequisites: files and package must exist before any subprocess
# ---------------------------------------------------------------------------


class TestPrerequisites:
    """Guard: if key files are missing, every other test fails before it starts."""

    def test_acceptance_py_exists(self) -> None:
        assert ACCEPTANCE_PY.exists(), f"acceptance.py not found at {ACCEPTANCE_PY}"

    def test_check_server_py_exists(self) -> None:
        assert CHECK_SERVER.exists(), f"check_server.py not found at {CHECK_SERVER}"

    def test_fixtures_dir_exists(self) -> None:
        assert FIXTURES.is_dir(), f"tests/fixtures/ missing at {FIXTURES}"

    def test_acceptance_source_defs_fixture_exists(self) -> None:
        p = FIXTURES / "acceptance_source_defs.json"
        assert p.exists(), f"acceptance_source_defs.json missing at {p}"

    def test_rss_left_fixture_exists(self) -> None:
        p = FIXTURES / "rss_left.xml"
        assert p.exists(), f"rss_left.xml missing at {p}"

    def test_rss_right_fixture_exists(self) -> None:
        p = FIXTURES / "rss_right.xml"
        assert p.exists(), f"rss_right.xml missing at {p}"

    def test_rss_markets_fixture_exists(self) -> None:
        p = FIXTURES / "rss_markets.xml"
        assert p.exists(), f"rss_markets.xml missing at {p}"

    def test_situation_monitor_package_importable(self) -> None:
        """Import failure crashes every acceptance subprocess — verify early."""
        try:
            import situation_monitor  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"situation_monitor not importable: {exc}")

    def test_acceptance_py_uses_sys_executable(self) -> None:
        """acceptance.py must use sys.executable — bare 'python3' is missing on some platforms."""
        content = ACCEPTANCE_PY.read_text()
        assert "sys.executable" in content, (
            "acceptance.py must use sys.executable for subprocess calls.\n"
            "Bare 'python' or 'python3' is absent on macOS and some CI environments."
        )

    def test_acceptance_py_syntax_valid(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c",
             f"import ast; ast.parse(open({str(ACCEPTANCE_PY)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "acceptance.py has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_check_server_py_syntax_valid(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c",
             f"import ast; ast.parse(open({str(CHECK_SERVER)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "check_server.py has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_acceptance_py_sets_offline_backend(self) -> None:
        """acceptance.py must propagate SM_LLM_BACKEND=offline to sub-subprocesses."""
        content = ACCEPTANCE_PY.read_text()
        assert "SM_LLM_BACKEND" in content and "offline" in content, (
            "acceptance.py must set SM_LLM_BACKEND=offline in subprocess env.\n"
            "Without this, sub-commands attempt live LLM calls and fail in CI."
        )

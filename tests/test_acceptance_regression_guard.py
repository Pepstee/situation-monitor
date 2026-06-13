"""Full regression guard: pytest -x + evidence.py subprocess contracts.

Acceptance criteria under test (each assertion can fail on a real regression):
  1. ``pytest -x`` exits 0 — full test suite passes with fail-fast.
  2. ``evidence.py`` exits 0 — evidence generation pipeline succeeds end-to-end.
  3. ``evidence.txt`` contains the literal ``DUAL_LENS: PASS``.
  4. ``evidence.txt`` contains at least one line with a ``%`` character (SPIN_PCT).
  5. ``evidence.txt`` contains the literal ``MARKET: PASS``.
  6. ``verdict_brief.txt`` line 1 is exactly ``DUAL_LENS: Y``.
  7. ``verdict_brief.txt`` line 2 is exactly ``SPIN_PCT: Y``.
  8. ``verdict_brief.txt`` line 3 is exactly ``MARKET: Y``.

Design note: to prevent infinite subprocess recursion, the meta-pytest call
excludes this file and all other known files that also spawn a pytest subprocess.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
EVIDENCE_SCRIPT = PROJECT_ROOT / "evidence.py"
EVIDENCE_FILE = PROJECT_ROOT / "evidence.txt"
VERDICT_FILE = PROJECT_ROOT / "verdict_brief.txt"

THIS_FILE = Path(__file__).name

# All test files that spawn a pytest subprocess — exclude all to break recursion.
_PYTEST_META_FILES = [
    THIS_FILE,
    "test_regression_guard.py",
    "test_pytest_acceptance_regression.py",
    "test_independent_subprocess_guard.py",
]


def _stub_env() -> dict[str, str]:
    """Environment that forces stub LLM and fixture RSS — no network calls."""
    return {
        **os.environ,
        "SM_LLM_BACKEND": "stub",
        "SM_SOURCES": "tests/fixtures/rss_sample.xml",
    }


# ---------------------------------------------------------------------------
# Module-scoped fixtures — each subprocess runs exactly once per session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pytest_x_result() -> subprocess.CompletedProcess:
    """Run ``pytest -x`` excluding all recursive meta-test files."""
    ignore_flags = [f"--ignore=tests/{f}" for f in _PYTEST_META_FILES]
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", *ignore_flags, "-x", "-q", "--tb=short"],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_stub_env(),
        timeout=300,
    )


@pytest.fixture(scope="module")
def evidence_result() -> subprocess.CompletedProcess:
    """Run evidence.py and capture stdout/stderr and returncode."""
    return subprocess.run(
        [sys.executable, str(EVIDENCE_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=PROJECT_ROOT,
    )


@pytest.fixture(scope="module")
def evidence_text(evidence_result) -> str:
    """Return the content of evidence.txt written by evidence.py."""
    assert EVIDENCE_FILE.exists(), (
        "evidence.txt must exist after evidence.py runs — file was not produced"
    )
    return EVIDENCE_FILE.read_text()


@pytest.fixture(scope="module")
def evidence_lines(evidence_text) -> list[str]:
    """Non-empty lines of evidence.txt, preserving order."""
    return [line for line in evidence_text.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def verdict_text(evidence_result) -> str:
    """Return the content of verdict_brief.txt written by evidence.py."""
    assert VERDICT_FILE.exists(), (
        "verdict_brief.txt must exist after evidence.py runs — file was not produced"
    )
    return VERDICT_FILE.read_text()


@pytest.fixture(scope="module")
def verdict_lines(verdict_text) -> list[str]:
    """Non-empty lines of verdict_brief.txt, preserving order."""
    return [line for line in verdict_text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# 1. pytest -x exits 0
# ---------------------------------------------------------------------------


class TestPytestXExitsZero:
    """``pytest -x tests/`` must exit 0 — the full suite passes with no failures."""

    def test_returncode_is_zero(self, pytest_x_result: subprocess.CompletedProcess) -> None:
        assert pytest_x_result.returncode == 0, (
            f"pytest -x exited {pytest_x_result.returncode}; expected 0.\n"
            f"stdout tail:\n{pytest_x_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"stderr tail:\n{pytest_x_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_output_contains_passed_summary(self, pytest_x_result: subprocess.CompletedProcess) -> None:
        """pytest -q must emit 'N passed' confirming tests ran and passed."""
        output = pytest_x_result.stdout.decode(errors="replace")
        assert re.search(r"\d+ passed", output), (
            f"pytest -x output does not contain 'N passed'; no tests may have run.\n"
            f"Output tail:\n{output[-1000:]}"
        )

    def test_no_failures_in_output(self, pytest_x_result: subprocess.CompletedProcess) -> None:
        output = pytest_x_result.stdout.decode(errors="replace")
        assert "failed" not in output.lower() or pytest_x_result.returncode == 0, (
            f"'failed' keyword found in pytest -x output.\nTail:\n{output[-2000:]}"
        )

    def test_no_collection_errors(self, pytest_x_result: subprocess.CompletedProcess) -> None:
        combined = (
            pytest_x_result.stdout.decode(errors="replace")
            + pytest_x_result.stderr.decode(errors="replace")
        )
        assert "ERROR collecting" not in combined, (
            f"Collection errors in pytest -x output:\n{combined[:2000]}"
        )

    def test_no_import_errors(self, pytest_x_result: subprocess.CompletedProcess) -> None:
        combined = (
            pytest_x_result.stdout.decode(errors="replace")
            + pytest_x_result.stderr.decode(errors="replace")
        )
        assert "ImportError" not in combined, (
            f"ImportError in pytest -x output:\n{combined[:2000]}"
        )

    def test_collects_at_least_fifty_tests(self, pytest_x_result: subprocess.CompletedProcess) -> None:
        """A count below 50 signals a misconfigured conftest or broken collection."""
        output = pytest_x_result.stdout.decode(errors="replace")
        matches = re.findall(r"(\d+) passed", output)
        count = int(matches[-1]) if matches else 0
        assert count >= 50, (
            f"Expected at least 50 tests to pass; only {count} passed.\n"
            f"Output tail:\n{output[-1000:]}"
        )


# ---------------------------------------------------------------------------
# 2. evidence.py exits 0
# ---------------------------------------------------------------------------


class TestEvidenceScriptExitsZero:
    """evidence.py must exit 0 and produce both output files without errors."""

    def test_evidence_script_exists(self) -> None:
        assert EVIDENCE_SCRIPT.exists(), (
            f"evidence.py not found at {EVIDENCE_SCRIPT}"
        )

    def test_returncode_is_zero(self, evidence_result: subprocess.CompletedProcess) -> None:
        assert evidence_result.returncode == 0, (
            f"evidence.py exited {evidence_result.returncode}; expected 0.\n"
            f"stderr:\n{evidence_result.stderr}"
        )

    def test_produces_evidence_txt(self, evidence_result: subprocess.CompletedProcess) -> None:
        assert EVIDENCE_FILE.exists(), (
            "evidence.py did not produce evidence.txt"
        )

    def test_produces_verdict_brief_txt(self, evidence_result: subprocess.CompletedProcess) -> None:
        assert VERDICT_FILE.exists(), (
            "evidence.py did not produce verdict_brief.txt"
        )

    def test_stdout_mentions_wrote_evidence(self, evidence_result: subprocess.CompletedProcess) -> None:
        assert "Wrote" in evidence_result.stdout, (
            f"evidence.py stdout did not contain 'Wrote':\n{evidence_result.stdout!r}"
        )

    def test_no_traceback_in_stderr(self, evidence_result: subprocess.CompletedProcess) -> None:
        assert "Traceback" not in evidence_result.stderr, (
            f"evidence.py stderr contains a traceback:\n{evidence_result.stderr[:2000]}"
        )

    def test_no_traceback_in_stdout(self, evidence_result: subprocess.CompletedProcess) -> None:
        assert "Traceback" not in evidence_result.stdout, (
            f"evidence.py stdout contains a traceback:\n{evidence_result.stdout[:2000]}"
        )

    def test_stdout_echoes_dual_lens_label(self, evidence_result: subprocess.CompletedProcess) -> None:
        assert "DUAL_LENS:" in evidence_result.stdout, (
            "evidence.py stdout must echo the DUAL_LENS: line"
        )

    def test_stdout_echoes_market_label(self, evidence_result: subprocess.CompletedProcess) -> None:
        assert "MARKET:" in evidence_result.stdout, (
            "evidence.py stdout must echo the MARKET: line"
        )


# ---------------------------------------------------------------------------
# 3. evidence.txt contains DUAL_LENS: PASS
# ---------------------------------------------------------------------------


class TestEvidenceFileDualLensPass:
    """evidence.txt must contain the literal string 'DUAL_LENS: PASS'."""

    def test_dual_lens_line_present(self, evidence_text: str) -> None:
        assert "DUAL_LENS:" in evidence_text, (
            "evidence.txt must contain a DUAL_LENS: line"
        )

    def test_dual_lens_pass_literal(self, evidence_text: str) -> None:
        assert "DUAL_LENS: PASS" in evidence_text, (
            "evidence.txt must contain the literal 'DUAL_LENS: PASS'.\n"
            "This proves the dual-lens pipeline ingested articles from both left and right "
            "lean buckets."
        )

    def test_dual_lens_value_is_pass_not_fail(self, evidence_lines: list[str]) -> None:
        dual = [l for l in evidence_lines if l.startswith("DUAL_LENS:")]
        assert dual, "No DUAL_LENS: line found in evidence.txt"
        value = dual[0].split(":", 1)[1].strip()
        assert value == "PASS", (
            f"DUAL_LENS value must be 'PASS'; got {value!r}.\n"
            f"Both left and right lean buckets must be populated."
        )

    def test_dual_lens_line_is_first(self, evidence_lines: list[str]) -> None:
        """DUAL_LENS: must appear as the first line of evidence.txt."""
        assert evidence_lines, "evidence.txt is empty"
        assert evidence_lines[0].startswith("DUAL_LENS:"), (
            f"evidence.txt line 1 must start with 'DUAL_LENS:'; got {evidence_lines[0]!r}"
        )


# ---------------------------------------------------------------------------
# 4. evidence.txt contains a line with %
# ---------------------------------------------------------------------------


class TestEvidenceFilePercentLine:
    """evidence.txt must contain at least one line with a '%' character (SPIN_PCT)."""

    def test_any_line_contains_percent(self, evidence_lines: list[str]) -> None:
        pct_lines = [l for l in evidence_lines if "%" in l]
        assert pct_lines, (
            "evidence.txt must contain at least one line with '%' (expected from SPIN_PCT)"
        )

    def test_spin_pct_line_present(self, evidence_text: str) -> None:
        assert "SPIN_PCT:" in evidence_text, (
            "evidence.txt must contain a SPIN_PCT: line"
        )

    def test_spin_pct_value_contains_percent(self, evidence_lines: list[str]) -> None:
        spin = [l for l in evidence_lines if l.startswith("SPIN_PCT:")]
        assert spin, "No SPIN_PCT: line found in evidence.txt"
        assert "%" in spin[0], (
            f"SPIN_PCT line must contain '%'; got: {spin[0]!r}"
        )

    def test_spin_pct_value_is_integer_percent(self, evidence_lines: list[str]) -> None:
        """SPIN_PCT value must match the format '<integer>%'."""
        spin = [l for l in evidence_lines if l.startswith("SPIN_PCT:")]
        assert spin, "No SPIN_PCT: line found in evidence.txt"
        value = spin[0].split(":", 1)[1].strip()
        assert re.fullmatch(r"\d+%", value), (
            f"SPIN_PCT value must be '<integer>%' (e.g. '50%'); got {value!r}"
        )

    def test_spin_pct_integer_in_valid_range(self, evidence_lines: list[str]) -> None:
        spin = [l for l in evidence_lines if l.startswith("SPIN_PCT:")]
        assert spin, "No SPIN_PCT: line found"
        value = spin[0].split(":", 1)[1].strip().rstrip("%")
        pct = int(value)
        assert 0 <= pct <= 100, (
            f"SPIN_PCT value {pct}% is outside the valid [0, 100] range"
        )


# ---------------------------------------------------------------------------
# 5. evidence.txt contains MARKET: PASS
# ---------------------------------------------------------------------------


class TestEvidenceFileMarketPass:
    """evidence.txt must contain the literal string 'MARKET: PASS'."""

    def test_market_line_present(self, evidence_text: str) -> None:
        assert "MARKET:" in evidence_text, (
            "evidence.txt must contain a MARKET: line"
        )

    def test_market_pass_literal(self, evidence_text: str) -> None:
        assert "MARKET: PASS" in evidence_text, (
            "evidence.txt must contain the literal 'MARKET: PASS'.\n"
            "This proves fetch_practical_movers() returned at least one mover."
        )

    def test_market_value_is_pass_not_fail(self, evidence_lines: list[str]) -> None:
        market = [l for l in evidence_lines if l.startswith("MARKET:")]
        assert market, "No MARKET: line found in evidence.txt"
        value = market[0].split(":", 1)[1].strip()
        assert value == "PASS", (
            f"MARKET value must be 'PASS'; got {value!r}.\n"
            f"fetch_practical_movers() must return at least one PracticalMover."
        )


# ---------------------------------------------------------------------------
# 6–8. verdict_brief.txt: three lines, each ending with 'Y'
# ---------------------------------------------------------------------------


class TestVerdictBriefTxt:
    """verdict_brief.txt must contain exactly: DUAL_LENS: Y / SPIN_PCT: Y / MARKET: Y."""

    def test_verdict_file_exists(self) -> None:
        assert VERDICT_FILE.exists(), (
            f"verdict_brief.txt not found at {VERDICT_FILE}"
        )

    def test_verdict_has_at_least_three_lines(self, verdict_lines: list[str]) -> None:
        assert len(verdict_lines) >= 3, (
            f"verdict_brief.txt must have at least 3 non-empty lines; "
            f"got {len(verdict_lines)}: {verdict_lines}"
        )

    def test_verdict_line1_is_dual_lens_y(self, verdict_lines: list[str]) -> None:
        """Line 1 must be exactly 'DUAL_LENS: Y'."""
        assert len(verdict_lines) >= 1, "verdict_brief.txt is empty"
        assert verdict_lines[0] == "DUAL_LENS: Y", (
            f"verdict_brief.txt line 1 must be 'DUAL_LENS: Y'; got {verdict_lines[0]!r}"
        )

    def test_verdict_line2_is_spin_pct_y(self, verdict_lines: list[str]) -> None:
        """Line 2 must be exactly 'SPIN_PCT: Y'."""
        assert len(verdict_lines) >= 2, "verdict_brief.txt has fewer than 2 lines"
        assert verdict_lines[1] == "SPIN_PCT: Y", (
            f"verdict_brief.txt line 2 must be 'SPIN_PCT: Y'; got {verdict_lines[1]!r}"
        )

    def test_verdict_line3_is_market_y(self, verdict_lines: list[str]) -> None:
        """Line 3 must be exactly 'MARKET: Y'."""
        assert len(verdict_lines) >= 3, "verdict_brief.txt has fewer than 3 lines"
        assert verdict_lines[2] == "MARKET: Y", (
            f"verdict_brief.txt line 3 must be 'MARKET: Y'; got {verdict_lines[2]!r}"
        )

    def test_all_three_lines_match_expected(self, verdict_lines: list[str]) -> None:
        """Composite: all three lines correct in a single check."""
        assert len(verdict_lines) >= 3, (
            f"verdict_brief.txt must have at least 3 lines; got {len(verdict_lines)}"
        )
        expected = ["DUAL_LENS: Y", "SPIN_PCT: Y", "MARKET: Y"]
        for i, exp in enumerate(expected):
            assert verdict_lines[i] == exp, (
                f"verdict_brief.txt line {i + 1}: expected {exp!r}, got {verdict_lines[i]!r}"
            )

    def test_verdict_values_are_y_not_satisfactory(self, verdict_lines: list[str]) -> None:
        """Lines must use compact 'Y' indicator, not verbose 'SATISFACTORY'."""
        for i, line in enumerate(verdict_lines[:3]):
            assert "SATISFACTORY" not in line, (
                f"verdict_brief.txt line {i + 1} must use 'Y' not 'SATISFACTORY'; "
                f"got {line!r}"
            )

    def test_verdict_values_are_y_not_n(self, verdict_lines: list[str]) -> None:
        """All three lines must carry 'Y' (pass) status, not 'N' (fail)."""
        for i, line in enumerate(verdict_lines[:3]):
            parts = line.split(":", 1)
            assert len(parts) == 2, f"Line {i + 1} missing ':': {line!r}"
            value = parts[1].strip()
            assert value == "Y", (
                f"verdict_brief.txt line {i + 1} value must be 'Y'; got {value!r}"
            )

    def test_verdict_dual_lens_key_on_line1(self, verdict_lines: list[str]) -> None:
        assert len(verdict_lines) >= 1, "verdict_brief.txt is empty"
        key = verdict_lines[0].split(":", 1)[0].strip()
        assert key == "DUAL_LENS", (
            f"verdict_brief.txt line 1 key must be 'DUAL_LENS'; got {key!r}"
        )

    def test_verdict_spin_pct_key_on_line2(self, verdict_lines: list[str]) -> None:
        assert len(verdict_lines) >= 2, "verdict_brief.txt has fewer than 2 lines"
        key = verdict_lines[1].split(":", 1)[0].strip()
        assert key == "SPIN_PCT", (
            f"verdict_brief.txt line 2 key must be 'SPIN_PCT'; got {key!r}"
        )

    def test_verdict_market_key_on_line3(self, verdict_lines: list[str]) -> None:
        assert len(verdict_lines) >= 3, "verdict_brief.txt has fewer than 3 lines"
        key = verdict_lines[2].split(":", 1)[0].strip()
        assert key == "MARKET", (
            f"verdict_brief.txt line 3 key must be 'MARKET'; got {key!r}"
        )

    def test_verdict_file_ends_with_newline(self, verdict_text: str) -> None:
        assert verdict_text.endswith("\n"), (
            "verdict_brief.txt must end with a newline character"
        )

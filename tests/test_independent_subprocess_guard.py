"""Independent regression guard after repairs.

Verifies the four acceptance criteria via two separate subprocess calls —
one for pytest, one for the acceptance script.  These tests are independent
of the builder's own test files: they check *output contracts*, not
implementation internals, and every assertion is capable of failing on a
real regression.

Acceptance criteria under test:
  1. ``pytest tests/`` exits 0 — all tests collected and passing.
  2. Acceptance script exits 0 — both subcommands succeed end-to-end.
  3. Acceptance stdout contains both lens column markers:
       ``#### LEFT``  and  ``#### RIGHT``
  4. Acceptance stdout contains a numeric spin percentage:
       ``spin_pct: N.N%`` (must be parseable as a float in [0, 100]).

Design note: to prevent infinite subprocess recursion, the meta-pytest call
excludes both this file and ``test_pytest_acceptance_regression.py`` (which
also spawns a pytest subprocess).  Excluding those two files is the minimal
cut that breaks every possible cycle while still running the full test suite.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"
THIS_FILE = Path(__file__).name
# Also exclude the sibling meta-test to prevent subprocess nesting → infinite recursion.
OTHER_META_TEST = "test_pytest_acceptance_regression.py"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _stub_env() -> dict[str, str]:
    """Force stub LLM backend and fixture sources — no live network calls."""
    return {
        **os.environ,
        "SM_LLM_BACKEND": "stub",
        "SM_SOURCES": "tests/fixtures/rss_sample.xml",
    }


# ---------------------------------------------------------------------------
# Shared fixtures (module-scoped to run each subprocess exactly once)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pytest_result() -> subprocess.CompletedProcess:
    """Run pytest as a subprocess, excluding recursive meta-test files."""
    return subprocess.run(
        [
            sys.executable,
            "-m", "pytest",
            "tests/",
            f"--ignore=tests/{THIS_FILE}",
            f"--ignore=tests/{OTHER_META_TEST}",
            "-q",
            "--tb=short",
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_stub_env(),
        timeout=300,
    )


@pytest.fixture(scope="module")
def acceptance_result() -> subprocess.CompletedProcess:
    """Run the acceptance script verbatim and capture both stdout and returncode."""
    cmd = ACCEPTANCE_FILE.read_text().strip()
    return subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        timeout=120,
        cwd=PROJECT_ROOT,
    )


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_result: subprocess.CompletedProcess) -> str:
    return acceptance_result.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# 1. pytest subprocess: exits 0
# ---------------------------------------------------------------------------


class TestPytestSubprocessExitsZero:
    """The full test suite must pass when run as a fresh subprocess."""

    def test_pytest_returncode_is_zero(self, pytest_result: subprocess.CompletedProcess) -> None:
        assert pytest_result.returncode == 0, (
            f"pytest subprocess exited {pytest_result.returncode}; expected 0.\n"
            f"--- stdout tail ---\n"
            f"{pytest_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"--- stderr tail ---\n"
            f"{pytest_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_pytest_collects_at_least_one_test(self, pytest_result: subprocess.CompletedProcess) -> None:
        """A zero returncode with zero collected tests would be a silent misconfiguration."""
        output = pytest_result.stdout.decode(errors="replace")
        # pytest -q summary line: "N passed" or "N passed, M warnings"
        assert re.search(r"\d+ passed", output), (
            f"pytest output does not contain 'N passed' — no tests may have run.\n"
            f"Output tail:\n{output[-1000:]}"
        )

    def test_pytest_no_failures_in_output(self, pytest_result: subprocess.CompletedProcess) -> None:
        output = pytest_result.stdout.decode(errors="replace")
        assert "failed" not in output.lower() or pytest_result.returncode == 0, (
            f"'failed' found in pytest output.\nOutput tail:\n{output[-2000:]}"
        )

    def test_pytest_no_collection_errors(self, pytest_result: subprocess.CompletedProcess) -> None:
        output = (
            pytest_result.stdout.decode(errors="replace")
            + pytest_result.stderr.decode(errors="replace")
        )
        assert "ERROR collecting" not in output, (
            f"Collection errors detected in pytest output.\nOutput:\n{output[:2000]}"
        )


# ---------------------------------------------------------------------------
# 2. Acceptance subprocess: exits 0
# ---------------------------------------------------------------------------


class TestAcceptanceSubprocessExitsZero:
    """The acceptance script must exit 0 with both subcommands succeeding."""

    def test_acceptance_returncode_is_zero(self, acceptance_result: subprocess.CompletedProcess) -> None:
        assert acceptance_result.returncode == 0, (
            f"Acceptance script exited {acceptance_result.returncode}; expected 0.\n"
            f"Both 'once' and 'digest-dry-run' subcommands must succeed.\n"
            f"stdout: {acceptance_result.stdout.decode(errors='replace')[:2000]}\n"
            f"stderr: {acceptance_result.stderr.decode(errors='replace')[:500]}"
        )

    def test_acceptance_file_exists(self) -> None:
        assert ACCEPTANCE_FILE.exists(), (
            f"acceptance file not found at {ACCEPTANCE_FILE}"
        )

    def test_acceptance_file_non_empty(self) -> None:
        assert ACCEPTANCE_FILE.read_text().strip(), "acceptance file must not be empty"

    def test_acceptance_references_situation_monitor(self) -> None:
        assert "situation_monitor" in ACCEPTANCE_FILE.read_text(), (
            "acceptance file must reference the situation_monitor module"
        )

    def test_acceptance_references_once_subcommand(self) -> None:
        assert " once " in ACCEPTANCE_FILE.read_text(), (
            "acceptance file must invoke the 'once' subcommand"
        )

    def test_acceptance_references_digest_dry_run(self) -> None:
        assert "digest-dry-run" in ACCEPTANCE_FILE.read_text(), (
            "acceptance file must invoke the 'digest-dry-run' subcommand"
        )

    def test_acceptance_no_traceback_in_stdout(self, acceptance_stdout: str) -> None:
        assert "Traceback" not in acceptance_stdout, (
            "Acceptance stdout must not contain a Python traceback"
        )

    def test_acceptance_produces_situation_monitor_heading(self, acceptance_stdout: str) -> None:
        assert "Situation Monitor" in acceptance_stdout, (
            "Acceptance stdout must contain 'Situation Monitor' heading"
        )


# ---------------------------------------------------------------------------
# 3. Acceptance stdout: both lens column markers present
# ---------------------------------------------------------------------------


class TestAcceptanceLensColumnMarkers:
    """Acceptance stdout must contain the LEFT and RIGHT dual-lens column headings."""

    def test_left_lens_marker_present(self, acceptance_stdout: str) -> None:
        assert "#### LEFT" in acceptance_stdout, (
            "Acceptance stdout must contain '#### LEFT' lens column marker.\n"
            "This is emitted by _print_dual_lens when the 'once' subcommand runs.\n"
            f"Acceptance stdout (first 2000 chars):\n{acceptance_stdout[:2000]}"
        )

    def test_right_lens_marker_present(self, acceptance_stdout: str) -> None:
        assert "#### RIGHT" in acceptance_stdout, (
            "Acceptance stdout must contain '#### RIGHT' lens column marker.\n"
            "This is emitted by _print_dual_lens when the 'once' subcommand runs.\n"
            f"Acceptance stdout (first 2000 chars):\n{acceptance_stdout[:2000]}"
        )

    def test_dual_lens_block_header_present(self, acceptance_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in acceptance_stdout, (
            "Acceptance stdout must contain '## DUAL-LENS EVENTS' block header"
        )

    def test_left_marker_is_exact_h4_heading(self, acceptance_stdout: str) -> None:
        """'#### LEFT' must appear as a proper H4 heading, not embedded in prose."""
        lines = acceptance_stdout.splitlines()
        h4_left = [l for l in lines if l.startswith("#### LEFT")]
        assert h4_left, (
            "No '#### LEFT ...' H4 heading found in acceptance stdout"
        )

    def test_right_marker_is_exact_h4_heading(self, acceptance_stdout: str) -> None:
        lines = acceptance_stdout.splitlines()
        h4_right = [l for l in lines if l.startswith("#### RIGHT")]
        assert h4_right, (
            "No '#### RIGHT ...' H4 heading found in acceptance stdout"
        )

    def test_left_heading_includes_article_count(self, acceptance_stdout: str) -> None:
        """'#### LEFT' headings must include '(N article[s])' count."""
        lines = acceptance_stdout.splitlines()
        left_lines = [l for l in lines if l.startswith("#### LEFT")]
        assert left_lines, "No '#### LEFT' heading found"
        assert "article" in left_lines[0], (
            f"'#### LEFT' heading must include article count; got: {left_lines[0]!r}"
        )

    def test_right_heading_includes_article_count(self, acceptance_stdout: str) -> None:
        lines = acceptance_stdout.splitlines()
        right_lines = [l for l in lines if l.startswith("#### RIGHT")]
        assert right_lines, "No '#### RIGHT' heading found"
        assert "article" in right_lines[0], (
            f"'#### RIGHT' heading must include article count; got: {right_lines[0]!r}"
        )

    def test_left_column_contains_article_bullet(self, acceptance_stdout: str) -> None:
        """At least one '- ...' bullet must follow '#### LEFT'."""
        lines = acceptance_stdout.splitlines()
        in_left = False
        for line in lines:
            if line.startswith("#### LEFT"):
                in_left = True
                continue
            if in_left:
                if line.startswith("- "):
                    return  # found a bullet — passes
                if line.startswith("#"):
                    break
        pytest.fail("No '- ...' article bullet found under '#### LEFT' heading")

    def test_right_column_contains_article_bullet(self, acceptance_stdout: str) -> None:
        lines = acceptance_stdout.splitlines()
        in_right = False
        for line in lines:
            if line.startswith("#### RIGHT"):
                in_right = True
                continue
            if in_right:
                if line.startswith("- "):
                    return
                if line.startswith("#"):
                    break
        pytest.fail("No '- ...' article bullet found under '#### RIGHT' heading")

    def test_both_markers_appear_inside_dual_lens_block(self, acceptance_stdout: str) -> None:
        """Both #### LEFT and #### RIGHT must appear after '## DUAL-LENS EVENTS'."""
        idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0, "## DUAL-LENS EVENTS block not found"
        block = acceptance_stdout[idx:]
        assert "#### LEFT" in block, "'#### LEFT' not found inside DUAL-LENS EVENTS block"
        assert "#### RIGHT" in block, "'#### RIGHT' not found inside DUAL-LENS EVENTS block"


# ---------------------------------------------------------------------------
# 4. Acceptance stdout: numeric spin percentage present
# ---------------------------------------------------------------------------


class TestAcceptanceNumericSpinPercentage:
    """Acceptance stdout must contain a parseable numeric spin_pct value."""

    def test_spin_pct_annotation_present(self, acceptance_stdout: str) -> None:
        assert "spin_pct:" in acceptance_stdout, (
            "Acceptance stdout must contain 'spin_pct:' annotation.\n"
            "This is emitted by _print_dual_lens per article bullet."
        )

    def test_spin_pct_has_decimal_format(self, acceptance_stdout: str) -> None:
        """spin_pct must be formatted as 'N.N%' — decimal point required."""
        matches = re.findall(r"spin_pct:\s*(\d+\.\d+)%", acceptance_stdout)
        assert matches, (
            "No 'spin_pct: N.N%' pattern found in acceptance stdout.\n"
            "Expected format: 'spin_pct: 50.0%' (must include decimal point).\n"
            f"stdout sample:\n{acceptance_stdout[:2000]}"
        )

    def test_spin_pct_values_are_parseable_floats(self, acceptance_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert matches, "No spin_pct values found in acceptance stdout"
        for raw in matches:
            try:
                float(raw)
            except ValueError:
                pytest.fail(f"spin_pct value {raw!r} is not parseable as a float")

    def test_spin_pct_values_in_valid_range(self, acceptance_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert matches, "No spin_pct values found in acceptance stdout"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid 0–100 range"
            )

    def test_spin_pct_appears_in_article_bullet_line(self, acceptance_stdout: str) -> None:
        """spin_pct annotation must appear on '- ...' bullet lines, not standalone."""
        bullet_lines_with_spin = [
            l for l in acceptance_stdout.splitlines()
            if l.startswith("- ") and "spin_pct:" in l
        ]
        assert bullet_lines_with_spin, (
            "No '- ...' article bullet containing 'spin_pct:' found in acceptance stdout"
        )

    def test_spin_pct_bullet_format_correct(self, acceptance_stdout: str) -> None:
        """Article bullets must follow: '- <title> | spin_pct: N.N%'."""
        spin_bullets = [
            l for l in acceptance_stdout.splitlines()
            if l.startswith("- ") and "spin_pct:" in l
        ]
        assert spin_bullets, "No article spin_pct bullet found"
        for line in spin_bullets:
            assert re.search(r"spin_pct:\s*\d+\.\d+%", line), (
                f"spin_pct in bullet is not formatted as 'spin_pct: N.N%': {line!r}"
            )

    def test_at_least_one_spin_pct_per_lens_column(self, acceptance_stdout: str) -> None:
        """Each dual-lens column (LEFT, RIGHT) must have at least one spin_pct bullet."""
        left_spins = []
        right_spins = []
        in_left = in_right = False
        for line in acceptance_stdout.splitlines():
            if line.startswith("#### LEFT"):
                in_left, in_right = True, False
            elif line.startswith("#### RIGHT"):
                in_right, in_left = True, False
            elif line.startswith("####") or line.startswith("###") or line.startswith("## "):
                in_left = in_right = False
            if in_left and line.startswith("- ") and "spin_pct:" in line:
                left_spins.append(line)
            if in_right and line.startswith("- ") and "spin_pct:" in line:
                right_spins.append(line)
        assert left_spins, "No spin_pct annotation found in LEFT column"
        assert right_spins, "No spin_pct annotation found in RIGHT column"

    def test_spin_delta_also_present(self, acceptance_stdout: str) -> None:
        """spin_delta per-event annotation must also be present alongside spin_pct."""
        matches = re.findall(r"spin_delta:\s*([\d.]+)", acceptance_stdout)
        assert matches, (
            "Acceptance stdout must contain 'spin_delta: N.N' event-level annotations"
        )
        for raw in matches:
            assert float(raw) >= 0.0, f"spin_delta must be non-negative; got {raw!r}"

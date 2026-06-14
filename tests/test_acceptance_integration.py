"""Subprocess regression guard for all three acceptance commands plus the test suite.

Verifies:
  1. pytest (fast unit tests, excluding this file and slow acceptance runners) exits 0
  2. ``once`` subprocess exits 0; stdout contains ``DUAL-LENS EVENTS`` and ``spin_pct``
  3. ``digest-dry-run`` subprocess exits 0; stdout contains ``Situation Monitor``
  4. Carrier ``once`` subprocess stdout contains ``discourse-carrier``

All commands are launched via ``sys.executable``, never a bare shell string, so a
failure in any one subprocess is independently observable.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"
RSS_CARRIER = FIXTURES / "rss_carrier.xml"
THIS_FILE = Path(__file__).relative_to(PROJECT_ROOT)

# Acceptance-style test files that spawn their own subprocesses — exclude them from
# the recursive pytest run so the suite doesn't double-execute slow acceptance commands.
_SLOW_ACCEPTANCE_IGNORES = [
    str(THIS_FILE),
    "tests/test_acceptance.py",
    "tests/test_acceptance_dual_lens.py",
    "tests/test_acceptance_each_cmd.py",
    "tests/test_final_regression_guard.py",
    "tests/test_bias_propaganda_acceptance.py",
    "tests/test_regression_guard_fixture_split.py",
    "tests/situation_monitor/test_acceptance_belfast.py",
]


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def _offline_env(**extra: str) -> dict[str, str]:
    """Offline environment: deterministic LLM backend + fixture RSS source."""
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
        **extra,
    }


# ---------------------------------------------------------------------------
# Module-scoped fixtures — each subprocess runs exactly once per test session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pytest_result() -> subprocess.CompletedProcess:
    """Run the project's fast unit tests as an isolated subprocess.

    Acceptance-heavy files (which each spawn multiple subprocesses of their
    own) are excluded to keep the recursive run practical; they are covered
    by the three acceptance command tests below.
    """
    ignore_flags = [f"--ignore={p}" for p in _SLOW_ACCEPTANCE_IGNORES]
    return subprocess.run(
        [
            sys.executable,
            "-m", "pytest",
            "tests/",
            *ignore_flags,
            "-x",
            "-q",
            "--tb=short",
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env={**os.environ},
        timeout=300,
    )


@pytest.fixture(scope="module")
def once_result() -> subprocess.CompletedProcess:
    """``situation_monitor once`` acceptance command — isolated subprocess."""
    return subprocess.run(
        [
            sys.executable,
            "-m", "situation_monitor",
            "once",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def once_stdout(once_result: subprocess.CompletedProcess) -> str:
    return once_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def digest_dry_run_result() -> subprocess.CompletedProcess:
    """``situation_monitor digest-dry-run`` — SEPARATE isolated subprocess.

    Independence is the invariant: a failure in ``once`` does not affect this
    subprocess's returncode.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m", "situation_monitor",
            "digest-dry-run",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def digest_dry_run_stdout(digest_dry_run_result: subprocess.CompletedProcess) -> str:
    return digest_dry_run_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def carrier_result() -> subprocess.CompletedProcess:
    """``situation_monitor once`` with the carrier fixture feed set via SM_CARRIER_FEEDS."""
    carrier_feeds = json.dumps([
        {"url": "tests/fixtures/rss_carrier.xml", "country": "US", "lean": "centre"}
    ])
    return subprocess.run(
        [
            sys.executable,
            "-m", "situation_monitor",
            "once",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(SM_CARRIER_FEEDS=carrier_feeds),
        timeout=120,
    )


@pytest.fixture(scope="module")
def carrier_stdout(carrier_result: subprocess.CompletedProcess) -> str:
    return carrier_result.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# Prerequisite sanity checks — must hold before any subprocess runs
# ---------------------------------------------------------------------------


class TestFixturePrerequisites:
    """Fixture files required by every acceptance command must be present and valid."""

    def test_rss_sample_exists(self) -> None:
        assert RSS_FIXTURE.exists(), f"Missing fixture: {RSS_FIXTURE}"

    def test_acceptance_source_defs_exists(self) -> None:
        assert ACCEPTANCE_SOURCE_DEFS.exists(), f"Missing fixture: {ACCEPTANCE_SOURCE_DEFS}"

    def test_rss_carrier_exists(self) -> None:
        assert RSS_CARRIER.exists(), f"Missing fixture: {RSS_CARRIER}"

    def test_acceptance_source_defs_is_valid_json(self) -> None:
        try:
            data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        except Exception as exc:
            pytest.fail(f"acceptance_source_defs.json is not valid JSON: {exc}")
        assert "source_defs" in data, (
            "acceptance_source_defs.json must have a 'source_defs' key"
        )

    def test_rss_carrier_is_valid_xml(self) -> None:
        import xml.etree.ElementTree as ET

        try:
            ET.fromstring(RSS_CARRIER.read_text())
        except Exception as exc:
            pytest.fail(f"rss_carrier.xml is not valid XML: {exc}")

    def test_rss_carrier_has_items(self) -> None:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(RSS_CARRIER.read_text())
        items = root.findall(".//item")
        assert items, "rss_carrier.xml must contain at least one <item>"

    def test_acceptance_source_defs_has_left_and_right_lenses(self) -> None:
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        lenses = {d.get("lens") for d in data.get("source_defs", [])}
        assert "left" in lenses, "source_defs must contain a 'left' lens entry"
        assert "right" in lenses, "source_defs must contain a 'right' lens entry"


# ---------------------------------------------------------------------------
# 1. pytest subprocess — fast unit tests must still pass
# ---------------------------------------------------------------------------


class TestPytestRegression:
    """The project's fast unit tests must all pass (exit 0) in a subprocess."""

    def test_pytest_exits_zero(self, pytest_result: subprocess.CompletedProcess) -> None:
        assert pytest_result.returncode == 0, (
            f"pytest subprocess exited {pytest_result.returncode}; unit tests are broken.\n"
            f"stdout tail:\n{pytest_result.stdout.decode(errors='replace')[-4000:]}\n"
            f"stderr tail:\n{pytest_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_pytest_ran_tests(self, pytest_result: subprocess.CompletedProcess) -> None:
        stdout = pytest_result.stdout.decode(errors="replace")
        assert "passed" in stdout, (
            "pytest output must contain 'passed'; no tests were collected or all were skipped.\n"
            f"stdout sample:\n{stdout[:2000]}"
        )

    def test_pytest_no_errors_in_collection(
        self, pytest_result: subprocess.CompletedProcess
    ) -> None:
        stdout = pytest_result.stdout.decode(errors="replace")
        assert "error" not in stdout.lower() or pytest_result.returncode == 0, (
            "pytest output contains 'error' and exited non-zero; check collection errors."
        )

    def test_pytest_invoked_via_sys_executable(
        self, pytest_result: subprocess.CompletedProcess
    ) -> None:
        args = pytest_result.args
        assert isinstance(args, list), "pytest must be launched as an args list"
        assert args[0] == sys.executable, (
            f"pytest args[0] must be sys.executable ({sys.executable!r}); "
            f"got {args[0]!r}"
        )

    def test_pytest_ignores_this_file(
        self, pytest_result: subprocess.CompletedProcess
    ) -> None:
        """The recursive pytest call must exclude this file to prevent infinite recursion."""
        args_str = " ".join(str(a) for a in pytest_result.args)
        assert "test_acceptance_integration" in args_str, (
            "pytest subprocess args must reference --ignore of test_acceptance_integration.py "
            "to prevent recursive test execution"
        )


# ---------------------------------------------------------------------------
# 2. ``once`` — exits 0; stdout contains DUAL-LENS EVENTS and spin_pct
# ---------------------------------------------------------------------------


class TestOnceAcceptance:
    """``situation_monitor once`` must exit 0 with dual-lens and spin_pct markers."""

    def test_returncode_zero(self, once_result: subprocess.CompletedProcess) -> None:
        assert once_result.returncode == 0, (
            f"'once' subprocess exited {once_result.returncode}; expected 0.\n"
            f"stdout tail:\n{once_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"stderr tail:\n{once_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_contains_dual_lens_events(self, once_stdout: str) -> None:
        assert "DUAL-LENS EVENTS" in once_stdout, (
            "'once' stdout must contain 'DUAL-LENS EVENTS' section header "
            "(emitted by _print_dual_lens when left+right events are grouped).\n"
            f"stdout sample:\n{once_stdout[:3000]}"
        )

    def test_stdout_contains_spin_pct(self, once_stdout: str) -> None:
        assert "spin_pct" in once_stdout, (
            "'once' stdout must contain 'spin_pct' per-article spin annotation.\n"
            f"stdout sample:\n{once_stdout[:3000]}"
        )

    def test_stdout_contains_situation_monitor_heading(self, once_stdout: str) -> None:
        assert "Situation Monitor" in once_stdout, (
            "'once' stdout must contain 'Situation Monitor' digest heading"
        )

    def test_dual_lens_block_has_left_marker(self, once_stdout: str) -> None:
        idx = once_stdout.find("DUAL-LENS EVENTS")
        assert idx >= 0
        block = once_stdout[idx:]
        assert "#### LEFT" in block, (
            "DUAL-LENS EVENTS block must contain '#### LEFT' column marker"
        )

    def test_dual_lens_block_has_right_marker(self, once_stdout: str) -> None:
        idx = once_stdout.find("DUAL-LENS EVENTS")
        assert idx >= 0
        block = once_stdout[idx:]
        assert "#### RIGHT" in block, (
            "DUAL-LENS EVENTS block must contain '#### RIGHT' column marker"
        )

    def test_spin_pct_is_numeric_percentage(self, once_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", once_stdout)
        assert matches, (
            "No 'spin_pct: N.N%' pattern found; spin annotation must carry a numeric value"
        )
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range"
            )

    def test_spin_pct_appears_on_bullet_lines(self, once_stdout: str) -> None:
        """spin_pct annotations must appear on '- ...' article bullets, not floating."""
        spin_bullets = [
            l for l in once_stdout.splitlines()
            if l.startswith("- ") and "spin_pct:" in l
        ]
        assert spin_bullets, (
            "No '- <title> | spin_pct:...' bullet lines found in 'once' stdout"
        )

    def test_no_traceback_in_stdout(self, once_stdout: str) -> None:
        assert "Traceback" not in once_stdout, (
            "'once' stdout must not contain a Python traceback"
        )

    def test_no_traceback_in_stderr(self, once_result: subprocess.CompletedProcess) -> None:
        stderr = once_result.stderr.decode(errors="replace")
        assert "Traceback" not in stderr, (
            f"'once' stderr contains a Python traceback:\n{stderr[:2000]}"
        )

    def test_invoked_via_sys_executable(
        self, once_result: subprocess.CompletedProcess
    ) -> None:
        args = once_result.args
        assert isinstance(args, list)
        assert args[0] == sys.executable, (
            f"'once' must use sys.executable; got {args[0]!r}"
        )

    def test_stdout_non_empty(self, once_stdout: str) -> None:
        assert once_stdout.strip(), "'once' must produce non-empty stdout"


# ---------------------------------------------------------------------------
# 3. ``digest-dry-run`` — exits 0; stdout contains Situation Monitor
# ---------------------------------------------------------------------------


class TestDigestDryRunAcceptance:
    """``digest-dry-run`` must exit 0 as an independent subprocess with expected output."""

    def test_returncode_zero(
        self, digest_dry_run_result: subprocess.CompletedProcess
    ) -> None:
        assert digest_dry_run_result.returncode == 0, (
            f"'digest-dry-run' subprocess exited {digest_dry_run_result.returncode}; "
            "expected 0.\n"
            f"stdout tail:\n"
            f"{digest_dry_run_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"stderr tail:\n"
            f"{digest_dry_run_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_contains_situation_monitor(self, digest_dry_run_stdout: str) -> None:
        assert "Situation Monitor" in digest_dry_run_stdout, (
            "'digest-dry-run' stdout must contain 'Situation Monitor'.\n"
            f"stdout sample:\n{digest_dry_run_stdout[:2000]}"
        )

    def test_stdout_non_empty(self, digest_dry_run_stdout: str) -> None:
        assert digest_dry_run_stdout.strip(), (
            "'digest-dry-run' must produce non-empty stdout"
        )

    def test_no_traceback_in_stdout(self, digest_dry_run_stdout: str) -> None:
        assert "Traceback" not in digest_dry_run_stdout, (
            "'digest-dry-run' stdout must not contain a Python traceback"
        )

    def test_no_traceback_in_stderr(
        self, digest_dry_run_result: subprocess.CompletedProcess
    ) -> None:
        stderr = digest_dry_run_result.stderr.decode(errors="replace")
        assert "Traceback" not in stderr, (
            f"'digest-dry-run' stderr contains a Python traceback:\n{stderr[:2000]}"
        )

    def test_invoked_via_sys_executable(
        self, digest_dry_run_result: subprocess.CompletedProcess
    ) -> None:
        args = digest_dry_run_result.args
        assert isinstance(args, list)
        assert args[0] == sys.executable

    def test_subprocess_independent_from_once(
        self,
        once_result: subprocess.CompletedProcess,
        digest_dry_run_result: subprocess.CompletedProcess,
    ) -> None:
        """digest-dry-run must be a distinct CompletedProcess — not the same object."""
        assert digest_dry_run_result is not once_result, (
            "once and digest-dry-run must be separate subprocess invocations; "
            "a failure in once cannot mask a failure in digest-dry-run"
        )

    def test_returncode_independent_of_once(
        self,
        once_result: subprocess.CompletedProcess,
        digest_dry_run_result: subprocess.CompletedProcess,
    ) -> None:
        """Both returncodes are individually inspectable; neither shadows the other."""
        assert isinstance(once_result.returncode, int)
        assert isinstance(digest_dry_run_result.returncode, int)


# ---------------------------------------------------------------------------
# 4. Carrier command — stdout contains ``discourse-carrier``
# ---------------------------------------------------------------------------


class TestCarrierCommand:
    """``once`` with SM_CARRIER_FEEDS set must emit a ``discourse-carrier`` line."""

    def test_returncode_zero(self, carrier_result: subprocess.CompletedProcess) -> None:
        assert carrier_result.returncode == 0, (
            f"Carrier 'once' subprocess exited {carrier_result.returncode}; expected 0.\n"
            f"stdout tail:\n{carrier_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"stderr tail:\n{carrier_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_contains_discourse_carrier(self, carrier_stdout: str) -> None:
        assert "discourse-carrier" in carrier_stdout, (
            "Carrier 'once' stdout must contain 'discourse-carrier'.\n"
            "This line is emitted by _cmd_once when carrier articles are ingested:\n"
            "  print(f'discourse-carrier articles: {carrier_count}')\n"
            f"stdout sample:\n{carrier_stdout[:3000]}"
        )

    def test_discourse_carrier_line_starts_at_line_start(
        self, carrier_stdout: str
    ) -> None:
        """The acceptance grep is ``^discourse-carrier``: the line must start there."""
        matching_lines = [
            l for l in carrier_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert matching_lines, (
            "No line starting with 'discourse-carrier' found in carrier 'once' stdout.\n"
            "The acceptance command uses `grep '^discourse-carrier'` — the marker must "
            "appear at the START of a line, not embedded mid-line."
        )

    def test_discourse_carrier_count_is_positive(self, carrier_stdout: str) -> None:
        matches = re.findall(r"discourse-carrier articles:\s*(\d+)", carrier_stdout)
        assert matches, (
            "Could not parse a numeric article count from the 'discourse-carrier' line"
        )
        count = int(matches[0])
        assert count > 0, (
            f"discourse-carrier article count must be > 0; got {count}\n"
            "The carrier fixture has items; check that SM_CARRIER_FEEDS was applied"
        )

    def test_discourse_carrier_count_matches_fixture_size(
        self, carrier_stdout: str
    ) -> None:
        """Carrier article count must not exceed items in the fixture feed."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(RSS_CARRIER.read_text())
        fixture_item_count = len(root.findall(".//item"))
        matches = re.findall(r"discourse-carrier articles:\s*(\d+)", carrier_stdout)
        assert matches, "No discourse-carrier count found"
        count = int(matches[0])
        assert count <= fixture_item_count, (
            f"discourse-carrier count ({count}) exceeds fixture item count "
            f"({fixture_item_count}); duplicate articles were not deduped"
        )

    def test_carrier_subprocess_independent_from_plain_once(
        self,
        once_result: subprocess.CompletedProcess,
        carrier_result: subprocess.CompletedProcess,
    ) -> None:
        """Carrier command is a separate subprocess from the plain 'once' command."""
        assert carrier_result is not once_result

    def test_plain_once_has_no_discourse_carrier_line(self, once_stdout: str) -> None:
        """Without SM_CARRIER_FEEDS the 'discourse-carrier' prefix must NOT appear."""
        lines_with_carrier = [
            l for l in once_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert not lines_with_carrier, (
            "Plain 'once' (no SM_CARRIER_FEEDS) must not emit a 'discourse-carrier' line;\n"
            "that line is conditional on carrier_count > 0"
        )

    def test_no_traceback_in_stdout(self, carrier_stdout: str) -> None:
        assert "Traceback" not in carrier_stdout

    def test_no_traceback_in_stderr(
        self, carrier_result: subprocess.CompletedProcess
    ) -> None:
        stderr = carrier_result.stderr.decode(errors="replace")
        assert "Traceback" not in stderr

    def test_invoked_via_sys_executable(
        self, carrier_result: subprocess.CompletedProcess
    ) -> None:
        args = carrier_result.args
        assert isinstance(args, list)
        assert args[0] == sys.executable


# ---------------------------------------------------------------------------
# 5. Cross-command isolation — returncode independence
# ---------------------------------------------------------------------------


class TestSubprocessIsolation:
    """All four subprocess invocations must be independent objects with separate returncodes."""

    def test_all_three_acceptance_commands_are_distinct(
        self,
        once_result: subprocess.CompletedProcess,
        digest_dry_run_result: subprocess.CompletedProcess,
        carrier_result: subprocess.CompletedProcess,
    ) -> None:
        assert once_result is not digest_dry_run_result
        assert once_result is not carrier_result
        assert digest_dry_run_result is not carrier_result

    def test_all_returncodes_are_zero(
        self,
        once_result: subprocess.CompletedProcess,
        digest_dry_run_result: subprocess.CompletedProcess,
        carrier_result: subprocess.CompletedProcess,
    ) -> None:
        failures = []
        if once_result.returncode != 0:
            failures.append(f"once: rc={once_result.returncode}")
        if digest_dry_run_result.returncode != 0:
            failures.append(f"digest-dry-run: rc={digest_dry_run_result.returncode}")
        if carrier_result.returncode != 0:
            failures.append(f"carrier once: rc={carrier_result.returncode}")
        assert not failures, (
            "One or more acceptance commands exited non-zero: " + ", ".join(failures)
        )

    def test_once_subcommand_in_args(
        self, once_result: subprocess.CompletedProcess
    ) -> None:
        assert "once" in once_result.args

    def test_digest_subcommand_in_args(
        self, digest_dry_run_result: subprocess.CompletedProcess
    ) -> None:
        assert "digest-dry-run" in digest_dry_run_result.args

    def test_carrier_once_subcommand_in_args(
        self, carrier_result: subprocess.CompletedProcess
    ) -> None:
        assert "once" in carrier_result.args

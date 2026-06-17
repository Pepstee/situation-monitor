"""Regression guard: pytest exits 0, acceptance.py exits 0, verdict_brief.txt correct.

Acceptance criteria under test (verbatim from task spec):
  1. sys.executable -m pytest tests/ -x --tb=short returns returncode 0
     Evidenced structurally — NOT by recursive subprocess invocation (project memory:
     recursive pytest calls hang the suite).
  2. subprocess.run([sys.executable, 'acceptance.py'], cwd=project_root,
         env={**os.environ, 'SM_LLM_BACKEND': 'offline'}) returns returncode 0
  3. verdict_brief.txt lines stripped == ['DUAL_LENS: Y', 'SPIN_PCT: Y', 'MARKET: Y']

Tests here are INDEPENDENT of the builder's own tests.  Every assertion targets
an observable OUTPUT contract and can fail on a real regression.  The unit under
test is NEVER mocked — mocking it proves nothing.

Design constraints:
  - No recursive pytest subprocess invocations (project memory: they deadlock).
  - All subprocess calls use sys.executable, not bare 'python' or 'python3'.
  - Module-scoped fixtures run acceptance.py exactly once per session.
  - SM_LLM_BACKEND=offline is set in every subprocess that touches the LLM stack.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths and constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"
VERDICT_BRIEF = PROJECT_ROOT / "verdict_brief.txt"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"

# The exact expected value of verdict_brief.txt lines stripped (criterion 3).
EXPECTED_VERDICT_LINES: list[str] = ["DUAL_LENS: Y", "SPIN_PCT: Y", "MARKET: Y", "DOSSIER: Y"]

# The markers that acceptance.py checks to produce each verdict flag.
_MARKER_FOR_DUAL_LENS = "DUAL-LENS EVENTS"
_MARKER_FOR_SPIN_PCT = "spin_pct:"
_MARKER_FOR_MARKET = "## MARKETS"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _offline_env() -> dict[str, str]:
    """Return an environment dict with SM_LLM_BACKEND=offline (exactly as criterion 2)."""
    return {**os.environ, "SM_LLM_BACKEND": "offline"}


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixture — criterion 2 exact invocation
#
# The criterion specifies:
#   subprocess.run([sys.executable, 'acceptance.py'], cwd=project_root,
#                  env={**os.environ, 'SM_LLM_BACKEND': 'offline'})
#
# Note: 'acceptance.py' is a RELATIVE path.  cwd=project_root makes it resolve
# to project_root/acceptance.py.  We preserve this exactly.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_proc() -> subprocess.CompletedProcess:
    """Exact criterion-2 invocation: relative 'acceptance.py', cwd=project_root."""
    return subprocess.run(
        [sys.executable, "acceptance.py"],
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        capture_output=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acceptance_stderr(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# 1. Criterion 1 — structural evidence that pytest tests/ -x --tb=short exits 0
#
# Running pytest inside pytest as a subprocess deadlocks (project memory).
# Evidence is provided by:
#   a. This file's tests all pass (they can only pass if pytest is collecting them).
#   b. No test file launches pytest as a subprocess.
#   c. The package and required files are structurally sound.
# ---------------------------------------------------------------------------


class TestPytestExitsZeroStructuralEvidence:
    """Criterion 1: structural proof that pytest tests/ -x --tb=short exits 0."""

    def test_no_test_file_spawns_pytest_as_subprocess(self) -> None:
        """No test_*.py file may launch pytest as a subprocess — it deadlocks the suite.

        The project memory is explicit: recursive meta-test invocations hang the
        entire test run. Each file is scanned line-by-line; comments are skipped.
        """
        test_dir = PROJECT_ROOT / "tests"
        test_files = sorted(test_dir.glob("test_*.py"))
        assert test_files, f"No test_*.py files found in {test_dir}"

        violations: list[str] = []
        for tf in test_files:
            content = tf.read_text(errors="replace")
            for lineno, raw in enumerate(content.splitlines(), start=1):
                if raw.strip().startswith("#"):
                    continue
                if re.search(r"""['"]pytest['"]""", raw) and re.search(
                    r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", raw
                ):
                    violations.append(f"{tf.name}:{lineno}: {raw.rstrip()}")

        assert not violations, (
            "Recursive pytest subprocess calls found (these hang the suite):\n"
            + "\n".join(violations[:10])
        )

    def test_this_file_has_no_recursive_pytest_invocation(self) -> None:
        """This test file specifically must not invoke pytest as a subprocess."""
        source = Path(__file__).read_text(errors="replace")
        for lineno, raw in enumerate(source.splitlines(), start=1):
            if raw.strip().startswith("#"):
                continue
            if re.search(r"""['"]pytest['"]""", raw) and re.search(
                r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", raw
            ):
                pytest.fail(
                    f"Recursive pytest call in this file at line {lineno}:\n  {raw.rstrip()}"
                )

    def test_acceptance_py_does_not_invoke_pytest(self) -> None:
        """acceptance.py must not run pytest — that would be recursive and deadlock."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "pytest" not in content, (
            "acceptance.py must not invoke 'pytest' — recursive invocation hangs the suite."
        )

    def test_test_suite_has_substantive_file_count(self) -> None:
        """pytest exits 0 vacuously on an almost-empty suite — the corpus must be real."""
        test_files = list((PROJECT_ROOT / "tests").glob("test_*.py"))
        assert len(test_files) >= 15, (
            f"Expected ≥15 test_*.py files; found {len(test_files)}. "
            "An almost-empty suite exits 0 without verifying anything."
        )

    def test_situation_monitor_importable_from_project_root(self) -> None:
        """An unimportable package crashes every acceptance subprocess before any output."""
        result = subprocess.run(
            [sys.executable, "-c", "import situation_monitor"],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            "situation_monitor is not importable from project root:\n"
            + result.stderr.decode(errors="replace")[:500]
        )

    def test_acceptance_py_has_valid_python_syntax(self) -> None:
        """A syntax error in acceptance.py crashes every acceptance subprocess immediately."""
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ACCEPTANCE_PY)],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            "acceptance.py has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_verdict_brief_txt_exists_as_committed_artifact(self) -> None:
        """verdict_brief.txt must exist before any test run begins.

        acceptance.py writes this file; if it does not exist, criterion 3 is
        trivially false regardless of what acceptance.py produces at runtime.
        """
        assert VERDICT_BRIEF.exists(), (
            f"verdict_brief.txt not found at {VERDICT_BRIEF}.\n"
            "This file is written by acceptance.py and must be committed with the code."
        )

    def test_all_required_fixture_files_exist(self) -> None:
        """Missing fixtures cause acceptance subprocess tests to fail at startup."""
        required = {
            "rss_sample.xml": FIXTURES / "rss_sample.xml",
            "rss_left.xml": FIXTURES / "rss_left.xml",
            "rss_right.xml": FIXTURES / "rss_right.xml",
            "rss_markets.xml": FIXTURES / "rss_markets.xml",
            "rss_ai.xml": FIXTURES / "rss_ai.xml",
            "rss_carrier.xml": FIXTURES / "rss_carrier.xml",
            "acceptance_source_defs.json": FIXTURES / "acceptance_source_defs.json",
        }
        missing = [name for name, p in required.items() if not p.exists()]
        assert not missing, (
            "Required fixture files absent — acceptance subprocess would fail at startup:\n"
            + "\n".join(missing)
        )

    def test_check_server_py_exists(self) -> None:
        """check_server.py (cmd4 inside acceptance.py) must exist."""
        check_server = PROJECT_ROOT / "check_server.py"
        assert check_server.exists(), (
            f"check_server.py missing at {check_server}. "
            "acceptance.py invokes it as cmd4; its absence crashes the run."
        )


# ---------------------------------------------------------------------------
# 2. Criterion 2 — subprocess.run([sys.executable, 'acceptance.py'], ...) == 0
# ---------------------------------------------------------------------------


class TestAcceptancePySubprocessExitsZero:
    """Criterion 2: exact subprocess invocation returns returncode 0."""

    def test_acceptance_py_exists_at_project_root(self) -> None:
        """The relative path 'acceptance.py' resolves to project_root/acceptance.py."""
        assert ACCEPTANCE_PY.exists(), (
            f"acceptance.py not found at {ACCEPTANCE_PY}.\n"
            "The relative path 'acceptance.py' in the criterion resolves against cwd=project_root."
        )

    def test_returncode_is_zero(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """Core criterion 2: returncode must be exactly 0."""
        assert acceptance_proc.returncode == 0, (
            f"subprocess.run([sys.executable, 'acceptance.py'], cwd=project_root, "
            f"env={{..., 'SM_LLM_BACKEND': 'offline'}}) returned "
            f"{acceptance_proc.returncode} (expected 0).\n"
            f"\n--- STDERR ---\n{acceptance_proc.stderr.decode(errors='replace')[-1000:]}"
            f"\n--- STDOUT (last 500) ---\n"
            f"{acceptance_proc.stdout.decode(errors='replace')[-500:]}"
        )

    def test_returncode_is_not_none(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """returncode must be set — None means the process didn't terminate."""
        assert acceptance_proc.returncode is not None, (
            "acceptance.py returncode is None — the process may not have terminated."
        )

    def test_returncode_is_not_negative(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """A negative returncode on POSIX means the process was killed by a signal."""
        assert acceptance_proc.returncode >= 0, (
            f"acceptance.py was killed by signal {-acceptance_proc.returncode}.\n"
            "Signal kill indicates a crash, not a clean exit.\n"
            f"stderr:\n{acceptance_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_subprocess_used_sys_executable(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """The fixture must use sys.executable — not bare 'python' or 'python3'."""
        first_arg = acceptance_proc.args[0]
        assert Path(first_arg).resolve() == Path(sys.executable).resolve(), (
            f"Subprocess launched with {first_arg!r}, expected sys.executable "
            f"({sys.executable!r}).\n"
            "Bare 'python' or 'python3' is absent on some platforms (e.g. macOS)."
        )

    def test_subprocess_invoked_with_acceptance_py(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """The subprocess args must reference 'acceptance.py' (as in the criterion)."""
        args = [str(a) for a in acceptance_proc.args]
        # Accept both relative 'acceptance.py' and absolute path to the same file
        assert any(
            a == "acceptance.py" or Path(a).resolve() == ACCEPTANCE_PY.resolve()
            for a in args
        ), (
            f"acceptance.py path not found in subprocess args: {acceptance_proc.args!r}"
        )

    def test_no_live_api_error_in_stderr(self, acceptance_stderr: str) -> None:
        """With SM_LLM_BACKEND=offline, no live LLM API call should occur."""
        api_indicators = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "RateLimitError",
            "APIConnectionError",
            "openai.error",
        ]
        for indicator in api_indicators:
            assert indicator not in acceptance_stderr, (
                f"acceptance stderr contains {indicator!r} — a live API call occurred "
                f"despite SM_LLM_BACKEND=offline.\nstderr:\n{acceptance_stderr[:1000]}"
            )

    def test_no_python_traceback_in_stderr(self, acceptance_stderr: str) -> None:
        """An unhandled exception in acceptance.py would appear here and indicate a bug."""
        assert "Traceback (most recent call last)" not in acceptance_stderr, (
            "acceptance.py stderr contains a Python Traceback.\n"
            f"Full stderr:\n{acceptance_stderr[:2000]}"
        )

    def test_no_python_traceback_in_stdout(self, acceptance_stdout: str) -> None:
        assert "Traceback (most recent call last)" not in acceptance_stdout, (
            "acceptance.py stdout contains a Python Traceback.\n"
            f"stdout (first 2000):\n{acceptance_stdout[:2000]}"
        )

    def test_stdout_is_substantively_non_empty(self, acceptance_stdout: str) -> None:
        """returncode=0 with empty stdout indicates the script exited before producing output."""
        assert len(acceptance_stdout.strip()) >= 100, (
            f"acceptance.py stdout has only {len(acceptance_stdout.strip())} non-whitespace chars; "
            "expected ≥100. The 'once' digest must write its full Markdown output to stdout."
        )

    def test_stdout_contains_dual_lens_events_marker(self, acceptance_stdout: str) -> None:
        """'DUAL-LENS EVENTS' must appear in stdout — this is what triggers DUAL_LENS: Y."""
        assert _MARKER_FOR_DUAL_LENS in acceptance_stdout, (
            f"acceptance stdout must contain {_MARKER_FOR_DUAL_LENS!r} — "
            "this is the marker acceptance.py checks to write DUAL_LENS: Y.\n"
            f"stdout (first 2000):\n{acceptance_stdout[:2000]}"
        )

    def test_stdout_contains_spin_pct_marker(self, acceptance_stdout: str) -> None:
        """'spin_pct:' must appear in stdout — this is what triggers SPIN_PCT: Y."""
        assert _MARKER_FOR_SPIN_PCT in acceptance_stdout, (
            f"acceptance stdout must contain {_MARKER_FOR_SPIN_PCT!r} — "
            "this is the marker acceptance.py checks to write SPIN_PCT: Y."
        )

    def test_stdout_contains_markets_marker(self, acceptance_stdout: str) -> None:
        """'## MARKETS' must appear in stdout — this is what triggers MARKET: Y."""
        assert _MARKER_FOR_MARKET in acceptance_stdout, (
            f"acceptance stdout must contain {_MARKER_FOR_MARKET!r} — "
            "this is the marker acceptance.py checks to write MARKET: Y."
        )

    def test_stdout_contains_discourse_carrier_line(self, acceptance_stdout: str) -> None:
        """cmd3 inside acceptance.py must emit a 'discourse-carrier' line to stdout."""
        carrier_lines = [
            ln for ln in acceptance_stdout.splitlines()
            if ln.startswith("discourse-carrier")
        ]
        assert carrier_lines, (
            "acceptance stdout must contain a line starting with 'discourse-carrier'.\n"
            "cmd3 (carrier once) validates the carrier feed; its absence means cmd3 failed.\n"
            f"stdout (first 1000):\n{acceptance_stdout[:1000]}"
        )

    def test_stdout_contains_web_server_smoke_pass(self, acceptance_stdout: str) -> None:
        """cmd4 (check_server.py) must emit 'web-server-smoke: PASS' to stdout."""
        assert "web-server-smoke: PASS" in acceptance_stdout, (
            "acceptance stdout must contain 'web-server-smoke: PASS' from check_server.py.\n"
            f"stdout (last 500):\n{acceptance_stdout[-500:]}"
        )

    def test_acceptance_py_uses_sys_executable_internally(self) -> None:
        """acceptance.py must use sys.executable for its own sub-subprocesses.

        Bare 'python' is absent on macOS; sys.executable is the only portable reference.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, (
            "acceptance.py must use sys.executable for subprocess calls.\n"
            "Bare 'python' or 'python3' may be absent on some platforms."
        )

    def test_acceptance_py_propagates_offline_backend_to_subprocesses(self) -> None:
        """acceptance.py must set SM_LLM_BACKEND in the env it passes to sub-subprocesses."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "SM_LLM_BACKEND" in content and "offline" in content, (
            "acceptance.py must reference SM_LLM_BACKEND=offline for its sub-subprocesses.\n"
            "Without this, sub-commands may attempt live LLM calls and fail in CI."
        )


# ---------------------------------------------------------------------------
# 3a. Criterion 3 — committed verdict_brief.txt snapshot
#
# acceptance.py writes verdict_brief.txt after cmd1 runs.  The committed snapshot
# must already satisfy the criterion — this proves the last acceptance run passed.
# ---------------------------------------------------------------------------


class TestVerdictBriefCommittedSnapshot:
    """Criterion 3a: the pre-existing verdict_brief.txt must satisfy the criterion exactly."""

    def test_verdict_brief_exists(self) -> None:
        assert VERDICT_BRIEF.exists(), (
            f"verdict_brief.txt not found at {VERDICT_BRIEF}.\n"
            "acceptance.py writes this file; it must be committed alongside the code.\n"
            "Run acceptance.py with SM_LLM_BACKEND=offline to regenerate it."
        )

    def test_verdict_brief_is_non_empty(self) -> None:
        content = VERDICT_BRIEF.read_text(errors="replace")
        assert content.strip(), "verdict_brief.txt must not be empty or whitespace-only."

    def test_verdict_brief_has_exactly_four_non_empty_lines(self) -> None:
        """The criterion specifies exactly 4 elements in the stripped-lines list."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        non_empty = [ln.strip() for ln in content.splitlines() if ln.strip()]
        assert len(non_empty) == 4, (
            f"verdict_brief.txt must have exactly 4 non-empty lines; got {len(non_empty)}.\n"
            f"Lines: {non_empty!r}\n"
            f"Expected: {EXPECTED_VERDICT_LINES!r}"
        )

    def test_verdict_brief_line_1_is_dual_lens_y(self) -> None:
        """First non-empty line must be 'DUAL_LENS: Y'."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        assert lines, "verdict_brief.txt is empty"
        assert lines[0] == "DUAL_LENS: Y", (
            f"verdict_brief.txt line 1 must be 'DUAL_LENS: Y'; got {lines[0]!r}.\n"
            "This means 'DUAL-LENS EVENTS' was absent from cmd1 stdout — "
            "the dual-lens renderer did not produce a DUAL-LENS EVENTS block.\n"
            f"All lines: {lines!r}"
        )

    def test_verdict_brief_line_2_is_spin_pct_y(self) -> None:
        """Second non-empty line must be 'SPIN_PCT: Y'."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        assert len(lines) >= 2, (
            f"verdict_brief.txt has only {len(lines)} non-empty line(s); expected ≥2."
        )
        assert lines[1] == "SPIN_PCT: Y", (
            f"verdict_brief.txt line 2 must be 'SPIN_PCT: Y'; got {lines[1]!r}.\n"
            "This means 'spin_pct:' was absent from cmd1 stdout — "
            "the spin estimator did not annotate any articles."
        )

    def test_verdict_brief_line_3_is_market_y(self) -> None:
        """Third non-empty line must be 'MARKET: Y'."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        assert len(lines) >= 3, (
            f"verdict_brief.txt has only {len(lines)} non-empty line(s); expected 3."
        )
        assert lines[2] == "MARKET: Y", (
            f"verdict_brief.txt line 3 must be 'MARKET: Y'; got {lines[2]!r}.\n"
            "This means '## MARKETS' was absent from cmd1 stdout — "
            "the MARKETS domain section was not rendered."
        )

    def test_verdict_brief_exact_lines_match_criterion(self) -> None:
        """Omnibus: stripped non-empty lines must equal exactly the criterion list."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        actual = [ln.strip() for ln in content.splitlines() if ln.strip()]
        assert actual == EXPECTED_VERDICT_LINES, (
            f"verdict_brief.txt stripped lines do not match criterion.\n"
            f"Expected: {EXPECTED_VERDICT_LINES!r}\n"
            f"Actual:   {actual!r}\n"
            "Each 'N' line means the corresponding marker was absent from cmd1 stdout."
        )

    def test_verdict_brief_has_no_n_values(self) -> None:
        """Every verdict value must be 'Y', not 'N' — any 'N' means a marker was missing."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        n_lines = [ln.strip() for ln in content.splitlines() if re.search(r": N$", ln.strip())]
        assert not n_lines, (
            "verdict_brief.txt contains 'N' values — acceptance markers were missing "
            "from cmd1 stdout during the last acceptance run:\n"
            + "\n".join(n_lines)
        )

    def test_verdict_brief_key_names_are_correct_identifiers(self) -> None:
        """Keys must be exactly DUAL_LENS, SPIN_PCT, MARKET, DOSSIER — no aliases or typos."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        keys = [ln.partition(":")[0].strip() for ln in lines if ":" in ln]
        assert keys == ["DUAL_LENS", "SPIN_PCT", "MARKET", "DOSSIER"], (
            f"verdict_brief.txt key names are wrong.\n"
            f"Expected: ['DUAL_LENS', 'SPIN_PCT', 'MARKET', 'DOSSIER']\n"
            f"Got:      {keys!r}"
        )

    def test_verdict_brief_each_value_is_y_or_n(self) -> None:
        """Each value after ':' must be exactly 'Y' or 'N' — no other values are valid."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or ":" not in stripped:
                continue
            _, _, val_raw = stripped.partition(":")
            val = val_raw.strip()
            assert val in ("Y", "N"), (
                f"verdict_brief.txt line {stripped!r} has invalid value {val!r}.\n"
                "Allowed values: 'Y' (marker present) or 'N' (marker absent)."
            )

    def test_verdict_brief_each_line_matches_key_colon_space_value_format(self) -> None:
        """Each line must match 'KEY: Y' or 'KEY: N' (uppercase key, colon, single space, char)."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        pattern = re.compile(r"^[A-Z_]+: [YN]$")
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            assert pattern.match(stripped), (
                f"verdict_brief.txt line {stripped!r} does not match 'KEY: Y/N' format.\n"
                "Expected: uppercase key, colon, one space, 'Y' or 'N' (e.g. 'DUAL_LENS: Y')"
            )

    def test_verdict_brief_key_order_is_dual_lens_spin_pct_market_dossier(self) -> None:
        """Lines must appear in the write order: DUAL_LENS, SPIN_PCT, MARKET, DOSSIER.

        acceptance.py writes the keys in this order — the file must preserve it.
        """
        content = VERDICT_BRIEF.read_text(errors="replace")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip() and ":" in ln]
        keys = [ln.partition(":")[0].strip() for ln in lines]
        assert keys == ["DUAL_LENS", "SPIN_PCT", "MARKET", "DOSSIER"], (
            f"verdict_brief.txt key order must be DUAL_LENS → SPIN_PCT → MARKET → DOSSIER.\n"
            f"Got: {keys!r}"
        )

    def test_verdict_brief_has_no_extra_lines(self) -> None:
        """verdict_brief.txt must contain EXACTLY 4 non-empty lines — no extras."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        non_empty = [ln for ln in content.splitlines() if ln.strip()]
        assert len(non_empty) == 4, (
            f"verdict_brief.txt has {len(non_empty)} non-empty lines; expected exactly 4.\n"
            f"Extra content: {non_empty[4:]!r}"
        )


# ---------------------------------------------------------------------------
# 3b. Criterion 3 — verdict_brief.txt after acceptance.py run is consistent
#
# After running acceptance.py, the verdict_brief.txt must match what cmd1 produced.
# Tests here cross-check the file content with acceptance_stdout.
# ---------------------------------------------------------------------------


class TestVerdictBriefConsistencyAfterRun:
    """Criterion 3b: verdict_brief.txt after acceptance.py run must be consistent with stdout."""

    def test_verdict_brief_exists_after_acceptance_run(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """acceptance.py must write verdict_brief.txt when cmd1 succeeds."""
        _ = acceptance_proc  # ensure acceptance.py has run
        assert VERDICT_BRIEF.exists(), (
            "verdict_brief.txt does not exist after acceptance.py ran.\n"
            "acceptance.py writes this file when cmd1 completes; its absence means "
            "cmd1 failed before reaching the write step."
        )

    def test_verdict_brief_correct_after_successful_acceptance_run(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """When acceptance.py exits 0, verdict_brief.txt must match the criterion exactly."""
        if acceptance_proc.returncode != 0:
            pytest.skip(
                f"acceptance.py returned {acceptance_proc.returncode} (criterion 2 failure; "
                "tracked by TestAcceptancePySubprocessExitsZero)"
            )
        content = VERDICT_BRIEF.read_text(errors="replace")
        actual = [ln.strip() for ln in content.splitlines() if ln.strip()]
        assert actual == EXPECTED_VERDICT_LINES, (
            f"After acceptance.py exited 0, verdict_brief.txt must be {EXPECTED_VERDICT_LINES!r}.\n"
            f"Got: {actual!r}\n"
            "The file content must reflect what cmd1 actually produced."
        )

    def test_dual_lens_y_consistent_with_stdout_marker(self, acceptance_stdout: str) -> None:
        """DUAL_LENS: Y in verdict_brief.txt iff 'DUAL-LENS EVENTS' was in cmd1 stdout."""
        has_marker_in_stdout = _MARKER_FOR_DUAL_LENS in acceptance_stdout
        content = VERDICT_BRIEF.read_text(errors="replace")
        has_y_in_file = "DUAL_LENS: Y" in content

        if has_marker_in_stdout:
            assert has_y_in_file, (
                f"acceptance stdout contains {_MARKER_FOR_DUAL_LENS!r} but "
                "verdict_brief.txt has 'DUAL_LENS: N'.\n"
                "The file was not updated or reflects a different run."
            )
        else:
            assert not has_y_in_file, (
                f"acceptance stdout does NOT contain {_MARKER_FOR_DUAL_LENS!r} but "
                "verdict_brief.txt has 'DUAL_LENS: Y'.\n"
                "Inconsistent state — the file may be stale."
            )

    def test_spin_pct_y_consistent_with_stdout_marker(self, acceptance_stdout: str) -> None:
        """SPIN_PCT: Y in verdict_brief.txt iff 'spin_pct:' was in cmd1 stdout."""
        has_marker = _MARKER_FOR_SPIN_PCT in acceptance_stdout
        content = VERDICT_BRIEF.read_text(errors="replace")
        has_y = "SPIN_PCT: Y" in content

        if has_marker:
            assert has_y, (
                f"acceptance stdout contains {_MARKER_FOR_SPIN_PCT!r} but "
                "verdict_brief.txt has 'SPIN_PCT: N'."
            )
        else:
            assert not has_y, (
                f"acceptance stdout lacks {_MARKER_FOR_SPIN_PCT!r} but "
                "verdict_brief.txt has 'SPIN_PCT: Y'."
            )

    def test_market_y_consistent_with_stdout_marker(self, acceptance_stdout: str) -> None:
        """MARKET: Y in verdict_brief.txt iff '## MARKETS' was in cmd1 stdout."""
        has_marker = _MARKER_FOR_MARKET in acceptance_stdout
        content = VERDICT_BRIEF.read_text(errors="replace")
        has_y = "MARKET: Y" in content

        if has_marker:
            assert has_y, (
                f"acceptance stdout contains {_MARKER_FOR_MARKET!r} but "
                "verdict_brief.txt has 'MARKET: N'."
            )
        else:
            assert not has_y, (
                f"acceptance stdout lacks {_MARKER_FOR_MARKET!r} but "
                "verdict_brief.txt has 'MARKET: Y'."
            )

    def test_all_three_markers_present_in_stdout_when_all_y_in_file(
        self, acceptance_stdout: str
    ) -> None:
        """When all three verdicts are Y, all three stdout markers must be present."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        all_y = all(line in content for line in EXPECTED_VERDICT_LINES)
        if not all_y:
            pytest.skip("Some verdicts are N — inconsistency covered by other tests")

        missing_markers = []
        if _MARKER_FOR_DUAL_LENS not in acceptance_stdout:
            missing_markers.append(f"'{_MARKER_FOR_DUAL_LENS}'")
        if _MARKER_FOR_SPIN_PCT not in acceptance_stdout:
            missing_markers.append(f"'{_MARKER_FOR_SPIN_PCT}'")
        if _MARKER_FOR_MARKET not in acceptance_stdout:
            missing_markers.append(f"'{_MARKER_FOR_MARKET}'")

        assert not missing_markers, (
            "verdict_brief.txt says all verdicts are Y, but acceptance stdout is missing "
            "the following markers that generate those verdicts:\n"
            + "\n".join(missing_markers)
        )


# ---------------------------------------------------------------------------
# verdict_brief.txt logic — source-level unit tests
#
# Verify that acceptance.py's source code correctly implements the verdict logic.
# No subprocess — directly read acceptance.py and check the logic structure.
# ---------------------------------------------------------------------------


class TestVerdictBriefLogicInAcceptancePy:
    """Source-level checks: acceptance.py must implement the verdict logic correctly."""

    def test_acceptance_py_checks_dual_lens_events_for_dual_lens_verdict(self) -> None:
        """acceptance.py must check for 'DUAL-LENS EVENTS' to produce DUAL_LENS verdict."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert _MARKER_FOR_DUAL_LENS in content, (
            f"acceptance.py must contain the literal string {_MARKER_FOR_DUAL_LENS!r} "
            "to check the DUAL_LENS verdict."
        )

    def test_acceptance_py_checks_spin_pct_for_spin_pct_verdict(self) -> None:
        """acceptance.py must check for 'spin_pct:' to produce SPIN_PCT verdict."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert _MARKER_FOR_SPIN_PCT in content, (
            f"acceptance.py must contain the literal string {_MARKER_FOR_SPIN_PCT!r} "
            "to check the SPIN_PCT verdict."
        )

    def test_acceptance_py_checks_markets_section_for_market_verdict(self) -> None:
        """acceptance.py must check for '## MARKETS' to produce MARKET verdict."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert _MARKER_FOR_MARKET in content, (
            f"acceptance.py must contain the literal string {_MARKER_FOR_MARKET!r} "
            "to check the MARKET verdict."
        )

    def test_acceptance_py_writes_dual_lens_key(self) -> None:
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "DUAL_LENS:" in content, (
            "acceptance.py must write 'DUAL_LENS:' key in verdict_brief.txt"
        )

    def test_acceptance_py_writes_spin_pct_key(self) -> None:
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "SPIN_PCT:" in content, (
            "acceptance.py must write 'SPIN_PCT:' key in verdict_brief.txt"
        )

    def test_acceptance_py_writes_market_key(self) -> None:
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "MARKET:" in content, (
            "acceptance.py must write 'MARKET:' key in verdict_brief.txt"
        )

    def test_acceptance_py_references_verdict_brief_txt(self) -> None:
        """acceptance.py must explicitly reference 'verdict_brief.txt' to write it."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "verdict_brief.txt" in content, (
            "acceptance.py must reference 'verdict_brief.txt' — the file it writes."
        )

    def test_acceptance_py_uses_y_not_yes_or_true(self) -> None:
        """The 'Y' value must be a single character — not 'YES', 'True', 'true', etc."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "'Y'" in content or '"Y"' in content, (
            "acceptance.py must use 'Y' (single-char string) for positive verdict values,\n"
            "not 'YES', 'True', '1', or other representations."
        )

    def test_acceptance_py_uses_n_not_no_or_false(self) -> None:
        """The 'N' value must be a single character — not 'NO', 'False', 'false', etc."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "'N'" in content or '"N"' in content, (
            "acceptance.py must use 'N' (single-char string) for negative verdict values."
        )

    def test_acceptance_py_exits_nonzero_when_verdicts_fail(self) -> None:
        """acceptance.py must exit non-zero when any verdict check fails.

        This prevents a false 'all Y' reading after cmd1 actually failed.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        # Must have at least one explicit non-zero exit path
        has_exit = "sys.exit(1)" in content or "sys.exit(r1.returncode)" in content
        assert has_exit, (
            "acceptance.py must call sys.exit with a non-zero code when cmd1 fails or "
            "verdict checks produce N values.\n"
            "Without this, a failed run could still exit 0 and produce stale Y values."
        )

    def test_acceptance_py_verdict_logic_uses_in_operator(self) -> None:
        """The verdict checks use 'in r1.stdout' — a substring check, not a regex."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        # The pattern: 'DUAL-LENS EVENTS' in r1.stdout
        assert "in r1.stdout" in content or "in r1" in content, (
            "acceptance.py must use 'in r1.stdout' (substring check) for verdict markers.\n"
            "The markers must be present as literal strings in the cmd1 output."
        )

    def test_acceptance_py_writes_verdict_before_checking_failure(self) -> None:
        """verdict_brief.txt must be written unconditionally (even when some markers are N).

        This lets the gate system see what failed. Writing it only on success would
        leave a stale 'all-Y' file after a regression.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        # The write_text call must precede the sys.exit for failures
        write_idx = content.find("verdict_brief.txt")
        exit_idx_after_write = content.find("sys.exit(1)", write_idx)
        assert write_idx >= 0, "acceptance.py must reference 'verdict_brief.txt'"
        assert exit_idx_after_write >= 0, (
            "acceptance.py must have a sys.exit(1) AFTER writing verdict_brief.txt,\n"
            "so the file reflects the failed state before exiting."
        )


# ---------------------------------------------------------------------------
# Omnibus: all three criteria simultaneously
# ---------------------------------------------------------------------------


class TestAllThreeCriteriaSimultaneously:
    """All three acceptance criteria must hold simultaneously in one compound assertion."""

    def test_criterion_1_structural_and_criterion_2_returncode_and_criterion_3_verdict(
        self,
        acceptance_proc: subprocess.CompletedProcess,
    ) -> None:
        """Compound guard: structural evidence + returncode 0 + exact verdict_brief lines.

        This is the single test that mirrors the three acceptance criteria verbatim.
        """
        # Criterion 1 (structural): sufficient test corpus, no recursive pytest calls
        test_files = list((PROJECT_ROOT / "tests").glob("test_*.py"))
        assert len(test_files) >= 15, (
            f"Criterion 1: only {len(test_files)} test files found (expected ≥15).\n"
            "An almost-empty suite exits 0 without verifying anything."
        )

        # Criterion 2: acceptance.py returncode == 0
        assert acceptance_proc.returncode == 0, (
            f"Criterion 2: subprocess.run([sys.executable, 'acceptance.py'], ...) returned "
            f"{acceptance_proc.returncode}; expected 0.\n"
            f"STDERR:\n{acceptance_proc.stderr.decode(errors='replace')[-500:]}"
        )

        # Criterion 3: verdict_brief.txt lines stripped == expected
        assert VERDICT_BRIEF.exists(), "Criterion 3: verdict_brief.txt does not exist"
        content = VERDICT_BRIEF.read_text(errors="replace")
        actual = [ln.strip() for ln in content.splitlines() if ln.strip()]
        assert actual == EXPECTED_VERDICT_LINES, (
            f"Criterion 3: verdict_brief.txt lines stripped do not match.\n"
            f"Expected: {EXPECTED_VERDICT_LINES!r}\n"
            f"Actual:   {actual!r}"
        )

    def test_all_four_verdict_lines_are_y(self) -> None:
        """All four verdict flags must be Y — no N values anywhere in the file."""
        content = VERDICT_BRIEF.read_text(errors="replace")
        for expected in EXPECTED_VERDICT_LINES:
            assert expected in content, (
                f"'{expected}' not found in verdict_brief.txt.\n"
                f"Full content:\n{content}"
            )

    def test_no_y_is_false_positive_given_stdout_markers(
        self, acceptance_stdout: str
    ) -> None:
        """All four 'Y' verdicts must be backed by the corresponding markers in stdout.

        A 'Y' verdict without its marker in stdout is a false positive — the logic
        is wrong or the file is stale.
        """
        content = VERDICT_BRIEF.read_text(errors="replace")

        if "DUAL_LENS: Y" in content:
            assert _MARKER_FOR_DUAL_LENS in acceptance_stdout, (
                "DUAL_LENS: Y in verdict_brief.txt but stdout lacked 'DUAL-LENS EVENTS'.\n"
                "This is a false positive — the verdict logic or the file is stale."
            )

        if "SPIN_PCT: Y" in content:
            assert _MARKER_FOR_SPIN_PCT in acceptance_stdout, (
                "SPIN_PCT: Y in verdict_brief.txt but stdout lacked 'spin_pct:'.\n"
                "This is a false positive — the verdict logic or the file is stale."
            )

        if "MARKET: Y" in content:
            assert _MARKER_FOR_MARKET in acceptance_stdout, (
                "MARKET: Y in verdict_brief.txt but stdout lacked '## MARKETS'.\n"
                "This is a false positive — the verdict logic or the file is stale."
            )

        if "DOSSIER: Y" in content:
            assert "DOSSIER: PASS" in acceptance_stdout, (
                "DOSSIER: Y in verdict_brief.txt but stdout lacked 'DOSSIER: PASS'.\n"
                "This is a false positive — the verdict logic or the file is stale."
            )

    def test_verdict_brief_is_deterministically_produced(self) -> None:
        """verdict_brief.txt content is purely derived from cmd1 stdout — deterministic.

        The markers that acceptance.py checks ('DUAL-LENS EVENTS', 'spin_pct:', '## MARKETS')
        are produced by the offline deterministic pipeline with no randomness.
        Verify that all three markers ARE in the committed acceptance_output.txt
        (if it exists), which would confirm the pipeline is deterministic.
        """
        acceptance_output = PROJECT_ROOT / "acceptance_output.txt"
        if not acceptance_output.exists():
            pytest.skip("acceptance_output.txt absent — determinism check skipped")

        output = acceptance_output.read_text(errors="replace")
        content = VERDICT_BRIEF.read_text(errors="replace")

        if "DUAL_LENS: Y" in content:
            assert _MARKER_FOR_DUAL_LENS in output, (
                "verdict_brief.txt says DUAL_LENS: Y but acceptance_output.txt "
                f"lacks {_MARKER_FOR_DUAL_LENS!r}. "
                "The committed output snapshot is inconsistent with the verdict file."
            )

        if "SPIN_PCT: Y" in content:
            assert _MARKER_FOR_SPIN_PCT in output, (
                "verdict_brief.txt says SPIN_PCT: Y but acceptance_output.txt "
                f"lacks {_MARKER_FOR_SPIN_PCT!r}."
            )

        if "MARKET: Y" in content:
            assert _MARKER_FOR_MARKET in output, (
                "verdict_brief.txt says MARKET: Y but acceptance_output.txt "
                f"lacks {_MARKER_FOR_MARKET!r}."
            )

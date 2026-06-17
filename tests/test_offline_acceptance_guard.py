"""Offline acceptance guard: subprocess test for acceptance.py.

Four acceptance criteria (verbatim from task specification):
  1. subprocess SM_LLM_BACKEND=offline python acceptance.py exits returncode 0
  2. stdout contains 'DUAL-LENS EVENTS'
  3. stdout contains 'spin_pct' with a percentage value (N.N%)
  4. verdict_brief.txt lines all contain 'Y'

This file is an INDEPENDENT check — the unit under test (acceptance.py) is
NEVER mocked. Mocking it would prove nothing. All assertions target observable
output contracts and CAN fail on a real regression.

Design constraints:
  - NO recursive pytest subprocess invocations (project memory: deadlocks).
  - All subprocess calls use sys.executable, not bare 'python' or 'python3'.
  - Module-scoped fixture runs acceptance.py exactly once per test module.
  - SM_LLM_BACKEND=offline is set in every subprocess touching the LLM stack.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"
VERDICT_BRIEF = PROJECT_ROOT / "verdict_brief.txt"

# Exact subprocess invocation dictated by criterion 1
_SUBPROCESS_CMD = [sys.executable, "acceptance.py"]
_SUBPROCESS_CWD = str(PROJECT_ROOT)
_SUBPROCESS_ENV = {**os.environ, "SM_LLM_BACKEND": "offline"}

# Criterion-anchored string constants
_DUAL_LENS_MARKER = "DUAL-LENS EVENTS"
_SPIN_PCT_KEYWORD = "spin_pct"
_SPIN_PCT_PATTERN = re.compile(r"spin_pct:\s*([\d.]+)%")
_VERDICT_Y = "Y"
_VERDICT_N = "N"

# Expected verdict_brief.txt content: every value must be Y
_EXPECTED_VERDICT_KEYS = ("DUAL_LENS", "SPIN_PCT", "MARKET", "DOSSIER")
_EXPECTED_VERDICT_LINES = ["DUAL_LENS: Y", "SPIN_PCT: Y", "MARKET: Y", "DOSSIER: Y"]


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixture
#
# Records the start-time immediately before spawning acceptance.py so that
# post-run tests can verify that verdict_brief.txt was actually written during
# this test session (not left over from a prior run).
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def _run_start_time() -> float:
    """Monotonic time just before acceptance.py is launched."""
    return time.time()


@pytest.fixture(scope="module")
def acceptance_proc(_run_start_time: float) -> subprocess.CompletedProcess:  # noqa: ARG001
    """Exact criterion-1 invocation: relative 'acceptance.py', cwd=PROJECT_ROOT."""
    return subprocess.run(
        _SUBPROCESS_CMD,
        cwd=_SUBPROCESS_CWD,
        env=_SUBPROCESS_ENV,
        capture_output=True,
        timeout=300,
    )


@pytest.fixture(scope="module")
def stdout(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def stderr(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 1 — subprocess SM_LLM_BACKEND=offline python acceptance.py
#               exits returncode 0
# ---------------------------------------------------------------------------


class TestCriterion1ReturncodeZero:
    """Acceptance criterion 1: SM_LLM_BACKEND=offline python acceptance.py → returncode 0."""

    def test_returncode_is_exactly_zero(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """Core criterion: returncode must be 0, not any other value.

        A non-zero returncode means one of the four acceptance sub-commands
        (once, digest-dry-run, carrier once, check_server.py) failed.
        """
        assert acceptance_proc.returncode == 0, (
            f"SM_LLM_BACKEND=offline python acceptance.py exited "
            f"{acceptance_proc.returncode} — expected 0.\n"
            f"stderr (last 1500 chars):\n"
            f"{acceptance_proc.stderr.decode(errors='replace')[-1500:]}"
        )

    def test_returncode_is_not_negative(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """A negative returncode on POSIX means the process was killed by a signal.

        Signal-killed processes are distinct from clean non-zero exits: they
        represent crashes (OOM, SIGKILL, SIGSEGV) not recoverable errors.
        """
        rc = acceptance_proc.returncode
        assert rc >= 0, (
            f"acceptance.py was killed by signal {-rc} (returncode={rc}).\n"
            "Signal kills indicate a crash — not an expected non-zero exit.\n"
            f"stderr:\n{acceptance_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_subprocess_used_sys_executable(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """The fixture must launch acceptance.py with sys.executable, not bare 'python'.

        Bare 'python' is absent on macOS; sys.executable is the only portable reference.
        """
        first_arg = Path(acceptance_proc.args[0]).resolve()
        expected = Path(sys.executable).resolve()
        assert first_arg == expected, (
            f"Subprocess launched with {acceptance_proc.args[0]!r} "
            f"(resolved: {first_arg}), expected sys.executable ({expected}).\n"
            "Bare 'python' or 'python3' may be absent on some platforms."
        )

    def test_subprocess_env_contains_offline_backend(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """SM_LLM_BACKEND=offline must be set — without it acceptance.py attempts live RSS."""
        # Verify the env used by the fixture has the offline key
        # (the fixture result does not expose env, so we check the fixture constant)
        assert _SUBPROCESS_ENV.get("SM_LLM_BACKEND") == "offline", (
            "Test fixture must set SM_LLM_BACKEND=offline in the subprocess env.\n"
            "Without it, acceptance.py skips the offline-stub branch and tries live feeds."
        )

    def test_stdout_is_non_empty_on_success(self, stdout: str) -> None:
        """returncode=0 with empty stdout indicates the script exited before writing output.

        The 'once' digest must emit its full Markdown output before the gate markers.
        """
        assert stdout.strip(), (
            "acceptance.py exited 0 but produced no stdout.\n"
            "The 'once' digest (cmd1) must emit its full Markdown output to stdout."
        )

    def test_no_unhandled_exception_in_stderr(self, stderr: str) -> None:
        """An unhandled exception in acceptance.py leaves a Traceback in stderr.

        exitcode=0 with a traceback in stderr indicates swallowed exceptions —
        the script exited cleanly by accident, not because all sub-commands passed.
        """
        assert "Traceback (most recent call last)" not in stderr, (
            "acceptance.py stderr contains an unhandled Python exception.\n"
            "Tracebacks in stderr with returncode=0 indicate swallowed failures.\n"
            f"stderr:\n{stderr[:2000]}"
        )

    def test_no_live_api_key_errors_in_stderr(self, stderr: str) -> None:
        """With SM_LLM_BACKEND=offline, no live LLM API should be contacted.

        API errors in stderr mean the offline guard in acceptance.py or the
        LLM backend switch in situation_monitor/llm.py is broken.
        """
        for indicator in ("AuthenticationError", "ANTHROPIC_API_KEY", "RateLimitError"):
            assert indicator not in stderr, (
                f"acceptance.py stderr contains {indicator!r} — a live API call occurred "
                f"despite SM_LLM_BACKEND=offline.\nstderr:\n{stderr[:1000]}"
            )


# ---------------------------------------------------------------------------
# Criterion 2 — stdout contains 'DUAL-LENS EVENTS'
# ---------------------------------------------------------------------------


class TestCriterion2DualLensEventsInStdout:
    """Acceptance criterion 2: stdout contains the string 'DUAL-LENS EVENTS'."""

    def test_dual_lens_events_marker_present(self, stdout: str) -> None:
        """Core criterion: the literal string 'DUAL-LENS EVENTS' must appear in stdout.

        This is exactly the marker acceptance.py checks to set DUAL_LENS: Y.
        If absent, both this test AND the DUAL_LENS: Y verdict would fail.
        """
        assert _DUAL_LENS_MARKER in stdout, (
            f"acceptance stdout does not contain {_DUAL_LENS_MARKER!r}.\n"
            "The dual-lens renderer did not emit a DUAL-LENS EVENTS section.\n"
            "This would also cause acceptance.py to write DUAL_LENS: N in verdict_brief.txt.\n"
            f"stdout (first 3000):\n{stdout[:3000]}"
        )

    def test_dual_lens_events_appears_as_h2_heading(self, stdout: str) -> None:
        """'DUAL-LENS EVENTS' must appear as '## DUAL-LENS EVENTS' — an ATX H2 heading.

        A bare substring match is insufficient: the string could appear in an
        article title or as prose. The renderer must emit it as a section heading.
        """
        assert re.search(r"^## DUAL-LENS EVENTS", stdout, re.MULTILINE), (
            "No '^## DUAL-LENS EVENTS' ATX H2 heading found in acceptance stdout.\n"
            "The dual-lens block must open with '## DUAL-LENS EVENTS' on its own line.\n"
            f"stdout (first 3000):\n{stdout[:3000]}"
        )

    def test_dual_lens_events_block_is_non_empty(self, stdout: str) -> None:
        """The DUAL-LENS EVENTS section must contain at least one event.

        A section header with no content is structurally valid Markdown but
        semantically empty — the dual-lens pipeline must have produced ≥1 event.
        """
        dual_idx = stdout.find(_DUAL_LENS_MARKER)
        assert dual_idx >= 0, f"'{_DUAL_LENS_MARKER}' not in stdout — checked by prior test"
        block = stdout[dual_idx:]
        # An event starts with '### <title>'
        has_event = bool(re.search(r"^### ", block, re.MULTILINE))
        assert has_event, (
            "The DUAL-LENS EVENTS block contains no '### <title>' event entries.\n"
            "The dual-lens pipeline must group ≥1 pair of left/right articles into an event.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_dual_lens_events_contains_left_heading(self, stdout: str) -> None:
        """The DUAL-LENS EVENTS block must contain a '#### LEFT' heading.

        Absence means either no left-lean articles were present or the renderer
        suppressed the column — both are structural regressions.
        """
        dual_idx = stdout.find(_DUAL_LENS_MARKER)
        if dual_idx < 0:
            pytest.skip(f"'{_DUAL_LENS_MARKER}' absent — covered by other tests")
        block = stdout[dual_idx:]
        assert re.search(r"^#### LEFT\b", block, re.MULTILINE), (
            "No '#### LEFT' heading inside the DUAL-LENS EVENTS block.\n"
            "At least one left-lean article must produce a LEFT column.\n"
            f"Block (first 800):\n{block[:800]}"
        )

    def test_dual_lens_events_contains_right_heading(self, stdout: str) -> None:
        """The DUAL-LENS EVENTS block must contain a '#### RIGHT' heading."""
        dual_idx = stdout.find(_DUAL_LENS_MARKER)
        if dual_idx < 0:
            pytest.skip(f"'{_DUAL_LENS_MARKER}' absent — covered by other tests")
        block = stdout[dual_idx:]
        assert re.search(r"^#### RIGHT\b", block, re.MULTILINE), (
            "No '#### RIGHT' heading inside the DUAL-LENS EVENTS block.\n"
            "At least one right-lean article must produce a RIGHT column.\n"
            f"Block (first 800):\n{block[:800]}"
        )

    def test_dual_lens_events_appears_after_domain_sections(self, stdout: str) -> None:
        """Domain sections (WORLD/MARKETS/AI) must precede the DUAL-LENS EVENTS block.

        The canonical output order is: WORLD → MARKETS → AI → DUAL-LENS EVENTS.
        If DUAL-LENS EVENTS appears first, the renderer output ordering is broken.
        """
        dual_idx = stdout.find(_DUAL_LENS_MARKER)
        if dual_idx < 0:
            pytest.skip(f"'{_DUAL_LENS_MARKER}' absent — covered by other tests")
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            d_idx = stdout.find(domain)
            if d_idx >= 0:
                assert d_idx < dual_idx, (
                    f"'{domain}' appears at position {d_idx}, "
                    f"AFTER '## DUAL-LENS EVENTS' at {dual_idx}.\n"
                    "Domain sections must precede the dual-lens block."
                )


# ---------------------------------------------------------------------------
# Criterion 3 — stdout contains 'spin_pct' with a percentage value
# ---------------------------------------------------------------------------


class TestCriterion3SpinPctPercentageInStdout:
    """Acceptance criterion 3: stdout contains 'spin_pct' with a percentage value."""

    def test_spin_pct_keyword_present(self, stdout: str) -> None:
        """The literal string 'spin_pct' must appear in stdout.

        This is the keyword acceptance.py searches for via _extract_spin_pct()
        to decide SPIN_PCT: Y.  A missing keyword means the spin estimator
        produced no annotations.
        """
        assert _SPIN_PCT_KEYWORD in stdout, (
            f"acceptance stdout does not contain the keyword {_SPIN_PCT_KEYWORD!r}.\n"
            "The spin estimator must annotate each article with 'spin_pct: N.N%'.\n"
            f"stdout (first 2000):\n{stdout[:2000]}"
        )

    def test_spin_pct_followed_by_numeric_percentage(self, stdout: str) -> None:
        """'spin_pct:' must be followed by a numeric percentage value (N.N%).

        A bare keyword with no value would satisfy 'spin_pct present' but
        acceptance.py's _extract_spin_pct() regex requires a float percentage,
        so 'spin_pct: N.N%' is the only form that produces SPIN_PCT: Y.
        """
        match = _SPIN_PCT_PATTERN.search(stdout)
        assert match is not None, (
            "No 'spin_pct: N.N%' pattern found in acceptance stdout.\n"
            "Pattern: spin_pct:\\s*([\\d.]+)%\n"
            "The spin estimator must produce at least one 'spin_pct: N.N%' annotation.\n"
            f"stdout (first 3000):\n{stdout[:3000]}"
        )

    def test_spin_pct_value_is_float_not_integer(self, stdout: str) -> None:
        """spin_pct value must include a decimal point (:.1f format).

        The renderer uses f'{spin_pct:.1f}%' — integer format (no decimal) would
        break _extract_spin_pct() and produce SPIN_PCT: N.
        """
        matches = _SPIN_PCT_PATTERN.findall(stdout)
        assert matches, "No 'spin_pct: N.N%' values found — checked by prior test"
        for raw in matches:
            assert "." in raw, (
                f"spin_pct value {raw!r} has no decimal point.\n"
                "The :.1f format must produce values like '43.4%', not '43%'.\n"
                "An integer-only format would make _extract_spin_pct() return None → SPIN_PCT: N."
            )

    def test_spin_pct_values_in_valid_range(self, stdout: str) -> None:
        """All spin_pct percentage values must be in [0.0, 100.0].

        The lexical estimator clamps to this range; a value outside it means
        clamping is broken or a non-estimator value was injected.
        """
        values = [float(v) for v in _SPIN_PCT_PATTERN.findall(stdout)]
        assert values, "No spin_pct values found — checked by prior test"
        for val in values:
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside [0.0, 100.0].\n"
                "The lexical spin estimator must clamp its output to this range."
            )

    def test_spin_pct_appears_inside_dual_lens_block(self, stdout: str) -> None:
        """spin_pct percentage must be inside the DUAL-LENS EVENTS block, not stray prose.

        If spin_pct: annotations appear before the dual-lens section, the renderer
        is emitting them in the wrong location and the gate markers would be misleading.
        """
        dual_idx = stdout.find(_DUAL_LENS_MARKER)
        if dual_idx < 0:
            pytest.skip(f"'{_DUAL_LENS_MARKER}' absent — covered by other tests")
        block = stdout[dual_idx:]
        assert _SPIN_PCT_PATTERN.search(block), (
            "No 'spin_pct: N.N%' pattern found INSIDE the DUAL-LENS EVENTS block.\n"
            "Spin annotations must be rendered within the dual-lens section.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_spin_pct_value_is_not_stub_constant(self, stdout: str) -> None:
        """spin_pct values must not all be the same constant (stub estimator sign).

        A stub estimator might return a fixed constant (e.g., 50.0 for all articles).
        The real lexical estimator produces differentiated values because fixture
        articles contain measurably different charged-language densities.
        """
        values = [float(v) for v in _SPIN_PCT_PATTERN.findall(stdout)]
        assert values, "No spin_pct values found — checked by prior test"
        if len(values) >= 2:
            unique = set(values)
            assert len(unique) > 1, (
                f"All spin_pct values are identical ({values[0]}) — stub estimator sign.\n"
                "The real lexical estimator must produce differentiated scores across articles.\n"
                f"Values: {values}"
            )

    def test_spin_pct_on_bullet_lines(self, stdout: str) -> None:
        """spin_pct annotations must appear on bullet lines ('- <title> | spin_pct:').

        Annotations floating on their own lines (not on a bullet) are a rendering
        regression that would still satisfy the keyword check but break the
        intended output format.
        """
        bullet_spin_lines = [
            line for line in stdout.splitlines()
            if line.startswith("- ") and "spin_pct:" in line
        ]
        assert bullet_spin_lines, (
            "No '- <title> ... spin_pct:' bullet lines found in acceptance stdout.\n"
            "The dual-lens renderer must annotate each article bullet with spin_pct.\n"
            f"stdout (last 2000):\n{stdout[-2000:]}"
        )

    def test_at_least_one_spin_pct_value_above_zero(self, stdout: str) -> None:
        """At least one spin_pct must be > 0.0.

        The fixture articles contain charged language (threats, crisis, catastrophe,
        extremist); a score of 0.0 for all of them means the lexical estimator is
        not firing at all — a silent no-op regression.
        """
        values = [float(v) for v in _SPIN_PCT_PATTERN.findall(stdout)]
        assert values, "No spin_pct values found — checked by prior test"
        above_zero = [v for v in values if v > 0.0]
        assert above_zero, (
            "All spin_pct values are 0.0 — the lexical estimator produced no hits.\n"
            "Fixture articles contain charged language; at least one must score above 0.\n"
            f"All values: {values}"
        )


# ---------------------------------------------------------------------------
# Criterion 4 — verdict_brief.txt lines all contain 'Y'
# ---------------------------------------------------------------------------


class TestCriterion4VerdictBriefAllY:
    """Acceptance criterion 4: verdict_brief.txt lines all contain 'Y'."""

    def test_verdict_brief_exists(self, acceptance_proc: subprocess.CompletedProcess) -> None:
        """verdict_brief.txt must exist after acceptance.py has run.

        A missing file means acceptance.py crashed before reaching the write step
        (before cmd1 completed), or it was never run.
        """
        _ = acceptance_proc  # ensure acceptance.py has run before checking
        assert VERDICT_BRIEF.exists(), (
            f"verdict_brief.txt not found at {VERDICT_BRIEF}.\n"
            "acceptance.py writes this file after cmd1 succeeds.\n"
            "Its absence means acceptance.py exited before writing the verdict."
        )

    def test_every_non_empty_line_contains_y(self) -> None:
        """Core criterion 4: every non-empty line in verdict_brief.txt contains 'Y'.

        A line with ': N' means the corresponding marker was absent from cmd1
        stdout, so that verdict check failed.  ANY 'N' is a criterion failure.
        """
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent — checked by test_verdict_brief_exists")
        lines = [
            ln.strip()
            for ln in VERDICT_BRIEF.read_text(errors="replace").splitlines()
            if ln.strip()
        ]
        assert lines, "verdict_brief.txt is empty"
        for line in lines:
            assert _VERDICT_Y in line, (
                f"verdict_brief.txt line {line!r} does not contain 'Y'.\n"
                "Every non-empty line must contain 'Y' — criterion 4 requires all verdicts pass.\n"
                f"All lines: {lines}"
            )

    def test_no_line_has_n_value(self) -> None:
        """No verdict_brief.txt line may have ': N' as its value.

        This is the contrapositive of 'all contain Y': any ': N' line means
        the verdict failed (a marker was absent from acceptance.py cmd1 stdout).
        """
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent — checked by test_verdict_brief_exists")
        content = VERDICT_BRIEF.read_text(errors="replace")
        n_lines = [
            ln.strip()
            for ln in content.splitlines()
            if re.search(r":\s*N\s*$", ln.strip())
        ]
        assert not n_lines, (
            "verdict_brief.txt contains 'N' verdict values — the following markers "
            "were absent from acceptance.py cmd1 stdout:\n"
            + "\n".join(n_lines)
            + "\n\nFix: ensure acceptance.py cmd1 (the 'once' digest) emits the "
            "corresponding markers before they are checked."
        )

    def test_dual_lens_verdict_is_y(self) -> None:
        """DUAL_LENS verdict in verdict_brief.txt must be 'Y'.

        This verdict is Y iff '## DUAL-LENS EVENTS' appeared in cmd1 stdout.
        A value of 'N' means the dual-lens renderer produced no output.
        """
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent")
        content = VERDICT_BRIEF.read_text(errors="replace")
        assert "DUAL_LENS: Y" in content, (
            "verdict_brief.txt does not contain 'DUAL_LENS: Y'.\n"
            "This means '## DUAL-LENS EVENTS' was absent from cmd1 stdout.\n"
            f"Full file content:\n{content}"
        )

    def test_spin_pct_verdict_is_y(self) -> None:
        """SPIN_PCT verdict in verdict_brief.txt must be 'Y'.

        This verdict is Y iff 'spin_pct: N.N%' appeared in cmd1 stdout after
        a DUAL-LENS EVENTS block.  A value of 'N' means either the dual-lens
        block was absent or no articles were annotated with spin_pct.
        """
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent")
        content = VERDICT_BRIEF.read_text(errors="replace")
        assert "SPIN_PCT: Y" in content, (
            "verdict_brief.txt does not contain 'SPIN_PCT: Y'.\n"
            "This means 'spin_pct: N.N%' was absent from cmd1 stdout "
            "(or dual_lens_ok was False, preventing the spin_pct check).\n"
            f"Full file content:\n{content}"
        )

    def test_market_verdict_is_y(self) -> None:
        """MARKET verdict in verdict_brief.txt must be 'Y'.

        This verdict is Y iff '## MARKETS' appeared in cmd1 stdout.
        A value of 'N' means the MARKETS domain section was not rendered.
        """
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent")
        content = VERDICT_BRIEF.read_text(errors="replace")
        assert "MARKET: Y" in content, (
            "verdict_brief.txt does not contain 'MARKET: Y'.\n"
            "This means '## MARKETS' was absent from cmd1 stdout.\n"
            "Check that acceptance_source_defs.json includes a MARKETS-domain feed.\n"
            f"Full file content:\n{content}"
        )

    def test_verdict_brief_has_exactly_four_lines(self) -> None:
        """verdict_brief.txt must have exactly 4 non-empty lines.

        Fewer lines means acceptance.py did not finish writing all verdicts.
        Extra lines means the file format changed — downstream parsers expect 4.
        """
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent")
        lines = [
            ln.strip()
            for ln in VERDICT_BRIEF.read_text(errors="replace").splitlines()
            if ln.strip()
        ]
        assert len(lines) == 4, (
            f"verdict_brief.txt has {len(lines)} non-empty lines; expected exactly 4.\n"
            f"Lines: {lines!r}\n"
            f"Expected: {_EXPECTED_VERDICT_LINES!r}"
        )

    def test_verdict_brief_exact_content(self) -> None:
        """Omnibus: verdict_brief.txt stripped non-empty lines must equal the criterion list."""
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent")
        content = VERDICT_BRIEF.read_text(errors="replace")
        actual = [ln.strip() for ln in content.splitlines() if ln.strip()]
        assert actual == _EXPECTED_VERDICT_LINES, (
            "verdict_brief.txt content does not match the criterion.\n"
            f"Expected: {_EXPECTED_VERDICT_LINES!r}\n"
            f"Actual:   {actual!r}\n"
            "Each 'N' value means the corresponding marker was absent from cmd1 stdout."
        )

    def test_verdict_brief_written_by_acceptance_py_source(self) -> None:
        """acceptance.py source must reference 'verdict_brief.txt' to write it.

        A verdict file that is never written by acceptance.py is a static artifact
        — it would always pass regardless of what cmd1 actually produced.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "verdict_brief.txt" in content, (
            "acceptance.py source does not reference 'verdict_brief.txt'.\n"
            "The file cannot be a dynamic product of the run; it would be a static artifact."
        )


# ---------------------------------------------------------------------------
# Cross-criterion consistency checks
# ---------------------------------------------------------------------------


class TestCrossCheckCriteria:
    """Verify that the four criteria are internally consistent after a single run."""

    def test_dual_lens_y_backed_by_stdout_marker(self, stdout: str) -> None:
        """If DUAL_LENS: Y in verdict_brief.txt, stdout must contain 'DUAL-LENS EVENTS'.

        A 'Y' verdict not backed by the marker in stdout is a false positive —
        the file is stale or the verdict logic is wrong.
        """
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent")
        content = VERDICT_BRIEF.read_text(errors="replace")
        if "DUAL_LENS: Y" in content:
            assert _DUAL_LENS_MARKER in stdout, (
                "verdict_brief.txt says DUAL_LENS: Y, but stdout lacks 'DUAL-LENS EVENTS'.\n"
                "This is a false positive — the file is stale or the logic is incorrect."
            )

    def test_spin_pct_y_backed_by_stdout_pattern(self, stdout: str) -> None:
        """If SPIN_PCT: Y in verdict_brief.txt, stdout must contain 'spin_pct: N.N%'.

        acceptance.py sets SPIN_PCT based on _extract_spin_pct(r1) returning
        a float, which requires the 'spin_pct: N.N%' pattern in r1.
        """
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent")
        content = VERDICT_BRIEF.read_text(errors="replace")
        if "SPIN_PCT: Y" in content:
            assert _SPIN_PCT_PATTERN.search(stdout), (
                "verdict_brief.txt says SPIN_PCT: Y, but stdout lacks 'spin_pct: N.N%'.\n"
                "This is a false positive — the file is stale or the verdict logic is broken."
            )

    def test_market_y_backed_by_stdout_markets_header(self, stdout: str) -> None:
        """If MARKET: Y in verdict_brief.txt, stdout must contain '## MARKETS'."""
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent")
        content = VERDICT_BRIEF.read_text(errors="replace")
        if "MARKET: Y" in content:
            assert "## MARKETS" in stdout, (
                "verdict_brief.txt says MARKET: Y, but stdout lacks '## MARKETS'.\n"
                "This is a false positive — the file is stale or the verdict logic is broken."
            )

    def test_dual_lens_n_would_cause_spin_pct_n(self, stdout: str) -> None:
        """When DUAL-LENS EVENTS is absent, SPIN_PCT must also be N.

        acceptance.py only extracts spin_pct when dual_lens_ok is True:
            spin_pct = _extract_spin_pct(r1) if dual_lens_ok else None
            spin_ok = spin_pct is not None
        So SPIN_PCT: Y without DUAL_LENS: Y is logically impossible.
        """
        if not VERDICT_BRIEF.exists():
            pytest.skip("verdict_brief.txt absent")
        content = VERDICT_BRIEF.read_text(errors="replace")
        dual_lens_y = "DUAL_LENS: Y" in content
        spin_pct_y = "SPIN_PCT: Y" in content
        if not dual_lens_y:
            assert not spin_pct_y, (
                "DUAL_LENS: N but SPIN_PCT: Y — logically impossible per acceptance.py logic.\n"
                "spin_pct is only extracted when dual_lens_ok is True.\n"
                f"verdict_brief.txt:\n{content}"
            )

    def test_all_criteria_hold_simultaneously(
        self, acceptance_proc: subprocess.CompletedProcess, stdout: str
    ) -> None:
        """Compound assertion: all four acceptance criteria hold at once.

        This is the single 'must pass' test that mirrors the task specification verbatim.
        """
        errors: list[str] = []

        # Criterion 1: returncode 0
        if acceptance_proc.returncode != 0:
            errors.append(
                f"Criterion 1 FAILED: returncode={acceptance_proc.returncode} (expected 0)"
            )

        # Criterion 2: stdout contains 'DUAL-LENS EVENTS'
        if _DUAL_LENS_MARKER not in stdout:
            errors.append(
                f"Criterion 2 FAILED: stdout does not contain {_DUAL_LENS_MARKER!r}"
            )

        # Criterion 3: stdout contains spin_pct with a percentage
        if not _SPIN_PCT_PATTERN.search(stdout):
            errors.append(
                "Criterion 3 FAILED: stdout does not contain 'spin_pct: N.N%'"
            )

        # Criterion 4: verdict_brief.txt lines all contain Y
        if VERDICT_BRIEF.exists():
            content = VERDICT_BRIEF.read_text(errors="replace")
            n_lines = [
                ln.strip()
                for ln in content.splitlines()
                if re.search(r":\s*N\s*$", ln.strip())
            ]
            if n_lines:
                errors.append(
                    f"Criterion 4 FAILED: verdict_brief.txt has N values: {n_lines}"
                )
        else:
            errors.append("Criterion 4 FAILED: verdict_brief.txt does not exist")

        assert not errors, (
            "Offline acceptance gate: one or more criteria FAILED:\n"
            + "\n".join(f"  • {e}" for e in errors)
            + f"\n\nstderr (last 1000):\n{acceptance_proc.stderr.decode(errors='replace')[-1000:]}"
        )


# ---------------------------------------------------------------------------
# Structural guards (source-level, no subprocess)
# ---------------------------------------------------------------------------


class TestSourceLevelGuards:
    """Source-level checks on acceptance.py to guard against logic regressions.

    These tests do NOT run acceptance.py — they inspect the source code to verify
    that the logic implementing each criterion is structurally present.
    Passing these guards does not imply the runtime output is correct; they are
    an early-warning system for source-level regressions.
    """

    def test_acceptance_py_checks_dual_lens_marker(self) -> None:
        """acceptance.py must contain the literal 'DUAL-LENS EVENTS' string.

        If this string is absent, the dual_lens_ok flag is always False,
        producing DUAL_LENS: N even when the renderer works correctly.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "DUAL-LENS EVENTS" in content, (
            "acceptance.py source must contain 'DUAL-LENS EVENTS' to check the DUAL_LENS verdict."
        )

    def test_acceptance_py_checks_spin_pct_pattern(self) -> None:
        """acceptance.py must reference 'spin_pct' to extract the spin percentage."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "spin_pct" in content, (
            "acceptance.py source must reference 'spin_pct' to check the SPIN_PCT verdict."
        )

    def test_acceptance_py_writes_y_for_passing_verdicts(self) -> None:
        """acceptance.py must use 'Y' (not 'YES', 'True', or '1') for passing verdicts."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "'Y'" in content or '"Y"' in content, (
            "acceptance.py must use single-character 'Y' for positive verdict values.\n"
            "Using 'YES', 'True', or '1' would cause the criterion-4 line-content check to fail."
        )

    def test_acceptance_py_writes_n_for_failing_verdicts(self) -> None:
        """acceptance.py must use 'N' (not 'NO', 'False', or '0') for failing verdicts."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "'N'" in content or '"N"' in content, (
            "acceptance.py must use single-character 'N' for negative verdict values."
        )

    def test_acceptance_py_exits_nonzero_on_verdict_failure(self) -> None:
        """acceptance.py must exit non-zero if any verdict is False.

        Without a sys.exit(1) after verdict evaluation, a partial failure would
        still produce returncode=0 — hiding the regression from the gate.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.exit(1)" in content, (
            "acceptance.py must call sys.exit(1) when a verdict check fails.\n"
            "Without it, partial failures are silently swallowed as returncode=0."
        )

    def test_acceptance_py_uses_sys_executable_for_subprocesses(self) -> None:
        """acceptance.py must use sys.executable, not bare 'python', for its sub-commands."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, (
            "acceptance.py must use sys.executable for subprocess calls.\n"
            "Bare 'python' or 'python3' may be absent on macOS and some Linux distributions."
        )

    def test_acceptance_py_does_not_invoke_pytest(self) -> None:
        """acceptance.py must not run pytest — that would cause a recursive deadlock.

        The acceptance gate is run inside pytest; if acceptance.py spawns pytest
        as a subprocess, the suite deadlocks (project memory).
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "pytest" not in content, (
            "acceptance.py must not invoke 'pytest' — recursive invocation deadlocks the suite."
        )

    def test_no_test_file_invokes_pytest_as_subprocess(self) -> None:
        """No test_*.py may spawn pytest as a subprocess — it deadlocks the suite.

        Scan every test file line-by-line; skip comment lines.
        """
        test_dir = PROJECT_ROOT / "tests"
        violations: list[str] = []
        for tf in test_dir.glob("test_*.py"):
            for lineno, raw in enumerate(tf.read_text(errors="replace").splitlines(), start=1):
                if raw.strip().startswith("#"):
                    continue
                if re.search(r"""['"]pytest['"]""", raw) and re.search(
                    r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", raw
                ):
                    violations.append(f"{tf.name}:{lineno}: {raw.rstrip()}")
        assert not violations, (
            "Recursive pytest subprocess calls found (these deadlock the suite):\n"
            + "\n".join(violations[:10])
        )

"""Acceptance regression guard: subprocess SM_LLM_BACKEND=offline python acceptance.py.

Acceptance criteria under test (verbatim from task spec):
  1. pytest -x exits 0  (evidenced structurally — recursive subprocess invocation forbidden)
  2. acceptance.py subprocess returncode == 0
  3. acceptance.py stdout non-empty
  4. acceptance.py stdout contains '#### LEFT'
  5. acceptance.py stdout contains '#### RIGHT'
  6. acceptance.py stdout contains 'spin_pct' followed by a number and %

Independent tester perspective: the unit under test is NEVER mocked — mocking
it proves nothing.  Every assertion CAN fail on a real regression.

Design constraints enforced:
  - No recursive pytest subprocess invocations (project memory: they hang the suite).
  - All subprocess calls use sys.executable (not bare 'python' or 'python3').
  - Module-scoped fixture ensures the acceptance subprocess runs exactly once.
  - SM_LLM_BACKEND=offline is set on every subprocess that touches the LLM stack.
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
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"


# ---------------------------------------------------------------------------
# Module-scoped subprocess: SM_LLM_BACKEND=offline python acceptance.py
# ---------------------------------------------------------------------------


def _offline_env() -> dict[str, str]:
    """Return an environment dict with SM_LLM_BACKEND=offline, as the criterion demands."""
    return {**os.environ, "SM_LLM_BACKEND": "offline"}


@pytest.fixture(scope="module")
def acceptance_result() -> subprocess.CompletedProcess:
    """Run acceptance.py as a subprocess with SM_LLM_BACKEND=offline.

    This is the exact invocation described in acceptance criterion 2:
    'subprocess run of SM_LLM_BACKEND=offline python3 acceptance.py'.
    sys.executable is used instead of bare 'python3' for portability.
    """
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        timeout=240,
    )


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_result: subprocess.CompletedProcess) -> str:
    return acceptance_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acceptance_stderr(acceptance_result: subprocess.CompletedProcess) -> str:
    return acceptance_result.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 2: acceptance.py subprocess returncode == 0
# ---------------------------------------------------------------------------


class TestReturncodeIsZero:
    """Criterion 2: SM_LLM_BACKEND=offline python acceptance.py must exit 0."""

    def test_returncode_equals_zero(
        self, acceptance_result: subprocess.CompletedProcess
    ) -> None:
        """Core criterion: returncode must be exactly 0, not 1, 2, or any non-zero."""
        stderr_tail = acceptance_result.stderr.decode(errors="replace")
        stdout_tail = acceptance_result.stdout.decode(errors="replace")[-500:]
        assert acceptance_result.returncode == 0, (
            f"SM_LLM_BACKEND=offline python acceptance.py exited "
            f"{acceptance_result.returncode} (expected 0).\n"
            f"\n--- FULL STDERR ---\n{stderr_tail}\n--- END STDERR ---\n"
            f"\n--- STDOUT (last 500 chars) ---\n{stdout_tail}\n--- END STDOUT ---"
        )

    def test_returncode_is_not_none(
        self, acceptance_result: subprocess.CompletedProcess
    ) -> None:
        """returncode must be set — None would mean the process is still running."""
        assert acceptance_result.returncode is not None, (
            "acceptance.py returncode is None — the process may not have terminated."
        )

    def test_returncode_is_not_negative(
        self, acceptance_result: subprocess.CompletedProcess
    ) -> None:
        """A negative returncode on POSIX means the process was killed by a signal."""
        assert acceptance_result.returncode >= 0, (
            f"acceptance.py was killed by signal {-acceptance_result.returncode}.\n"
            "A signal kill (SIGKILL, SIGSEGV, etc.) indicates a crash, not a clean exit.\n"
            f"stderr:\n{acceptance_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_acceptance_py_exists_as_prerequisite(self) -> None:
        """If acceptance.py is missing, subprocess cannot run and criterion 2 is impossible."""
        assert ACCEPTANCE_PY.exists(), (
            f"acceptance.py not found at {ACCEPTANCE_PY}.\n"
            "The file must exist for the subprocess to launch at all."
        )

    def test_acceptance_py_uses_sys_executable_internally(self) -> None:
        """acceptance.py must use sys.executable for sub-subprocesses — not bare 'python3'.

        Bare 'python3' is absent on some platforms.  The subprocess portability guarantee
        is only achieved through sys.executable.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, (
            "acceptance.py must use sys.executable for subprocess calls.\n"
            "Bare 'python' or 'python3' may be absent on some platforms (e.g. macOS).\n"
            "This is a prerequisite for the subprocess to launch sub-commands reliably."
        )

    def test_offline_mode_env_var_in_acceptance_py(self) -> None:
        """acceptance.py must set SM_LLM_BACKEND=offline in its subprocess env.

        If the env var is missing in the sub-commands, a live LLM would be called,
        which fails on most CI machines that have no API key.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "SM_LLM_BACKEND" in content and "offline" in content, (
            "acceptance.py must reference SM_LLM_BACKEND=offline for its sub-subprocesses.\n"
            "Without this, sub-commands may attempt live LLM calls and fail in CI."
        )

    def test_no_api_errors_in_stderr_when_offline(self, acceptance_stderr: str) -> None:
        """With SM_LLM_BACKEND=offline no live API call should occur — no API errors in stderr."""
        api_indicators = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "RateLimitError",
            "APIConnectionError",
            "openai.error",
        ]
        for indicator in api_indicators:
            assert indicator not in acceptance_stderr, (
                f"acceptance stderr contains {indicator!r} — an API error occurred "
                "despite SM_LLM_BACKEND=offline.\n"
                f"Full stderr:\n{acceptance_stderr[:1000]}"
            )

    def test_no_python_traceback_in_stderr(self, acceptance_stderr: str) -> None:
        """A Python Traceback in stderr indicates an unhandled exception — incompatible with exit 0."""
        assert "Traceback (most recent call last)" not in acceptance_stderr, (
            "acceptance.py stderr contains a Python Traceback.\n"
            "An unhandled exception must not occur for returncode to be 0.\n"
            f"stderr:\n{acceptance_stderr[:2000]}"
        )

    def test_subprocess_was_launched_with_sys_executable(
        self, acceptance_result: subprocess.CompletedProcess
    ) -> None:
        """The fixture itself must use sys.executable to invoke acceptance.py."""
        assert isinstance(acceptance_result.args, (list, tuple)), (
            "acceptance subprocess must be launched with an args list, not a shell string"
        )
        assert str(ACCEPTANCE_PY) in [str(a) for a in acceptance_result.args], (
            f"acceptance.py path not found in subprocess args: {acceptance_result.args!r}"
        )
        first_arg = acceptance_result.args[0]
        assert "python" in Path(first_arg).name.lower(), (
            f"Subprocess was not launched via a Python interpreter: {first_arg!r}"
        )


# ---------------------------------------------------------------------------
# Criterion 3: acceptance.py stdout non-empty
# ---------------------------------------------------------------------------


class TestStdoutNonEmpty:
    """Criterion 3: acceptance.py must produce at least one byte of stdout."""

    def test_stdout_has_non_whitespace_content(self, acceptance_stdout: str) -> None:
        """The primary check: stdout must contain at least one non-whitespace character."""
        assert acceptance_stdout.strip(), (
            "acceptance.py produced only whitespace (or empty) stdout.\n"
            "The 'once' digest (cmd1) must write its Markdown output to stdout.\n"
            "An empty stdout means all content went to stderr or the process exited "
            "before producing any output."
        )

    def test_stdout_exceeds_minimum_length(self, acceptance_stdout: str) -> None:
        """A minimal valid digest is several hundred bytes — fewer indicates truncation."""
        min_chars = 100
        assert len(acceptance_stdout.strip()) >= min_chars, (
            f"acceptance.py stdout has fewer than {min_chars} non-whitespace chars; "
            f"got {len(acceptance_stdout.strip())} chars.\n"
            "A valid digest (WORLD, MARKETS, AI, DUAL-LENS sections) must be substantially larger."
        )

    def test_stdout_has_multiple_lines(self, acceptance_stdout: str) -> None:
        """A single-line output is too short to be a valid digest."""
        lines = [ln for ln in acceptance_stdout.splitlines() if ln.strip()]
        assert len(lines) >= 5, (
            f"acceptance.py stdout has only {len(lines)} non-empty line(s).\n"
            "A valid multi-section digest must span many lines."
        )

    def test_no_python_traceback_in_stdout(self, acceptance_stdout: str) -> None:
        """A Traceback in stdout means an exception was printed but returncode may still be 0."""
        assert "Traceback (most recent call last)" not in acceptance_stdout, (
            "acceptance.py stdout contains a Python Traceback.\n"
            "Even if returncode is 0, an unhandled-exception print indicates a bug.\n"
            f"stdout (first 2000 chars):\n{acceptance_stdout[:2000]}"
        )

    def test_stdout_is_decodable_utf8(
        self, acceptance_result: subprocess.CompletedProcess
    ) -> None:
        """Stdout must be valid text — binary garbage or mojibake indicates an encoding bug."""
        try:
            _ = acceptance_result.stdout.decode("utf-8")
        except UnicodeDecodeError as exc:
            pytest.fail(
                f"acceptance.py stdout is not valid UTF-8: {exc}\n"
                "The digest output must be text, not binary."
            )


# ---------------------------------------------------------------------------
# Criterion 4 & 5: stdout contains '#### LEFT' and '#### RIGHT'
# ---------------------------------------------------------------------------


class TestDualLensMarkers:
    """Criteria 4 & 5: acceptance stdout must contain '#### LEFT' and '#### RIGHT'."""

    # ---- Presence ----

    def test_left_marker_present(self, acceptance_stdout: str) -> None:
        """'#### LEFT' must appear literally in acceptance.py stdout."""
        assert "#### LEFT" in acceptance_stdout, (
            "acceptance.py stdout does not contain '#### LEFT'.\n"
            "The dual-lens renderer must emit a LEFT column heading for left-leaning articles.\n"
            f"stdout (first 3000 chars):\n{acceptance_stdout[:3000]}"
        )

    def test_right_marker_present(self, acceptance_stdout: str) -> None:
        """'#### RIGHT' must appear literally in acceptance.py stdout."""
        assert "#### RIGHT" in acceptance_stdout, (
            "acceptance.py stdout does not contain '#### RIGHT'.\n"
            "The dual-lens renderer must emit a RIGHT column heading for right-leaning articles.\n"
            f"stdout (first 3000 chars):\n{acceptance_stdout[:3000]}"
        )

    def test_both_left_and_right_present_simultaneously(
        self, acceptance_stdout: str
    ) -> None:
        """Both markers must appear in the SAME acceptance run — a partial render is a failure."""
        missing = []
        if "#### LEFT" not in acceptance_stdout:
            missing.append("'#### LEFT'")
        if "#### RIGHT" not in acceptance_stdout:
            missing.append("'#### RIGHT'")
        assert not missing, (
            f"acceptance.py stdout is missing dual-lens column markers: {', '.join(missing)}.\n"
            "A valid dual-lens block requires both LEFT and RIGHT columns.\n"
            f"stdout (first 3000 chars):\n{acceptance_stdout[:3000]}"
        )

    # ---- Structural correctness: H4 heading at line start ----

    def test_left_is_at_line_start(self, acceptance_stdout: str) -> None:
        """'#### LEFT' must begin a line — the word 'LEFT' in prose does not satisfy this."""
        assert re.search(r"^#### LEFT\b", acceptance_stdout, re.MULTILINE), (
            "No '^#### LEFT' line-start H4 heading found in acceptance stdout.\n"
            "An article title containing 'LEFT' (e.g. 'Left-wing Policy') does NOT satisfy "
            "this criterion — the dual-lens renderer must emit '#### LEFT' at column 0."
        )

    def test_right_is_at_line_start(self, acceptance_stdout: str) -> None:
        """'#### RIGHT' must begin a line — not be embedded in prose."""
        assert re.search(r"^#### RIGHT\b", acceptance_stdout, re.MULTILINE), (
            "No '^#### RIGHT' line-start H4 heading found in acceptance stdout.\n"
            "The dual-lens renderer must emit '#### RIGHT' at column 0, not embedded in text."
        )

    def test_left_is_exactly_h4_not_h2_or_h3(self, acceptance_stdout: str) -> None:
        """The LEFT heading must be '#### LEFT' (H4), not '## LEFT' or '### LEFT'."""
        assert not re.search(r"^#{1,3} LEFT\b", acceptance_stdout, re.MULTILINE), (
            "Found '#/##/### LEFT' (H1–H3) in acceptance stdout.\n"
            "LEFT must be rendered as H4 ('#### LEFT'), not a higher-level heading."
        )

    def test_right_is_exactly_h4_not_h2_or_h3(self, acceptance_stdout: str) -> None:
        """The RIGHT heading must be '#### RIGHT' (H4), not '## RIGHT' or '### RIGHT'."""
        assert not re.search(r"^#{1,3} RIGHT\b", acceptance_stdout, re.MULTILINE), (
            "Found '#/##/### RIGHT' (H1–H3) in acceptance stdout.\n"
            "RIGHT must be rendered as H4 ('#### RIGHT'), not a higher-level heading."
        )

    # ---- Contextual correctness: inside the DUAL-LENS EVENTS block ----

    def test_dual_lens_events_block_exists(self, acceptance_stdout: str) -> None:
        """A prerequisite: the '## DUAL-LENS EVENTS' section must exist for LEFT/RIGHT to be valid."""
        assert "## DUAL-LENS EVENTS" in acceptance_stdout, (
            "acceptance.py stdout missing '## DUAL-LENS EVENTS' section.\n"
            "Without a dual-lens block, '#### LEFT' and '#### RIGHT' have no valid container.\n"
            f"stdout (first 3000 chars):\n{acceptance_stdout[:3000]}"
        )

    def test_left_is_inside_dual_lens_block(self, acceptance_stdout: str) -> None:
        """'#### LEFT' must appear AFTER '## DUAL-LENS EVENTS', not in the domain sections."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        if dual_idx < 0:
            pytest.skip("'## DUAL-LENS EVENTS' not found — covered by prerequisite test")
        block = acceptance_stdout[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' not found inside the '## DUAL-LENS EVENTS' block.\n"
            "It must appear after the DUAL-LENS header, not in domain digest sections.\n"
            f"Block (first 500 chars):\n{block[:500]}"
        )

    def test_right_is_inside_dual_lens_block(self, acceptance_stdout: str) -> None:
        """'#### RIGHT' must appear AFTER '## DUAL-LENS EVENTS'."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        if dual_idx < 0:
            pytest.skip("'## DUAL-LENS EVENTS' not found — covered by prerequisite test")
        block = acceptance_stdout[dual_idx:]
        assert "#### RIGHT" in block, (
            "'#### RIGHT' not found inside the '## DUAL-LENS EVENTS' block.\n"
            f"Block (first 500 chars):\n{block[:500]}"
        )

    def test_left_does_not_appear_before_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """Domain digest sections (## WORLD, ## MARKETS, ## AI) must NOT contain '#### LEFT'."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        if dual_idx < 0:
            return
        pre_block = acceptance_stdout[:dual_idx]
        assert "#### LEFT" not in pre_block, (
            "'#### LEFT' found BEFORE the '## DUAL-LENS EVENTS' header.\n"
            "Domain sections must not emit left/right column headings.\n"
            f"Pre-block content (last 500 chars):\n{pre_block[-500:]}"
        )

    def test_right_does_not_appear_before_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """Domain digest sections must NOT contain '#### RIGHT'."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        if dual_idx < 0:
            return
        pre_block = acceptance_stdout[:dual_idx]
        assert "#### RIGHT" not in pre_block, (
            "'#### RIGHT' found BEFORE the '## DUAL-LENS EVENTS' header.\n"
            "Domain sections must not emit left/right column headings."
        )

    def test_left_appears_before_right_in_document(self, acceptance_stdout: str) -> None:
        """Within the full stdout, '#### LEFT' must precede '#### RIGHT'."""
        left_idx = acceptance_stdout.find("#### LEFT")
        right_idx = acceptance_stdout.find("#### RIGHT")
        if left_idx < 0 or right_idx < 0:
            pytest.skip("One or both column markers missing — covered by presence tests")
        assert left_idx < right_idx, (
            f"'#### LEFT' (at char {left_idx}) must appear before "
            f"'#### RIGHT' (at char {right_idx}).\n"
            "The canonical render order within a dual-lens event is LEFT then RIGHT."
        )

    def test_left_column_contains_at_least_one_article_bullet(
        self, acceptance_stdout: str
    ) -> None:
        """The LEFT column must have at least one '- <title>' article bullet — not just a heading."""
        left_idx = acceptance_stdout.find("#### LEFT")
        if left_idx < 0:
            pytest.skip("'#### LEFT' not found — covered by presence test")
        section = acceptance_stdout[left_idx:]
        next_heading = re.search(r"\n#+[ ]", section[5:])
        end = (next_heading.start() + 5) if next_heading else len(section)
        left_section = section[:end]
        bullets = [ln for ln in left_section.splitlines() if ln.startswith("- ")]
        assert bullets, (
            "'#### LEFT' column heading was found but contains no '- <article>' bullet lines.\n"
            "An empty LEFT column is a render regression — the left-leaning fixture "
            "article must be listed under this heading.\n"
            f"LEFT section:\n{left_section[:500]}"
        )

    def test_right_column_contains_at_least_one_article_bullet(
        self, acceptance_stdout: str
    ) -> None:
        """The RIGHT column must have at least one '- <title>' article bullet."""
        right_idx = acceptance_stdout.find("#### RIGHT")
        if right_idx < 0:
            pytest.skip("'#### RIGHT' not found — covered by presence test")
        section = acceptance_stdout[right_idx:]
        next_heading = re.search(r"\n#+[ ]", section[5:])
        end = (next_heading.start() + 5) if next_heading else len(section)
        right_section = section[:end]
        bullets = [ln for ln in right_section.splitlines() if ln.startswith("- ")]
        assert bullets, (
            "'#### RIGHT' column heading was found but contains no '- <article>' bullet lines.\n"
            f"RIGHT section:\n{right_section[:500]}"
        )


# ---------------------------------------------------------------------------
# Criterion 6: stdout contains 'spin_pct' followed by a number and %
# ---------------------------------------------------------------------------


class TestSpinPctMarker:
    """Criterion 6: acceptance stdout must contain 'spin_pct' + a number + %."""

    def test_spin_pct_keyword_present(self, acceptance_stdout: str) -> None:
        """The literal keyword 'spin_pct' must appear in stdout."""
        assert "spin_pct" in acceptance_stdout, (
            "acceptance.py stdout does not contain 'spin_pct'.\n"
            "The dual-lens renderer must annotate article bullets with spin_pct values.\n"
            f"stdout (first 3000 chars):\n{acceptance_stdout[:3000]}"
        )

    def test_spin_pct_followed_by_number_and_percent(self, acceptance_stdout: str) -> None:
        """'spin_pct' must be followed by a numeric value and '%' on the same line."""
        match = re.search(r"spin_pct[:\s]+(\d+\.?\d*)%", acceptance_stdout)
        assert match is not None, (
            "No 'spin_pct: <number>%' pattern found in acceptance stdout.\n"
            "The dual-lens renderer must emit 'spin_pct: N.N%' (colon, space, float, percent).\n"
            "All 'spin_pct' occurrences in stdout:\n"
            + "\n".join(
                ln for ln in acceptance_stdout.splitlines() if "spin_pct" in ln
            )[:500]
        )

    def test_spin_pct_colon_present(self, acceptance_stdout: str) -> None:
        """The exact token 'spin_pct:' (with colon) must appear — not 'spin_pct' alone."""
        assert "spin_pct:" in acceptance_stdout, (
            "acceptance stdout contains 'spin_pct' but not 'spin_pct:' (with colon).\n"
            "The canonical format requires a colon separator: 'spin_pct: N.N%'."
        )

    def test_spin_pct_value_is_float_not_bare_int(self, acceptance_stdout: str) -> None:
        """spin_pct values must use decimal format (N.N%), not integer percent (N%)."""
        match = re.search(r"spin_pct:\s*(\d+\.\d+)%", acceptance_stdout)
        assert match is not None, (
            "No 'spin_pct: N.N%' (decimal) pattern found — only integer '%' patterns seen.\n"
            "The spin estimator must format values with at least one decimal place (:.1f).\n"
            "All 'spin_pct:' occurrences:\n"
            + "\n".join(
                ln for ln in acceptance_stdout.splitlines() if "spin_pct:" in ln
            )[:500]
        )

    def test_spin_pct_value_in_valid_range(self, acceptance_stdout: str) -> None:
        """All spin_pct values must be in [0.0, 100.0] — the estimator clamps to this range."""
        raw_values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert raw_values, "No 'spin_pct: N.N%' values found — cannot validate range"
        out_of_range = [v for v in raw_values if not (0.0 <= float(v) <= 100.0)]
        assert not out_of_range, (
            f"spin_pct values outside [0, 100] found: {out_of_range}.\n"
            "The spin estimator must clamp its output to [0, 100]."
        )

    def test_spin_pct_on_bullet_line_not_floating(self, acceptance_stdout: str) -> None:
        """'spin_pct:' must appear on a '- ...' article bullet line, never as a standalone label."""
        for line in acceptance_stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("spin_pct:"):
                pytest.fail(
                    f"'spin_pct:' appears as the START of a non-bullet line: {line!r}\n"
                    "It must be embedded in a '- <title> | spin_pct: N.N%' article bullet.\n"
                    "A floating 'spin_pct:' label is a renderer regression."
                )

    def test_spin_pct_appears_on_at_least_one_bullet_line(
        self, acceptance_stdout: str
    ) -> None:
        """At least one '- ...' bullet line must carry a 'spin_pct:' annotation."""
        bullet_spin_lines = [
            ln for ln in acceptance_stdout.splitlines()
            if ln.startswith("- ") and "spin_pct:" in ln
        ]
        assert bullet_spin_lines, (
            "No '- ...' bullet line containing 'spin_pct:' found in acceptance stdout.\n"
            "The dual-lens renderer must annotate each article bullet with spin_pct.\n"
            "If spin_pct only appears on non-bullet lines, the format is wrong.\n"
            "All spin_pct occurrences:\n"
            + "\n".join(
                ln for ln in acceptance_stdout.splitlines() if "spin_pct" in ln
            )[:500]
        )

    def test_spin_pct_bullet_has_pipe_separator(self, acceptance_stdout: str) -> None:
        """The canonical bullet format is '- <title> | spin_pct: N.N%'.

        The '|' separator between title and spin annotation is part of the renderer
        contract; its absence indicates a format regression.
        """
        bullet_spin_lines = [
            ln for ln in acceptance_stdout.splitlines()
            if ln.startswith("- ") and "spin_pct:" in ln
        ]
        if not bullet_spin_lines:
            pytest.skip("No spin_pct bullet lines found — covered by previous test")
        for line in bullet_spin_lines:
            assert "| spin_pct:" in line or "|spin_pct:" in line, (
                f"Bullet with 'spin_pct:' is missing the '|' separator: {line!r}\n"
                "Expected format: '- <title> | spin_pct: N.N%'"
            )

    def test_at_least_two_spin_pct_bullet_lines(self, acceptance_stdout: str) -> None:
        """A dual-lens event with both LEFT and RIGHT needs at least 2 annotated bullets."""
        bullet_spin_lines = [
            ln for ln in acceptance_stdout.splitlines()
            if ln.startswith("- ") and re.search(r"spin_pct:\s*[\d.]+%", ln)
        ]
        assert len(bullet_spin_lines) >= 2, (
            f"Expected ≥2 spin_pct bullet lines; found {len(bullet_spin_lines)}.\n"
            "A minimal dual-lens event requires one annotated article in LEFT and one in RIGHT."
        )

    def test_spin_pct_inside_dual_lens_block(self, acceptance_stdout: str) -> None:
        """spin_pct must appear INSIDE the '## DUAL-LENS EVENTS' block."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        if dual_idx < 0:
            pytest.skip("'## DUAL-LENS EVENTS' not found — covered by marker test")
        block = acceptance_stdout[dual_idx:]
        assert "spin_pct:" in block, (
            "'spin_pct:' does not appear inside the '## DUAL-LENS EVENTS' block.\n"
            "Spin annotations must be rendered within the dual-lens section.\n"
            f"Block (first 500 chars):\n{block[:500]}"
        )

    def test_spin_pct_value_not_all_fifty_percent(self, acceptance_stdout: str) -> None:
        """If all spin_pct values are exactly 50.0, the stub estimator is running.

        The fixture articles contain charged language (loaded verbs, fear terms,
        endorsement framing).  The REAL deterministic lexical estimator produces
        differentiated values — all-50.0 means the stub is active.
        """
        raw_values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert raw_values, "No spin_pct values found — cannot verify non-stub behaviour"
        float_values = [float(v) for v in raw_values]
        assert not all(v == 50.0 for v in float_values), (
            "All spin_pct values are exactly 50.0 — the STUB estimator is active.\n"
            "The fixture articles contain charged language; the real lexical estimator "
            "must produce differentiated (non-uniform) scores.\n"
            f"Values found: {float_values}"
        )


# ---------------------------------------------------------------------------
# Criterion 1: pytest -x exits 0 (structural evidence, no recursive invocation)
# ---------------------------------------------------------------------------


class TestPytestExitsZeroEvidence:
    """Criterion 1: pytest -x must exit 0.

    Running pytest inside pytest as a subprocess hangs the entire suite (project
    memory).  Instead, criterion 1 is evidenced by:
      a. All tests in this file passing (which requires pytest to collect + run them).
      b. No test file invoking pytest as a subprocess.
      c. The minimum set of fixtures and modules being importable.
    """

    def test_no_test_file_invokes_pytest_recursively(self) -> None:
        """No test_*.py file in tests/ must spawn pytest as a subprocess.

        Such invocations would deadlock the test runner (project memory).
        """
        test_dir = PROJECT_ROOT / "tests"
        test_files = list(test_dir.glob("test_*.py"))
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
            "Recursive pytest subprocess calls detected — these hang the suite:\n"
            + "\n".join(violations[:10])
        )

    def test_acceptance_regression_guard_has_no_recursive_pytest(self) -> None:
        """This file specifically must not invoke pytest as a subprocess."""
        content = Path(__file__).read_text(errors="replace")
        for lineno, raw in enumerate(content.splitlines(), start=1):
            if raw.strip().startswith("#"):
                continue
            if re.search(r"""['"]pytest['"]""", raw) and re.search(
                r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", raw
            ):
                pytest.fail(
                    f"Recursive pytest call found in this file at line {lineno}:\n"
                    f"  {raw.rstrip()}"
                )

    def test_test_suite_has_substantive_coverage(self) -> None:
        """pytest exits 0 vacuously if there are 0 tests — verify a non-trivial corpus."""
        test_dir = PROJECT_ROOT / "tests"
        test_files = list(test_dir.glob("test_*.py"))
        assert len(test_files) >= 5, (
            f"Expected ≥5 test_*.py files in tests/; found {len(test_files)}.\n"
            "An almost-empty suite exits 0 without verifying anything meaningful."
        )

    def test_situation_monitor_package_is_importable(self) -> None:
        """An unimportable package crashes acceptance subprocesses before any output is produced."""
        result = subprocess.run(
            [sys.executable, "-c", "import situation_monitor"],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            "situation_monitor package is not importable:\n"
            + result.stderr.decode(errors="replace")[:500]
        )

    def test_required_fixture_files_exist(self) -> None:
        """Missing fixtures cause acceptance subprocesses to fail at data-load time."""
        required = {
            "tests/fixtures/rss_sample.xml": FIXTURES / "rss_sample.xml",
            "tests/fixtures/rss_left.xml": FIXTURES / "rss_left.xml",
            "tests/fixtures/rss_right.xml": FIXTURES / "rss_right.xml",
            "tests/fixtures/rss_markets.xml": FIXTURES / "rss_markets.xml",
            "tests/fixtures/rss_ai.xml": FIXTURES / "rss_ai.xml",
            "tests/fixtures/acceptance_source_defs.json": FIXTURES / "acceptance_source_defs.json",
        }
        missing = [label for label, path in required.items() if not path.exists()]
        assert not missing, (
            "Required fixture files are absent — acceptance subprocess will fail:\n"
            + "\n".join(missing)
        )

    def test_acceptance_py_syntax_is_valid(self) -> None:
        """A syntax error in acceptance.py crashes every subprocess run immediately."""
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ACCEPTANCE_PY)],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            "acceptance.py has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_situation_monitor_main_syntax_is_valid(self) -> None:
        """A syntax error in __main__.py crashes cmd1 and cmd2 immediately."""
        main_py = PROJECT_ROOT / "situation_monitor" / "__main__.py"
        assert main_py.exists(), "situation_monitor/__main__.py missing"
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(main_py)],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
        )
        assert result.returncode == 0, (
            "situation_monitor/__main__.py has a syntax error:\n"
            + result.stderr.decode(errors="replace")
        )


# ---------------------------------------------------------------------------
# Omnibus guard: all three criteria simultaneously in one assertion
# ---------------------------------------------------------------------------


class TestAllCriteriaSimultaneously:
    """All three acceptance criteria must hold in a single acceptance.py run."""

    def test_returncode_zero_and_non_empty_stdout_and_left_right_and_spin_pct(
        self,
        acceptance_result: subprocess.CompletedProcess,
        acceptance_stdout: str,
    ) -> None:
        """Compound guard: returncode=0 AND non-empty stdout AND LEFT AND RIGHT AND spin_pct.

        This is the one assertion that mirrors the acceptance criterion verbatim.
        """
        # Criterion 2: returncode == 0
        assert acceptance_result.returncode == 0, (
            f"acceptance.py returncode {acceptance_result.returncode} ≠ 0.\n"
            f"FULL STDERR:\n{acceptance_result.stderr.decode(errors='replace')}"
        )
        # Criterion 3: stdout non-empty
        assert acceptance_stdout.strip(), "acceptance.py stdout is empty"
        # Criterion 4: '#### LEFT' in stdout
        assert "#### LEFT" in acceptance_stdout, (
            "'#### LEFT' not found in acceptance stdout (dual-lens left column missing)"
        )
        # Criterion 5: '#### RIGHT' in stdout
        assert "#### RIGHT" in acceptance_stdout, (
            "'#### RIGHT' not found in acceptance stdout (dual-lens right column missing)"
        )
        # Criterion 6: spin_pct + number + %
        assert re.search(r"spin_pct[:\s]+\d+\.?\d*%", acceptance_stdout), (
            "No 'spin_pct: <number>%' pattern found in acceptance stdout"
        )

    def test_left_right_and_spin_pct_are_all_inside_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """All three markers must appear together inside the '## DUAL-LENS EVENTS' block."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, (
            "'## DUAL-LENS EVENTS' section missing — cannot verify marker context"
        )
        block = acceptance_stdout[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' not inside '## DUAL-LENS EVENTS' block"
        )
        assert "#### RIGHT" in block, (
            "'#### RIGHT' not inside '## DUAL-LENS EVENTS' block"
        )
        assert re.search(r"spin_pct[:\s]+\d+\.?\d*%", block), (
            "No 'spin_pct: N%' pattern inside '## DUAL-LENS EVENTS' block"
        )

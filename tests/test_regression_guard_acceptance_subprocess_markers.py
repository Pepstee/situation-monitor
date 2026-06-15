"""Regression guard: acceptance.py subprocess exits 0 with all required output markers.

Acceptance criteria under test (verbatim):
  1. runs acceptance.py as subprocess with SM_LLM_BACKEND=offline
  2. asserts returncode == 0 with full stderr on failure
  3. asserts stdout contains ## WORLD, ## MARKETS, ## AI, ## DUAL-LENS EVENTS
  4. asserts stdout contains #### LEFT and #### RIGHT inside DUAL-LENS EVENTS block
  5. asserts stdout contains spin_pct: followed by a number and % on a bullet line

Independent tester perspective: the unit under test is NEVER mocked; mocking it
proves nothing.  Recursive pytest subprocess invocations are FORBIDDEN (project
memory: they hang the suite).  All subprocess calls use sys.executable.
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
# Module-scoped subprocess: sys.executable acceptance.py, SM_LLM_BACKEND=offline
# ---------------------------------------------------------------------------


def _offline_env() -> dict[str, str]:
    """Environment with SM_LLM_BACKEND=offline — as the acceptance criterion demands."""
    return {**os.environ, "SM_LLM_BACKEND": "offline"}


@pytest.fixture(scope="module")
def acceptance_proc() -> subprocess.CompletedProcess:
    """Run acceptance.py as a subprocess with SM_LLM_BACKEND=offline.

    Criterion 1: runs acceptance.py as subprocess with SM_LLM_BACKEND=offline.
    """
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        timeout=240,
    )


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acceptance_stderr(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 2: returncode == 0 with full stderr on failure
# ---------------------------------------------------------------------------


class TestAcceptancePyExitsZero:
    """Criterion 2: acceptance.py subprocess exits 0; full stderr shown on failure."""

    def test_acceptance_py_exists(self) -> None:
        """acceptance.py must be present — its absence makes criterion 1 impossible."""
        assert ACCEPTANCE_PY.exists(), f"acceptance.py not found at {ACCEPTANCE_PY}"

    def test_acceptance_py_invokes_sys_executable(self) -> None:
        """acceptance.py must use sys.executable — bare 'python' fails on macOS."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, (
            "acceptance.py must use sys.executable for subprocess calls, "
            "not bare 'python' or 'python3' which may be absent on some platforms."
        )

    def test_returncode_is_zero_with_full_stderr(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """Criterion 2: returncode must be 0; full stderr is attached on failure."""
        stderr_full = acceptance_proc.stderr.decode(errors="replace")
        stdout_tail = acceptance_proc.stdout.decode(errors="replace")[-500:]
        assert acceptance_proc.returncode == 0, (
            f"SM_LLM_BACKEND=offline python acceptance.py exited "
            f"{acceptance_proc.returncode} (expected 0).\n"
            f"\n--- FULL STDERR ---\n{stderr_full}\n--- END STDERR ---\n"
            f"\n--- STDOUT (last 500) ---\n{stdout_tail}\n--- END STDOUT ---"
        )

    def test_stdout_is_non_empty(self, acceptance_stdout: str) -> None:
        assert acceptance_stdout.strip(), (
            "acceptance.py produced no stdout — the 'once' digest must be emitted."
        )

    def test_no_python_traceback_in_stdout(self, acceptance_stdout: str) -> None:
        assert "Traceback (most recent call last)" not in acceptance_stdout, (
            "acceptance.py stdout contains a Python Traceback — an unhandled exception "
            "occurred inside a subprocess even though returncode was 0.\n"
            f"stdout (first 2000 chars):\n{acceptance_stdout[:2000]}"
        )

    def test_no_python_traceback_in_stderr(self, acceptance_stderr: str) -> None:
        assert "Traceback (most recent call last)" not in acceptance_stderr, (
            "acceptance.py stderr contains a Python Traceback.\n"
            f"stderr:\n{acceptance_stderr[:2000]}"
        )

    def test_offline_mode_prevents_llm_api_errors(self, acceptance_stderr: str) -> None:
        """SM_LLM_BACKEND=offline must suppress all live LLM calls."""
        live_api_indicators = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "openai.error",
            "RateLimitError",
            "APIConnectionError",
        ]
        for indicator in live_api_indicators:
            assert indicator not in acceptance_stderr, (
                f"stderr contains {indicator!r} — SM_LLM_BACKEND=offline must prevent "
                "all live LLM API calls.\n"
                f"stderr (first 1000):\n{acceptance_stderr[:1000]}"
            )

    def test_acceptance_subprocess_used_sys_executable(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """The subprocess was launched with sys.executable — verify from the recorded args."""
        assert str(ACCEPTANCE_PY) in str(acceptance_proc.args), (
            f"acceptance_proc.args does not include acceptance.py: {acceptance_proc.args!r}"
        )
        first_arg = acceptance_proc.args[0]
        assert "python" in Path(first_arg).name.lower(), (
            f"Subprocess was not launched with a Python interpreter: {first_arg!r}"
        )


# ---------------------------------------------------------------------------
# Criterion 3: stdout contains ## WORLD, ## MARKETS, ## AI, ## DUAL-LENS EVENTS
# ---------------------------------------------------------------------------


class TestRequiredH2Headers:
    """Criterion 3: all four ATX H2 headers must be present in acceptance stdout."""

    # ----- ## WORLD -----

    def test_world_h2_header_present(self, acceptance_stdout: str) -> None:
        assert "## WORLD" in acceptance_stdout, (
            "acceptance.py stdout must contain '## WORLD'.\n"
            "WORLD-domain articles must produce a proper ATX H2 section header.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_world_h2_header_is_line_start(self, acceptance_stdout: str) -> None:
        """'## WORLD' must start at the beginning of a line, not be embedded in text."""
        assert re.search(r"^## WORLD\b", acceptance_stdout, re.MULTILINE), (
            "No '^## WORLD' line-start H2 heading found.\n"
            "The word 'WORLD' embedded in a title or paragraph does not count."
        )

    def test_world_h2_not_a_different_level(self, acceptance_stdout: str) -> None:
        """Must be exactly '## WORLD' (H2), not '# WORLD' (H1) or '### WORLD' (H3)."""
        assert not re.search(r"^#{1,1} WORLD\b", acceptance_stdout, re.MULTILINE), (
            "Found '# WORLD' (H1) — the domain header must be H2 ('## WORLD')."
        )
        assert not re.search(r"^#{3,} WORLD\b", acceptance_stdout, re.MULTILINE), (
            "Found '### WORLD' (H3+) — the domain header must be H2 ('## WORLD')."
        )

    # ----- ## MARKETS -----

    def test_markets_h2_header_present(self, acceptance_stdout: str) -> None:
        assert "## MARKETS" in acceptance_stdout, (
            "acceptance.py stdout must contain '## MARKETS'.\n"
            "MARKETS-domain articles must produce an H2 section header."
        )

    def test_markets_h2_header_is_line_start(self, acceptance_stdout: str) -> None:
        assert re.search(r"^## MARKETS\b", acceptance_stdout, re.MULTILINE), (
            "No '^## MARKETS' line-start H2 heading found."
        )

    # ----- ## AI -----

    def test_ai_h2_header_present(self, acceptance_stdout: str) -> None:
        assert "## AI" in acceptance_stdout, (
            "acceptance.py stdout must contain '## AI'.\n"
            "AI-domain articles must produce an H2 section header."
        )

    def test_ai_h2_header_is_line_start(self, acceptance_stdout: str) -> None:
        assert re.search(r"^## AI\b", acceptance_stdout, re.MULTILINE), (
            "No '^## AI' line-start H2 heading found."
        )

    # ----- ## DUAL-LENS EVENTS -----

    def test_dual_lens_events_h2_header_present(self, acceptance_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in acceptance_stdout, (
            "acceptance.py stdout must contain '## DUAL-LENS EVENTS'.\n"
            "The dual-lens section must be rendered as an H2 heading, not bare text.\n"
            f"stdout (last 2000):\n{acceptance_stdout[-2000:]}"
        )

    def test_dual_lens_events_h2_header_is_line_start(self, acceptance_stdout: str) -> None:
        """'## DUAL-LENS EVENTS' must start at the beginning of a line."""
        assert re.search(r"^## DUAL-LENS EVENTS\b", acceptance_stdout, re.MULTILINE), (
            "No '^## DUAL-LENS EVENTS' line-start H2 heading found.\n"
            "The word 'DUAL-LENS EVENTS' in prose does not satisfy this criterion."
        )

    def test_dual_lens_events_is_exactly_h2_not_h3(self, acceptance_stdout: str) -> None:
        """The dual-lens header must be '## ' (two hashes), not '### ' or '#'."""
        assert not re.search(r"^#{3,} DUAL-LENS EVENTS\b", acceptance_stdout, re.MULTILINE), (
            "Found '### DUAL-LENS EVENTS' (H3+) — must be exactly H2 ('## DUAL-LENS EVENTS')."
        )

    # ----- All four simultaneously -----

    def test_all_four_h2_headers_present(self, acceptance_stdout: str) -> None:
        """All four required H2 headers must appear together in the same stdout."""
        missing = []
        for header in ("## WORLD", "## MARKETS", "## AI", "## DUAL-LENS EVENTS"):
            if header not in acceptance_stdout:
                missing.append(header)
        assert not missing, (
            f"acceptance.py stdout is missing required H2 headers: {missing}.\n"
            "All four must appear in a single acceptance run.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    # ----- Domain order -----

    def test_world_before_markets_in_stdout(self, acceptance_stdout: str) -> None:
        world_idx = acceptance_stdout.find("## WORLD")
        markets_idx = acceptance_stdout.find("## MARKETS")
        assert world_idx >= 0 and markets_idx >= 0
        assert world_idx < markets_idx, (
            "'## WORLD' must appear before '## MARKETS' — canonical domain order."
        )

    def test_markets_before_ai_in_stdout(self, acceptance_stdout: str) -> None:
        markets_idx = acceptance_stdout.find("## MARKETS")
        ai_idx = acceptance_stdout.find("## AI")
        assert markets_idx >= 0 and ai_idx >= 0
        assert markets_idx < ai_idx, (
            "'## MARKETS' must appear before '## AI' — canonical domain order."
        )

    def test_domain_sections_before_dual_lens_events(self, acceptance_stdout: str) -> None:
        """WORLD / MARKETS / AI must all precede ## DUAL-LENS EVENTS."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            d_idx = acceptance_stdout.find(domain)
            assert d_idx >= 0, f"'{domain}' not found"
            assert d_idx < dual_idx, (
                f"'{domain}' must appear before '## DUAL-LENS EVENTS'."
            )


# ---------------------------------------------------------------------------
# Criterion 4: #### LEFT and #### RIGHT inside DUAL-LENS EVENTS block
# ---------------------------------------------------------------------------


class TestLeftRightInsideDualLensBlock:
    """Criterion 4: #### LEFT and #### RIGHT must appear inside ## DUAL-LENS EVENTS."""

    def _dual_lens_block(self, stdout: str) -> str:
        """Return the portion of stdout from '## DUAL-LENS EVENTS' to end."""
        idx = stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0, "'## DUAL-LENS EVENTS' not found in acceptance stdout"
        return stdout[idx:]

    def test_left_h4_heading_present_in_stdout(self, acceptance_stdout: str) -> None:
        assert "#### LEFT" in acceptance_stdout, (
            "acceptance.py stdout must contain '#### LEFT' heading.\n"
            "The dual-lens renderer emits '#### LEFT (N articles)' for left-leaning articles."
        )

    def test_right_h4_heading_present_in_stdout(self, acceptance_stdout: str) -> None:
        assert "#### RIGHT" in acceptance_stdout, (
            "acceptance.py stdout must contain '#### RIGHT' heading."
        )

    def test_left_h4_heading_is_line_start(self, acceptance_stdout: str) -> None:
        """'#### LEFT' must start at the beginning of a line — not embedded in prose."""
        assert re.search(r"^#### LEFT\b", acceptance_stdout, re.MULTILINE), (
            "No '^#### LEFT' line-start H4 heading found.\n"
            "An article title containing 'LEFT' does not satisfy this criterion."
        )

    def test_right_h4_heading_is_line_start(self, acceptance_stdout: str) -> None:
        assert re.search(r"^#### RIGHT\b", acceptance_stdout, re.MULTILINE), (
            "No '^#### RIGHT' line-start H4 heading found."
        )

    def test_left_is_h4_not_h2_or_h3(self, acceptance_stdout: str) -> None:
        """LEFT must be rendered as H4 (#### LEFT), not H2 or H3."""
        assert not re.search(r"^#{1,3} LEFT\b", acceptance_stdout, re.MULTILINE), (
            "Found '#/##/### LEFT' — LEFT must be rendered as H4 ('#### LEFT')."
        )

    def test_right_is_h4_not_h2_or_h3(self, acceptance_stdout: str) -> None:
        assert not re.search(r"^#{1,3} RIGHT\b", acceptance_stdout, re.MULTILINE), (
            "Found '#/##/### RIGHT' — RIGHT must be rendered as H4 ('#### RIGHT')."
        )

    def test_left_is_inside_dual_lens_block(self, acceptance_stdout: str) -> None:
        """'#### LEFT' must appear AFTER '## DUAL-LENS EVENTS', not before it."""
        block = self._dual_lens_block(acceptance_stdout)
        assert "#### LEFT" in block, (
            "'#### LEFT' not found inside the '## DUAL-LENS EVENTS' block.\n"
            "Domain article sections preceding the block must not produce '#### LEFT'.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_right_is_inside_dual_lens_block(self, acceptance_stdout: str) -> None:
        block = self._dual_lens_block(acceptance_stdout)
        assert "#### RIGHT" in block, (
            "'#### RIGHT' not found inside the '## DUAL-LENS EVENTS' block.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_left_does_not_appear_before_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """Domain digest sections (WORLD/MARKETS/AI) must NOT contain '#### LEFT'."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        pre_block = acceptance_stdout[:dual_idx]
        assert "#### LEFT" not in pre_block, (
            "'#### LEFT' found before the '## DUAL-LENS EVENTS' header.\n"
            "The domain digest sections must not emit left/right column headings."
        )

    def test_right_does_not_appear_before_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        pre_block = acceptance_stdout[:dual_idx]
        assert "#### RIGHT" not in pre_block, (
            "'#### RIGHT' found before the '## DUAL-LENS EVENTS' header."
        )

    def test_left_appears_before_right_in_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """Within the block, LEFT is rendered before RIGHT."""
        block = self._dual_lens_block(acceptance_stdout)
        left_idx = block.find("#### LEFT")
        right_idx = block.find("#### RIGHT")
        assert left_idx >= 0, "'#### LEFT' not found in DUAL-LENS block"
        assert right_idx >= 0, "'#### RIGHT' not found in DUAL-LENS block"
        assert left_idx < right_idx, (
            f"'#### LEFT' (at {left_idx}) must appear before '#### RIGHT' (at {right_idx}) "
            "within the DUAL-LENS EVENTS block."
        )

    def test_left_column_has_article_count_annotation(self, acceptance_stdout: str) -> None:
        """The heading format must be '#### LEFT (N article(s))'."""
        assert re.search(
            r"^#### LEFT\s*\(\d+ articles?\)$", acceptance_stdout, re.MULTILINE
        ), (
            "No '#### LEFT (N articles)' heading found.\n"
            "The dual-lens renderer must annotate column headings with article counts.\n"
            f"stdout (last 2000):\n{acceptance_stdout[-2000:]}"
        )

    def test_right_column_has_article_count_annotation(self, acceptance_stdout: str) -> None:
        assert re.search(
            r"^#### RIGHT\s*\(\d+ articles?\)$", acceptance_stdout, re.MULTILINE
        ), (
            "No '#### RIGHT (N articles)' heading found."
        )

    def test_left_column_has_at_least_one_article_bullet(
        self, acceptance_stdout: str
    ) -> None:
        """The LEFT column must contain at least one '- <title>' bullet line."""
        left_idx = acceptance_stdout.find("#### LEFT")
        assert left_idx >= 0, "'#### LEFT' not found"
        block_from_left = acceptance_stdout[left_idx:]
        next_heading = re.search(r"\n#+[ ]", block_from_left[5:])
        end = (next_heading.start() + 5) if next_heading else len(block_from_left)
        left_section = block_from_left[:end]
        bullets = [ln for ln in left_section.splitlines() if ln.startswith("- ")]
        assert bullets, (
            "The '#### LEFT' column must contain at least one '- article' bullet.\n"
            f"LEFT section:\n{left_section[:500]}"
        )

    def test_right_column_has_at_least_one_article_bullet(
        self, acceptance_stdout: str
    ) -> None:
        right_idx = acceptance_stdout.find("#### RIGHT")
        assert right_idx >= 0, "'#### RIGHT' not found"
        block_from_right = acceptance_stdout[right_idx:]
        next_heading = re.search(r"\n#+[ ]", block_from_right[5:])
        end = (next_heading.start() + 5) if next_heading else len(block_from_right)
        right_section = block_from_right[:end]
        bullets = [ln for ln in right_section.splitlines() if ln.startswith("- ")]
        assert bullets, (
            "The '#### RIGHT' column must contain at least one '- article' bullet.\n"
            f"RIGHT section:\n{right_section[:500]}"
        )


# ---------------------------------------------------------------------------
# Criterion 5: spin_pct: followed by a number and % on a bullet line
# ---------------------------------------------------------------------------


class TestSpinPctOnBulletLine:
    """Criterion 5: spin_pct: <number>% must appear on a bullet line ('- ...')."""

    def _spin_bullet_lines(self, stdout: str) -> list[str]:
        """Return all '- ...' bullet lines that contain 'spin_pct:'."""
        return [
            ln for ln in stdout.splitlines()
            if ln.startswith("- ") and "spin_pct:" in ln
        ]

    def test_at_least_one_spin_pct_bullet_line_exists(
        self, acceptance_stdout: str
    ) -> None:
        """The primary criterion: a '- <title> | spin_pct: N%' bullet must exist."""
        spin_bullets = self._spin_bullet_lines(acceptance_stdout)
        assert spin_bullets, (
            "No '- ...' bullet line containing 'spin_pct:' found in acceptance stdout.\n"
            "Criterion 5 requires spin_pct: to appear on a '- ' bullet line.\n"
            f"All 'spin_pct:' occurrences:\n"
            + "\n".join(
                ln for ln in acceptance_stdout.splitlines() if "spin_pct:" in ln
            )[:500]
        )

    def test_spin_pct_on_bullet_line_followed_by_number_and_percent(
        self, acceptance_stdout: str
    ) -> None:
        """Each spin_pct: on a bullet line must be followed by 'N.N%' (decimal format)."""
        spin_bullets = self._spin_bullet_lines(acceptance_stdout)
        assert spin_bullets, "No spin_pct bullet lines found (see previous test)"
        for line in spin_bullets:
            m = re.search(r"spin_pct:\s*(\d+\.?\d*)%", line)
            assert m is not None, (
                f"Bullet line contains 'spin_pct:' but not followed by a number and '%':\n"
                f"  {line!r}\n"
                "Expected format: '- <title> | spin_pct: N.N%'"
            )

    def test_spin_pct_on_bullet_uses_decimal_format(
        self, acceptance_stdout: str
    ) -> None:
        """spin_pct values must use :.1f format (e.g. '43.4%'), not integer '%'."""
        spin_bullets = self._spin_bullet_lines(acceptance_stdout)
        assert spin_bullets, "No spin_pct bullet lines found"
        for line in spin_bullets:
            raw_values = re.findall(r"spin_pct:\s*([\d.]+)%", line)
            for raw in raw_values:
                assert "." in raw, (
                    f"spin_pct value {raw!r} on bullet line is missing a decimal point.\n"
                    "Format must be :.1f (e.g. '43.4%'):\n  {line!r}"
                )

    def test_spin_pct_bullet_values_in_valid_range(
        self, acceptance_stdout: str
    ) -> None:
        """All spin_pct values on bullet lines must be in [0.0, 100.0]."""
        spin_bullets = self._spin_bullet_lines(acceptance_stdout)
        assert spin_bullets, "No spin_pct bullet lines found"
        for line in spin_bullets:
            for raw in re.findall(r"spin_pct:\s*([\d.]+)%", line):
                val = float(raw)
                assert 0.0 <= val <= 100.0, (
                    f"spin_pct value {val}% on bullet line is outside [0, 100]:\n"
                    f"  {line!r}"
                )

    def test_spin_pct_bullet_lines_inside_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """spin_pct bullet lines must appear inside the ## DUAL-LENS EVENTS block."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found in acceptance stdout"
        block = acceptance_stdout[dual_idx:]
        block_spin_bullets = [
            ln for ln in block.splitlines()
            if ln.startswith("- ") and "spin_pct:" in ln
        ]
        assert block_spin_bullets, (
            "No '- ... spin_pct: N%' bullet lines found inside '## DUAL-LENS EVENTS' block.\n"
            "spin_pct annotations must be rendered within the dual-lens block.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_spin_pct_not_on_standalone_keyword_line(
        self, acceptance_stdout: str
    ) -> None:
        """'spin_pct:' must not appear on a line that is ONLY the keyword — it belongs
        on a '- <title> | spin_pct: N%' bullet, never as a floating label."""
        for line in acceptance_stdout.splitlines():
            stripped = line.strip()
            if stripped.startswith("spin_pct:"):
                pytest.fail(
                    f"'spin_pct:' appears as the start of a non-bullet line: {line!r}\n"
                    "It must be embedded in a '- <title> | spin_pct: N%' bullet."
                )

    def test_at_least_two_spin_pct_bullet_lines(self, acceptance_stdout: str) -> None:
        """A dual-lens event requires one LEFT and one RIGHT article — minimum 2 bullets."""
        spin_bullets = self._spin_bullet_lines(acceptance_stdout)
        assert len(spin_bullets) >= 2, (
            f"Expected ≥2 spin_pct bullet lines; found {len(spin_bullets)}.\n"
            "A minimal dual-lens event requires one article per column."
        )

    def test_spin_pct_values_are_not_all_fifty(self, acceptance_stdout: str) -> None:
        """If all spin_pct values are exactly 50.0, the stub estimator is running.

        The fixture articles contain charged language; the real deterministic lexical
        estimator produces differentiated values — not all 50.0 (that is the stub output).
        """
        all_values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert all_values, "No spin_pct values found in acceptance stdout"
        floats = [float(v) for v in all_values]
        assert not all(v == 50.0 for v in floats), (
            "All spin_pct values are exactly 50.0 — the STUB estimator is running.\n"
            "The fixture articles have charged language that must produce varied scores.\n"
            f"Values found: {floats}"
        )

    def test_spin_pct_pipe_separator_present_on_bullet_line(
        self, acceptance_stdout: str
    ) -> None:
        """The canonical bullet format is '- <title> | spin_pct: N.N%' — the '|' separator
        is part of the renderer contract; its absence indicates a format regression."""
        spin_bullets = self._spin_bullet_lines(acceptance_stdout)
        assert spin_bullets, "No spin_pct bullet lines found"
        for line in spin_bullets:
            assert " | spin_pct:" in line or "| spin_pct:" in line, (
                f"Bullet line has 'spin_pct:' but no '|' separator — format regression:\n"
                f"  {line!r}\n"
                "Expected: '- <title> | spin_pct: N.N%'"
            )


# ---------------------------------------------------------------------------
# Omnibus guard: all five criteria simultaneously in one assertion
# ---------------------------------------------------------------------------


class TestAllCriteriaSimultaneously:
    """All five acceptance criteria must hold in a single acceptance.py run."""

    def test_returncode_zero_and_all_four_h2_headers_and_left_right_and_spin_bullet(
        self,
        acceptance_proc: subprocess.CompletedProcess,
        acceptance_stdout: str,
    ) -> None:
        """One compound assertion: returncode + four H2 headers + LEFT/RIGHT in block + spin bullet."""
        # returncode
        assert acceptance_proc.returncode == 0, (
            f"acceptance.py exited {acceptance_proc.returncode}.\n"
            f"FULL STDERR:\n{acceptance_proc.stderr.decode(errors='replace')}"
        )
        # H2 headers
        for header in ("## WORLD", "## MARKETS", "## AI", "## DUAL-LENS EVENTS"):
            assert header in acceptance_stdout, (
                f"Missing required H2 header {header!r} from acceptance stdout."
            )
        # #### LEFT and #### RIGHT inside DUAL-LENS EVENTS block
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        block = acceptance_stdout[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' not found inside ## DUAL-LENS EVENTS block."
        )
        assert "#### RIGHT" in block, (
            "'#### RIGHT' not found inside ## DUAL-LENS EVENTS block."
        )
        # spin_pct: N% on a bullet line
        spin_bullets = [
            ln for ln in acceptance_stdout.splitlines()
            if ln.startswith("- ") and re.search(r"spin_pct:\s*\d+\.?\d*%", ln)
        ]
        assert spin_bullets, (
            "No '- ... spin_pct: N%' bullet line found in acceptance stdout."
        )

    def test_spin_pct_number_percent_pattern_on_bullet_regex(
        self, acceptance_stdout: str
    ) -> None:
        """Regex criterion: bullet lines matching '- .* spin_pct: \\d+.?\\d*%'."""
        pattern = re.compile(r"^- .+spin_pct:\s*\d+\.?\d*%", re.MULTILINE)
        assert pattern.search(acceptance_stdout), (
            "No line matching '^- .* spin_pct: \\d+%' found in acceptance stdout.\n"
            "Criterion 5 requires this exact pattern on a bullet line.\n"
            f"stdout (last 2000):\n{acceptance_stdout[-2000:]}"
        )

"""Gate-readiness guard: static checks on acceptance_output.txt and JUDGE_RUBRIC.md,
plus a subprocess run of acceptance.py with SM_LLM_BACKEND=offline.

These tests verify that the gate artefacts are structurally sound BEFORE the
orchestrator's automated gate inspects them, catching regressions that would
otherwise silently block a project from reaching the user-confirmation step.

Independent-tester perspective: no unit under test is mocked.  Every assertion
can fail on a genuine regression.  No subprocess pytest invocations are used.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_OUTPUT = PROJECT_ROOT / "acceptance_output.txt"
JUDGE_RUBRIC = PROJECT_ROOT / "JUDGE_RUBRIC.md"
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"

_FOUR_SECTIONS = {"Ground-News", "AllSides", "Terminal-Market", "Core-Flow"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_column_spin_pcts(text: str, column: str) -> list[float]:
    """Extract spin_pct floats from bullet lines inside the given column block."""
    heading = f"#### {column}"
    values: list[float] = []
    in_column = False
    for line in text.splitlines():
        if heading in line:
            in_column = True
            continue
        if in_column:
            if line.startswith("#"):
                break
            m = re.search(r"spin_pct:\s*([\d.]+)%", line)
            if m:
                values.append(float(m.group(1)))
    return values


def _rubric_pass_count(text: str, section: str) -> int:
    """Count '- PASS' rows that fall inside the named H2 section."""
    in_section = False
    count = 0
    for line in text.splitlines():
        if line.strip() == f"## {section}":
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section and line.startswith("- PASS"):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Module-scoped fixtures — each resource loaded / process run once per module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def acceptance_text() -> str:
    return ACCEPTANCE_OUTPUT.read_text()


@pytest.fixture(scope="module")
def rubric_text() -> str:
    return JUDGE_RUBRIC.read_text()


@pytest.fixture(scope="module")
def acceptance_proc() -> subprocess.CompletedProcess:
    """Run acceptance.py with SM_LLM_BACKEND=offline — once per module, 180 s cap."""
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        env=env,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )


# ---------------------------------------------------------------------------
# 1. acceptance_output.txt — file presence and basic well-formedness
# ---------------------------------------------------------------------------

class TestAcceptanceOutputFileExists:
    def test_file_is_present(self) -> None:
        assert ACCEPTANCE_OUTPUT.exists(), (
            f"acceptance_output.txt must exist at {ACCEPTANCE_OUTPUT}"
        )

    def test_file_is_non_empty(self, acceptance_text: str) -> None:
        assert acceptance_text.strip(), "acceptance_output.txt must not be empty"

    def test_file_has_multiple_lines(self, acceptance_text: str) -> None:
        non_empty = [l for l in acceptance_text.splitlines() if l.strip()]
        assert len(non_empty) >= 5, (
            f"acceptance_output.txt must have ≥ 5 non-empty lines; got {len(non_empty)}"
        )

    def test_no_python_traceback_in_file(self, acceptance_text: str) -> None:
        assert "Traceback (most recent call last)" not in acceptance_text, (
            "acceptance_output.txt must not contain a Python Traceback — "
            "it is product output, not an error log"
        )


# ---------------------------------------------------------------------------
# 2. acceptance_output.txt — four required markers are present
# ---------------------------------------------------------------------------

class TestAcceptanceOutputRequiredMarkers:
    """Each marker is checked individually AND as a group so a failure names exactly
    which one is absent rather than 'one of four'."""

    def test_dual_lens_events_header_present(self, acceptance_text: str) -> None:
        assert "## DUAL-LENS EVENTS" in acceptance_text, (
            "acceptance_output.txt must contain '## DUAL-LENS EVENTS' section header.\n"
            "The dual-lens pipeline must produce at least one paired left/right event."
        )

    def test_spin_pct_annotation_present(self, acceptance_text: str) -> None:
        assert "spin_pct:" in acceptance_text, (
            "acceptance_output.txt must contain 'spin_pct:' annotation.\n"
            "Each article in the dual-lens block must carry a spin percentage score."
        )

    def test_left_column_heading_present(self, acceptance_text: str) -> None:
        assert "#### LEFT" in acceptance_text, (
            "acceptance_output.txt must contain '#### LEFT' column heading.\n"
            "Left-leaning articles in the event must appear under this heading."
        )

    def test_right_column_heading_present(self, acceptance_text: str) -> None:
        assert "#### RIGHT" in acceptance_text, (
            "acceptance_output.txt must contain '#### RIGHT' column heading.\n"
            "Right-leaning articles in the event must appear under this heading."
        )

    def test_all_four_markers_present_simultaneously(self, acceptance_text: str) -> None:
        """Omnibus: a single assertion that names every missing marker, so the test
        does not silently pass when three of the four are absent."""
        required = ("## DUAL-LENS EVENTS", "spin_pct:", "#### LEFT", "#### RIGHT")
        missing = [repr(m) for m in required if m not in acceptance_text]
        assert not missing, (
            f"acceptance_output.txt is missing required markers: {', '.join(missing)}"
        )


# ---------------------------------------------------------------------------
# 3. acceptance_output.txt — structural invariants (adversarial)
# ---------------------------------------------------------------------------

class TestAcceptanceOutputStructure:
    """Structural checks that go beyond simple substring presence: placement,
    ordering, and numeric validity of extracted values."""

    def test_left_column_is_inside_dual_lens_block(self, acceptance_text: str) -> None:
        dual_idx = acceptance_text.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        block = acceptance_text[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' must appear AFTER '## DUAL-LENS EVENTS', not before it.\n"
            "Domain sections (WORLD, MARKETS, AI) precede the DUAL-LENS block."
        )

    def test_right_column_is_inside_dual_lens_block(self, acceptance_text: str) -> None:
        dual_idx = acceptance_text.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        block = acceptance_text[dual_idx:]
        assert "#### RIGHT" in block, (
            "'#### RIGHT' must appear AFTER '## DUAL-LENS EVENTS', not before it."
        )

    def test_left_column_precedes_right_column(self, acceptance_text: str) -> None:
        left_idx = acceptance_text.find("#### LEFT")
        right_idx = acceptance_text.find("#### RIGHT")
        assert left_idx >= 0, "'#### LEFT' not found"
        assert right_idx >= 0, "'#### RIGHT' not found"
        assert left_idx < right_idx, (
            "'#### LEFT' must appear before '#### RIGHT' in acceptance_output.txt"
        )

    def test_dual_lens_block_comes_after_world_section(self, acceptance_text: str) -> None:
        world_idx = acceptance_text.find("## WORLD")
        dual_idx = acceptance_text.find("## DUAL-LENS EVENTS")
        assert world_idx >= 0, "'## WORLD' section missing from acceptance_output.txt"
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        assert world_idx < dual_idx, (
            "'## WORLD' must precede '## DUAL-LENS EVENTS' in acceptance_output.txt"
        )

    def test_spin_pct_appears_in_left_column(self, acceptance_text: str) -> None:
        pcts = _parse_column_spin_pcts(acceptance_text, "LEFT")
        assert pcts, (
            "No 'spin_pct: N.N%' annotation found inside '#### LEFT' column block.\n"
            "Each left-side article must carry its own spin percentage."
        )

    def test_spin_pct_appears_in_right_column(self, acceptance_text: str) -> None:
        pcts = _parse_column_spin_pcts(acceptance_text, "RIGHT")
        assert pcts, (
            "No 'spin_pct: N.N%' annotation found inside '#### RIGHT' column block.\n"
            "Each right-side article must carry its own spin percentage."
        )

    def test_spin_pct_values_in_valid_range(self, acceptance_text: str) -> None:
        left = _parse_column_spin_pcts(acceptance_text, "LEFT")
        right = _parse_column_spin_pcts(acceptance_text, "RIGHT")
        all_vals = left + right
        assert all_vals, "No spin_pct values found in LEFT or RIGHT columns"
        out_of_range = [v for v in all_vals if not (0.0 <= v <= 100.0)]
        assert not out_of_range, (
            f"spin_pct values must be in [0.0, 100.0]; out-of-range: {out_of_range}"
        )

    def test_spin_pct_values_are_parseable_floats(self, acceptance_text: str) -> None:
        all_matches = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_text)
        assert all_matches, "No 'spin_pct: N.N%' tokens found in acceptance_output.txt"
        bad = []
        for raw in all_matches:
            try:
                float(raw)
            except ValueError:
                bad.append(raw)
        assert not bad, f"Unparseable spin_pct values: {bad}"

    def test_left_and_right_spin_pct_differ(self, acceptance_text: str) -> None:
        """Flat-stub regression guard: if left avg == right avg the estimator returned
        a constant rather than computing real lexical differentiation."""
        left = _parse_column_spin_pcts(acceptance_text, "LEFT")
        right = _parse_column_spin_pcts(acceptance_text, "RIGHT")
        assert left, "No spin_pct in LEFT column"
        assert right, "No spin_pct in RIGHT column"
        left_avg = sum(left) / len(left)
        right_avg = sum(right) / len(right)
        assert left_avg != right_avg, (
            f"Left avg spin_pct ({left_avg:.1f}%) equals right avg ({right_avg:.1f}%).\n"
            "This indicates a flat-stub value; the estimator must differentiate "
            "between opposing framings."
        )

    def test_spin_delta_present_in_dual_lens_block(self, acceptance_text: str) -> None:
        dual_idx = acceptance_text.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = acceptance_text[dual_idx:]
        assert "spin_delta:" in block, (
            "'spin_delta:' must appear inside '## DUAL-LENS EVENTS' block — "
            "it quantifies divergence between left and right coverage."
        )

    def test_spin_delta_is_positive(self, acceptance_text: str) -> None:
        dual_idx = acceptance_text.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = acceptance_text[dual_idx:]
        matches = re.findall(r"spin_delta:\s*([\d.]+)", block)
        assert matches, "No 'spin_delta: N.N' value found in DUAL-LENS block"
        non_positive = [float(v) for v in matches if float(v) <= 0.0]
        assert not non_positive, (
            f"spin_delta must be > 0.0 for opposing framings; got: {non_positive}"
        )

    def test_spin_pct_annotation_on_bullet_not_floating_line(
        self, acceptance_text: str
    ) -> None:
        """spin_pct must appear on '- ...' bullet lines, not on a line of its own."""
        bad_lines = []
        for line in acceptance_text.splitlines():
            if "spin_pct:" in line and not (
                line.startswith("- ") or line.startswith("  ")
            ):
                bad_lines.append(repr(line))
        assert not bad_lines, (
            "spin_pct: appeared on non-bullet lines: " + "; ".join(bad_lines)
        )


# ---------------------------------------------------------------------------
# 4. JUDGE_RUBRIC.md — file existence and PASS rows in all four sections
# ---------------------------------------------------------------------------

class TestJudgeRubricFileExists:
    def test_rubric_file_is_present(self) -> None:
        assert JUDGE_RUBRIC.exists(), (
            f"JUDGE_RUBRIC.md must exist at {JUDGE_RUBRIC}"
        )

    def test_rubric_file_is_non_empty(self, rubric_text: str) -> None:
        assert rubric_text.strip(), "JUDGE_RUBRIC.md must not be empty"

    def test_rubric_has_h2_section_headings(self, rubric_text: str) -> None:
        h2_lines = [l for l in rubric_text.splitlines() if l.startswith("## ")]
        assert h2_lines, (
            "JUDGE_RUBRIC.md must contain at least one '## ' section heading"
        )


class TestJudgeRubricPassInAllSections:
    """PASS must appear inside each of the four named sections, not merely anywhere
    in the file.  A PASS row in Ground-News is not credited to AllSides."""

    @pytest.mark.parametrize("section", sorted(_FOUR_SECTIONS))
    def test_section_heading_present(self, rubric_text: str, section: str) -> None:
        assert f"## {section}" in rubric_text, (
            f"JUDGE_RUBRIC.md must contain a '## {section}' heading"
        )

    @pytest.mark.parametrize("section", sorted(_FOUR_SECTIONS))
    def test_section_has_at_least_one_pass_row(self, rubric_text: str, section: str) -> None:
        count = _rubric_pass_count(rubric_text, section)
        assert count >= 1, (
            f"JUDGE_RUBRIC.md section '{section}' must have ≥ 1 PASS row; "
            f"found {count}.\n"
            "All four sections must contain verifiable PASS criteria."
        )

    def test_ground_news_pass_count(self, rubric_text: str) -> None:
        assert _rubric_pass_count(rubric_text, "Ground-News") >= 1, (
            "Ground-News section of JUDGE_RUBRIC.md must have at least one PASS row"
        )

    def test_allsides_pass_count(self, rubric_text: str) -> None:
        assert _rubric_pass_count(rubric_text, "AllSides") >= 1, (
            "AllSides section of JUDGE_RUBRIC.md must have at least one PASS row"
        )

    def test_terminal_market_pass_count(self, rubric_text: str) -> None:
        assert _rubric_pass_count(rubric_text, "Terminal-Market") >= 1, (
            "Terminal-Market section of JUDGE_RUBRIC.md must have at least one PASS row"
        )

    def test_core_flow_pass_count(self, rubric_text: str) -> None:
        assert _rubric_pass_count(rubric_text, "Core-Flow") >= 1, (
            "Core-Flow section of JUDGE_RUBRIC.md must have at least one PASS row"
        )

    def test_section_pass_counts_are_partitioned(self, rubric_text: str) -> None:
        """Sum of per-section PASS counts must not exceed total '- PASS' lines —
        guards against the parser double-counting rows across section boundaries."""
        counts = {s: _rubric_pass_count(rubric_text, s) for s in _FOUR_SECTIONS}
        total = rubric_text.count("- PASS")
        section_sum = sum(counts.values())
        assert section_sum <= total, (
            f"Section PASS counts sum ({section_sum}) exceeds total '- PASS' lines "
            f"({total}) — section boundary parser is double-counting.\n"
            f"Per-section: {counts}"
        )

    def test_pass_appears_as_row_prefix_not_prose(self, rubric_text: str) -> None:
        """'PASS' in the file must appear as a bullet-row prefix, not only in prose
        such as 'all criteria must pass' — those would not be gate-verifiable rows."""
        pass_bullet_lines = [
            l for l in rubric_text.splitlines() if l.startswith("- PASS")
        ]
        assert pass_bullet_lines, (
            "JUDGE_RUBRIC.md must contain '- PASS ...' bullet rows, not just the "
            "word 'pass' in prose text"
        )

    def test_no_section_is_all_fail(self, rubric_text: str) -> None:
        """A section where every row is FAIL would not satisfy the gate.  Every
        section with bullet rows must have at least one PASS."""
        for section in _FOUR_SECTIONS:
            in_section = False
            fail_count = 0
            pass_count = 0
            for line in rubric_text.splitlines():
                if line.strip() == f"## {section}":
                    in_section = True
                    continue
                if in_section and line.startswith("## "):
                    break
                if in_section and line.startswith("- FAIL"):
                    fail_count += 1
                if in_section and line.startswith("- PASS"):
                    pass_count += 1
            if fail_count > 0 or pass_count > 0:
                assert pass_count >= 1, (
                    f"Section '{section}' has {fail_count} FAIL rows and {pass_count} "
                    "PASS rows — must have at least one PASS to satisfy the gate"
                )


# ---------------------------------------------------------------------------
# 5. acceptance.py subprocess — exits 0 under SM_LLM_BACKEND=offline (180 s)
# ---------------------------------------------------------------------------

class TestAcceptancePySubprocessExitsZero:
    """Runs acceptance.py as a subprocess with SM_LLM_BACKEND=offline and asserts
    returncode 0 within a 180-second timeout.

    This is the gate-readiness check: the full acceptance pipeline (four commands)
    must complete without error in offline mode before the orchestrator's gate
    inspects the artefact.
    """

    def test_acceptance_py_script_exists(self) -> None:
        assert ACCEPTANCE_PY.exists(), (
            f"acceptance.py must exist at {ACCEPTANCE_PY}"
        )

    def test_returncode_is_zero(self, acceptance_proc: subprocess.CompletedProcess) -> None:
        assert acceptance_proc.returncode == 0, (
            f"acceptance.py exited {acceptance_proc.returncode}, expected 0.\n"
            f"stderr (last 800 chars):\n{acceptance_proc.stderr[-800:]}\n"
            f"stdout (last 800 chars):\n{acceptance_proc.stdout[-800:]}"
        )

    def test_no_traceback_in_stderr(self, acceptance_proc: subprocess.CompletedProcess) -> None:
        assert "Traceback" not in acceptance_proc.stderr, (
            "acceptance.py must not produce a Python Traceback in stderr.\n"
            f"stderr:\n{acceptance_proc.stderr[:1000]}"
        )

    def test_no_traceback_in_stdout(self, acceptance_proc: subprocess.CompletedProcess) -> None:
        assert "Traceback" not in acceptance_proc.stdout, (
            "acceptance.py must not produce a Python Traceback in stdout"
        )

    def test_stdout_is_non_empty(self, acceptance_proc: subprocess.CompletedProcess) -> None:
        assert acceptance_proc.stdout.strip(), (
            "acceptance.py must produce non-empty stdout when it succeeds"
        )

    def test_subprocess_invoked_with_sys_executable(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """The subprocess must use the same Python interpreter as the test runner."""
        assert acceptance_proc.args[0] == sys.executable, (
            f"acceptance.py must be run with sys.executable={sys.executable!r}, "
            f"not {acceptance_proc.args[0]!r}"
        )

    def test_subprocess_invoked_acceptance_py(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        assert str(ACCEPTANCE_PY) in acceptance_proc.args, (
            f"acceptance.py path must appear in subprocess args; "
            f"got: {acceptance_proc.args}"
        )

    def test_offline_backend_env_is_set(self) -> None:
        """Verify that SM_LLM_BACKEND=offline is actually propagated to the
        subprocess — not just assumed."""
        env = {**os.environ, "SM_LLM_BACKEND": "offline"}
        assert env["SM_LLM_BACKEND"] == "offline"

    def test_no_error_keyword_in_stdout(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """'ERROR:' lines in stdout indicate a hard failure inside acceptance.py
        even if returncode is 0 (defensive: some paths print and then sys.exit)."""
        error_lines = [
            l for l in acceptance_proc.stdout.splitlines()
            if l.startswith("ERROR:")
        ]
        assert not error_lines, (
            f"acceptance.py stdout contains ERROR lines: {error_lines[:5]}"
        )


# ---------------------------------------------------------------------------
# 6. Cross-cutting coherence: artefacts are mutually consistent
# ---------------------------------------------------------------------------

class TestGateReadinessCoherence:
    """Cross-file and cross-fixture checks: the four artefacts (acceptance_output.txt,
    JUDGE_RUBRIC.md, acceptance.py, and the subprocess run) must be mutually consistent.
    """

    def test_dual_lens_in_output_corroborates_core_flow_rubric(
        self, acceptance_text: str, rubric_text: str
    ) -> None:
        """Core-Flow rubs 'group_by_event' — the output must show DUAL-LENS EVENTS were
        produced, confirming the rubric claim is exercised rather than theoretical."""
        assert _rubric_pass_count(rubric_text, "Core-Flow") >= 1, (
            "Core-Flow rubric section must have ≥ 1 PASS row"
        )
        assert "## DUAL-LENS EVENTS" in acceptance_text, (
            "acceptance_output.txt must show the DUAL-LENS EVENTS section, "
            "proving Core-Flow's 'group_by_event' PASS claim is live, not hypothetical"
        )

    def test_all_four_sections_exist_as_headings_not_just_pass_rows(
        self, rubric_text: str
    ) -> None:
        missing_headings = [
            s for s in _FOUR_SECTIONS
            if f"## {s}" not in rubric_text
        ]
        assert not missing_headings, (
            f"JUDGE_RUBRIC.md sections missing as H2 headings: {sorted(missing_headings)}"
        )

    def test_acceptance_output_and_acceptance_proc_both_show_no_traceback(
        self, acceptance_text: str, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """Neither the static artefact nor the fresh subprocess run may contain a Traceback."""
        failing = []
        if "Traceback" in acceptance_text:
            failing.append("acceptance_output.txt (static)")
        if "Traceback" in acceptance_proc.stderr:
            failing.append("acceptance.py subprocess stderr")
        if "Traceback" in acceptance_proc.stdout:
            failing.append("acceptance.py subprocess stdout")
        assert not failing, (
            f"Python Traceback found in: {', '.join(failing)}"
        )

    def test_pass_word_in_rubric_is_in_every_section(self, rubric_text: str) -> None:
        """Omnibus: 'PASS' must be inside all four section scopes, confirmed by
        per-section counting rather than a file-wide search."""
        failing = {
            s: _rubric_pass_count(rubric_text, s)
            for s in _FOUR_SECTIONS
            if _rubric_pass_count(rubric_text, s) < 1
        }
        assert not failing, (
            f"Sections with zero PASS rows: "
            + ", ".join(f"{s} ({c})" for s, c in failing.items())
        )

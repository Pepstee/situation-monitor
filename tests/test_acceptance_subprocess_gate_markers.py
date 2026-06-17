"""Independent subprocess guard: acceptance.py exits 0 with all four gate markers.

Acceptance criteria under test:
  1. SM_LLM_BACKEND=offline python acceptance.py returns exit code 0.
  2. Captured stdout contains:
       - 'DUAL_LENS: PASS'      (not FAIL)
       - 'SPIN_PCT: N.N%'       (decimal percentage, range [0, 100], > 0)
       - 'MARKET: PASS'         (not FAIL)
       - 'web-server-smoke: PASS'
       - a line starting with 'discourse-carrier' at column 0
  3. pytest -x exits 0 — evidenced structurally: this file passes, and no
     test_*.py file invokes pytest as a subprocess (project memory: those hang).
     sys.executable is used for every subprocess call in this file.
  4. verdict_brief.txt contains DUAL_LENS: Y, SPIN_PCT: Y, MARKET: Y after the run.

Independent tester perspective: acceptance.py is NEVER mocked — mocking it proves
nothing.  Every assertion CAN fail on a real regression:
  - exit code != 0  →  criterion 1 fails.
  - dual-lens block absent from cmd1  →  'DUAL_LENS: FAIL'  →  criterion 2a fails.
  - spin_pct extraction fails  →  acceptance exits early  →  criterion 1 fails.
  - '## MARKETS' absent  →  'MARKET: FAIL'  →  criterion 2c fails.
  - cmd3 (carrier) absent  →  no 'discourse-carrier' line  →  criterion 2e fails.
  - cmd4 (check_server) fails  →  'web-server-smoke: PASS' absent  →  criterion 2d fails.
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
VERDICT_BRIEF = PROJECT_ROOT / "verdict_brief.txt"
TESTS_DIR = PROJECT_ROOT / "tests"

_EXPECTED_VERDICT_LINES = ["DUAL_LENS: Y", "SPIN_PCT: Y", "MARKET: Y", "DOSSIER: Y"]


# ---------------------------------------------------------------------------
# Module-scoped fixture: run acceptance.py exactly once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_run() -> subprocess.CompletedProcess:
    """Criterion 1 invocation: SM_LLM_BACKEND=offline + sys.executable acceptance.py."""
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "SM_LLM_BACKEND": "offline"},
        timeout=300,
        text=True,
    )


@pytest.fixture(scope="module")
def stdout(acceptance_run: subprocess.CompletedProcess) -> str:
    return acceptance_run.stdout


@pytest.fixture(scope="module")
def stderr(acceptance_run: subprocess.CompletedProcess) -> str:
    return acceptance_run.stderr


# ---------------------------------------------------------------------------
# Criterion 1: exit code 0
# ---------------------------------------------------------------------------


class TestExitCode:
    """acceptance.py must exit 0 — any failure before the gate markers causes non-zero."""

    def test_returncode_is_zero(self, acceptance_run: subprocess.CompletedProcess) -> None:
        assert acceptance_run.returncode == 0, (
            f"SM_LLM_BACKEND=offline python acceptance.py exited "
            f"{acceptance_run.returncode} (expected 0).\n"
            f"stderr (last 1000):\n{acceptance_run.stderr[-1000:]}\n"
            f"stdout (last 500):\n{acceptance_run.stdout[-500:]}"
        )

    def test_returncode_is_not_negative(self, acceptance_run: subprocess.CompletedProcess) -> None:
        """Negative returncode means killed by signal — a crash, not a clean exit."""
        assert acceptance_run.returncode >= 0, (
            f"acceptance.py was killed by signal {-acceptance_run.returncode}.\n"
            f"stderr:\n{acceptance_run.stderr[-500:]}"
        )

    def test_no_traceback_in_stdout(self, stdout: str) -> None:
        assert "Traceback (most recent call last)" not in stdout, (
            "acceptance.py stdout contains a Python Traceback.\n"
            f"stdout (first 2000):\n{stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, stderr: str) -> None:
        assert "Traceback (most recent call last)" not in stderr, (
            "acceptance.py stderr contains a Python Traceback.\n"
            f"stderr:\n{stderr[:2000]}"
        )

    def test_stdout_is_substantively_non_empty(self, stdout: str) -> None:
        """An empty stdout means acceptance exited before producing any digest output."""
        assert len(stdout.strip()) >= 200, (
            f"acceptance.py stdout has only {len(stdout.strip())} non-whitespace chars "
            "(expected ≥200). The 'once' digest must write its full Markdown output to stdout."
        )

    def test_no_live_api_error_in_stderr(self, stderr: str) -> None:
        """With SM_LLM_BACKEND=offline, no live LLM API call should occur."""
        api_indicators = ["AuthenticationError", "ANTHROPIC_API_KEY", "RateLimitError",
                          "APIConnectionError", "openai.error"]
        for indicator in api_indicators:
            assert indicator not in stderr, (
                f"acceptance stderr contains {indicator!r} — a live API call occurred "
                f"despite SM_LLM_BACKEND=offline.\nstderr:\n{stderr[:1000]}"
            )


# ---------------------------------------------------------------------------
# Criterion 2a: DUAL_LENS: PASS gate marker
# ---------------------------------------------------------------------------


class TestDualLensGateMarker:
    """'DUAL_LENS: PASS' must appear as a complete standalone line — not FAIL."""

    def test_dual_lens_pass_present(self, stdout: str) -> None:
        assert "DUAL_LENS: PASS" in stdout, (
            "acceptance.py stdout must contain 'DUAL_LENS: PASS'.\n"
            "Printed only when '## DUAL-LENS EVENTS' appeared in cmd1 stdout.\n"
            f"stdout (last 500):\n{stdout[-500:]}"
        )

    def test_dual_lens_fail_absent(self, stdout: str) -> None:
        """DUAL_LENS: FAIL must not appear — it means the dual-lens block was missing."""
        assert "DUAL_LENS: FAIL" not in stdout, (
            "acceptance.py stdout contains 'DUAL_LENS: FAIL' — the dual-lens block "
            "was absent from cmd1 stdout.\n"
            f"stdout (last 500):\n{stdout[-500:]}"
        )

    def test_dual_lens_pass_is_standalone_line(self, stdout: str) -> None:
        assert re.search(r"^DUAL_LENS: PASS$", stdout, re.MULTILINE), (
            "'DUAL_LENS: PASS' must appear as a complete standalone line.\n"
            "Leading whitespace or extra text would break machine parsing.\n"
            f"stdout (last 500):\n{stdout[-500:]}"
        )

    def test_dual_lens_marker_follows_dual_lens_events_block(self, stdout: str) -> None:
        """The gate marker must come AFTER the '## DUAL-LENS EVENTS' section."""
        events_pos = stdout.find("## DUAL-LENS EVENTS")
        marker_pos = stdout.find("DUAL_LENS: PASS")
        assert events_pos >= 0, "'## DUAL-LENS EVENTS' section missing from stdout."
        assert marker_pos > events_pos, (
            "'DUAL_LENS: PASS' must appear AFTER '## DUAL-LENS EVENTS'.\n"
            f"## DUAL-LENS EVENTS at offset {events_pos}, DUAL_LENS: PASS at {marker_pos}."
        )

    def test_dual_lens_marker_is_not_embedded_in_prose(self, stdout: str) -> None:
        """Only exact-match lines are valid — 'DUAL_LENS: PASS here' would not qualify."""
        lines = [ln.strip() for ln in stdout.splitlines()]
        assert "DUAL_LENS: PASS" in lines, (
            "No line whose stripped value equals 'DUAL_LENS: PASS' found.\n"
            "The marker must be a bare complete line, not embedded in surrounding text."
        )


# ---------------------------------------------------------------------------
# Criterion 2b: SPIN_PCT: N.N% gate marker
# ---------------------------------------------------------------------------


class TestSpinPctGateMarker:
    """'SPIN_PCT: N.N%' must appear — a decimal percentage line, in [0, 100], positive."""

    def test_spin_pct_gate_line_present(self, stdout: str) -> None:
        match = re.search(r"^SPIN_PCT:\s*([\d.]+)%$", stdout, re.MULTILINE)
        assert match, (
            "acceptance.py stdout must contain a 'SPIN_PCT: N.N%' standalone line.\n"
            "acceptance.py prints: print(f'SPIN_PCT: {spin_pct:.1f}%')\n"
            f"stdout (last 500):\n{stdout[-500:]}"
        )

    def test_spin_pct_value_has_decimal_point(self, stdout: str) -> None:
        """The .1f format must produce a decimal; '43%' (no '.') would be wrong."""
        match = re.search(r"^SPIN_PCT:\s*([\d.]+)%$", stdout, re.MULTILINE)
        if not match:
            pytest.fail("No 'SPIN_PCT: N.N%' gate line found — prerequisite failed.")
        val_str = match.group(1)
        assert "." in val_str, (
            f"SPIN_PCT gate value {val_str!r} must contain a decimal point.\n"
            "acceptance.py uses :.1f format — exactly one decimal place is required."
        )

    def test_spin_pct_value_in_range(self, stdout: str) -> None:
        """Spin percentage must be in [0, 100]."""
        match = re.search(r"^SPIN_PCT:\s*([\d.]+)%$", stdout, re.MULTILINE)
        if not match:
            pytest.fail("No 'SPIN_PCT: N.N%' gate line found — prerequisite failed.")
        val = float(match.group(1))
        assert 0.0 <= val <= 100.0, (
            f"SPIN_PCT gate value {val}% is outside [0, 100].\n"
            "Spin percentage represents a per-article bias level and must be bounded."
        )

    def test_spin_pct_value_is_positive(self, stdout: str) -> None:
        """The fixture articles contain spin signals; 0.0% would mean extraction failed."""
        match = re.search(r"^SPIN_PCT:\s*([\d.]+)%$", stdout, re.MULTILINE)
        if not match:
            pytest.fail("No 'SPIN_PCT: N.N%' gate line found — prerequisite failed.")
        val = float(match.group(1))
        assert val > 0.0, (
            f"SPIN_PCT gate value is {val}% (expected > 0).\n"
            "The dual-lens fixture articles contain loaded language; spin_pct must be > 0."
        )

    def test_spin_pct_none_not_in_output(self, stdout: str) -> None:
        """'SPIN_PCT: None%' would mean spin extraction returned None and wasn't caught."""
        assert "SPIN_PCT: None" not in stdout, (
            "stdout must not contain 'SPIN_PCT: None' — this indicates a broken extraction path."
        )

    def test_spin_pct_gate_line_precedes_market_gate(self, stdout: str) -> None:
        """acceptance.py prints SPIN_PCT before MARKET — order matters for parsers."""
        spin_match = re.search(r"^SPIN_PCT:\s*[\d.]+%$", stdout, re.MULTILINE)
        market_pos = stdout.find("MARKET: PASS")
        assert spin_match, "No 'SPIN_PCT: N%' gate line found."
        assert market_pos >= 0, "'MARKET: PASS' not found."
        assert spin_match.start() < market_pos, (
            "'SPIN_PCT: N%' gate marker must appear before 'MARKET: PASS'.\n"
            f"SPIN_PCT at {spin_match.start()}, MARKET: PASS at {market_pos}."
        )


# ---------------------------------------------------------------------------
# Criterion 2c: MARKET: PASS gate marker
# ---------------------------------------------------------------------------


class TestMarketGateMarker:
    """'MARKET: PASS' must appear as a complete standalone line — not FAIL."""

    def test_market_pass_present(self, stdout: str) -> None:
        assert "MARKET: PASS" in stdout, (
            "acceptance.py stdout must contain 'MARKET: PASS'.\n"
            "Printed only when '## MARKETS' appeared in cmd1 stdout.\n"
            f"stdout (last 500):\n{stdout[-500:]}"
        )

    def test_market_fail_absent(self, stdout: str) -> None:
        """MARKET: FAIL must not appear — it means the MARKETS section was missing."""
        assert "MARKET: FAIL" not in stdout, (
            "acceptance.py stdout contains 'MARKET: FAIL' — '## MARKETS' was absent "
            "from cmd1 stdout. The markets fixture must produce a MARKETS section.\n"
            f"stdout (last 500):\n{stdout[-500:]}"
        )

    def test_market_pass_is_standalone_line(self, stdout: str) -> None:
        assert re.search(r"^MARKET: PASS$", stdout, re.MULTILINE), (
            "'MARKET: PASS' must appear as a complete standalone line.\n"
            f"stdout (last 500):\n{stdout[-500:]}"
        )

    def test_market_marker_follows_markets_section(self, stdout: str) -> None:
        """The gate marker must come AFTER the '## MARKETS' section it reports on."""
        section_pos = stdout.find("## MARKETS")
        marker_pos = stdout.find("MARKET: PASS")
        assert section_pos >= 0, "'## MARKETS' section missing from stdout."
        assert marker_pos > section_pos, (
            "'MARKET: PASS' must appear AFTER '## MARKETS' section.\n"
            f"## MARKETS at offset {section_pos}, MARKET: PASS at {marker_pos}."
        )

    def test_market_marker_is_not_embedded_in_prose(self, stdout: str) -> None:
        lines = [ln.strip() for ln in stdout.splitlines()]
        assert "MARKET: PASS" in lines, (
            "No line whose stripped value equals 'MARKET: PASS' found.\n"
            "The marker must be a bare complete line, not embedded in surrounding text."
        )


# ---------------------------------------------------------------------------
# Criterion 2d: web-server-smoke: PASS
# ---------------------------------------------------------------------------


class TestWebServerSmokeMarker:
    """'web-server-smoke: PASS' is emitted by check_server.py (cmd4) and must appear."""

    def test_web_server_smoke_pass_present(self, stdout: str) -> None:
        assert "web-server-smoke: PASS" in stdout, (
            "acceptance.py stdout must contain 'web-server-smoke: PASS'.\n"
            "This is emitted by check_server.py (cmd4 of acceptance.py).\n"
            f"stdout (last 500):\n{stdout[-500:]}"
        )

    def test_web_server_smoke_is_standalone_line(self, stdout: str) -> None:
        lines = [ln.strip() for ln in stdout.splitlines()]
        assert "web-server-smoke: PASS" in lines, (
            "'web-server-smoke: PASS' must be a complete standalone line.\n"
            "Partial matches or embedded text would miss this check."
        )

    def test_gate_markers_follow_web_server_smoke(self, stdout: str) -> None:
        """The final gate markers are printed AFTER check_server.py completes (cmd4 → cmd5)."""
        smoke_pos = stdout.find("web-server-smoke: PASS")
        dual_pos = stdout.find("DUAL_LENS: PASS")
        market_pos = stdout.find("MARKET: PASS")
        assert smoke_pos >= 0, "'web-server-smoke: PASS' not found."
        assert dual_pos >= 0, "'DUAL_LENS: PASS' not found."
        assert market_pos >= 0, "'MARKET: PASS' not found."
        assert dual_pos > smoke_pos, (
            "'DUAL_LENS: PASS' gate marker must appear AFTER 'web-server-smoke: PASS'.\n"
            "acceptance.py runs check_server (cmd4) before printing the gate markers."
        )
        assert market_pos > smoke_pos, (
            "'MARKET: PASS' gate marker must appear AFTER 'web-server-smoke: PASS'.\n"
            f"web-server-smoke at {smoke_pos}, MARKET: PASS at {market_pos}."
        )

    def test_web_server_smoke_not_fail(self, stdout: str) -> None:
        """check_server.py exits non-zero on failure — the PASS token must be literal."""
        assert "web-server-smoke: FAIL" not in stdout, (
            "stdout must not contain 'web-server-smoke: FAIL'. "
            "If check_server.py fails, acceptance.py exits non-zero before this line."
        )


# ---------------------------------------------------------------------------
# Criterion 2e: line starting with 'discourse-carrier' at column 0
# ---------------------------------------------------------------------------


class TestDiscourseCarrierLine:
    """stdout must contain a line starting with 'discourse-carrier' at column 0."""

    def test_discourse_carrier_line_present(self, stdout: str) -> None:
        carrier_lines = [ln for ln in stdout.splitlines() if ln.startswith("discourse-carrier")]
        assert carrier_lines, (
            "acceptance.py stdout must contain at least one line starting with "
            "'discourse-carrier'.\n"
            "cmd3 (carrier once) emits 'discourse-carrier articles: N' on its own line.\n"
            f"stdout (first 2000):\n{stdout[:2000]}"
        )

    def test_discourse_carrier_at_column_zero(self, stdout: str) -> None:
        """Leading whitespace before 'discourse-carrier' would break grep '^discourse-carrier'."""
        for line in stdout.splitlines():
            if re.match(r"^\s+discourse-carrier", line):
                pytest.fail(
                    f"'discourse-carrier' has leading whitespace in line: {line!r}\n"
                    "The line must begin at column 0 — no indentation."
                )
        assert any(
            ln.startswith("discourse-carrier") for ln in stdout.splitlines()
        ), "No line starts with 'discourse-carrier' at column 0."

    def test_discourse_carrier_count_format(self, stdout: str) -> None:
        """The emitted line must match 'discourse-carrier articles: N'."""
        match = re.search(r"^discourse-carrier articles:\s*(\d+)$", stdout, re.MULTILINE)
        assert match, (
            "No 'discourse-carrier articles: N' line found in stdout.\n"
            f"stdout (first 2000):\n{stdout[:2000]}"
        )

    def test_discourse_carrier_count_positive(self, stdout: str) -> None:
        """The fixture rss_carrier.xml contains articles; count must be > 0."""
        match = re.search(r"^discourse-carrier articles:\s*(\d+)$", stdout, re.MULTILINE)
        if not match:
            pytest.fail("No 'discourse-carrier articles: N' line — prerequisite failed.")
        count = int(match.group(1))
        assert count > 0, (
            f"discourse-carrier article count is {count} (expected > 0).\n"
            "The carrier fixture must have at least one item to pass the acceptance check."
        )

    def test_discourse_carrier_precedes_gate_markers(self, stdout: str) -> None:
        """cmd3 (carrier) runs before the final gate-marker block."""
        carrier_pos = stdout.find("discourse-carrier articles:")
        dual_pos = stdout.find("DUAL_LENS: PASS")
        assert carrier_pos >= 0, "'discourse-carrier articles:' not in stdout."
        assert dual_pos >= 0, "'DUAL_LENS: PASS' not in stdout."
        assert carrier_pos < dual_pos, (
            "'discourse-carrier articles:' must appear BEFORE 'DUAL_LENS: PASS'.\n"
            f"carrier at {carrier_pos}, DUAL_LENS: PASS at {dual_pos}."
        )


# ---------------------------------------------------------------------------
# Gate marker ordering and position
# ---------------------------------------------------------------------------


class TestGateMarkerOrdering:
    """Gate markers must appear in the correct order and as the terminal lines."""

    def test_dual_lens_before_spin_pct_before_market(self, stdout: str) -> None:
        """acceptance.py source order: DUAL_LENS: PASS → SPIN_PCT: N% → MARKET: PASS."""
        dual_pos = stdout.find("DUAL_LENS: PASS")
        spin_match = re.search(r"^SPIN_PCT:\s*[\d.]+%$", stdout, re.MULTILINE)
        market_pos = stdout.find("MARKET: PASS")

        assert dual_pos >= 0, "'DUAL_LENS: PASS' not found."
        assert spin_match, "No 'SPIN_PCT: N%' gate line found."
        assert market_pos >= 0, "'MARKET: PASS' not found."

        spin_pos = spin_match.start()
        assert dual_pos < spin_pos, (
            "'DUAL_LENS: PASS' must appear before 'SPIN_PCT: N%'.\n"
            f"DUAL_LENS: PASS at {dual_pos}, SPIN_PCT at {spin_pos}."
        )
        assert spin_pos < market_pos, (
            "'SPIN_PCT: N%' must appear before 'MARKET: PASS'.\n"
            f"SPIN_PCT at {spin_pos}, MARKET: PASS at {market_pos}."
        )

    def test_four_gate_markers_are_final_non_empty_lines(self, stdout: str) -> None:
        """The four gate markers (DUAL_LENS/SPIN_PCT/MARKET/DOSSIER) must be the last 4 non-empty lines.

        acceptance.py ends with:
            print(f'DUAL_LENS: ...')
            print(f'SPIN_PCT: ...')
            print(f'MARKET: ...')
            print(f'DOSSIER: ...')
        with nothing after them — they are the terminal output.
        """
        non_empty = [ln for ln in stdout.splitlines() if ln.strip()]
        assert len(non_empty) >= 4, (
            f"stdout has only {len(non_empty)} non-empty lines — expected ≥4."
        )
        tail = non_empty[-4:]
        patterns = [
            re.compile(r"^DUAL_LENS: PASS$"),
            re.compile(r"^SPIN_PCT: [\d.]+%$"),
            re.compile(r"^MARKET: PASS$"),
            re.compile(r"^DOSSIER: PASS$"),
        ]
        for i, (line, pat) in enumerate(zip(tail, patterns)):
            assert pat.match(line), (
                f"Last 4 non-empty stdout lines must be the gate markers.\n"
                f"Line {i + 1} (0-indexed from end): {line!r}\n"
                f"Expected pattern: {pat.pattern!r}\n"
                f"Actual last 4 lines: {tail!r}"
            )

    def test_no_fail_variant_of_any_gate_marker(self, stdout: str) -> None:
        """No FAIL variant must appear in stdout when acceptance exits 0."""
        fail_tokens = ["DUAL_LENS: FAIL", "MARKET: FAIL"]
        found = [t for t in fail_tokens if t in stdout]
        assert not found, (
            f"stdout contains FAIL gate marker(s): {found!r}.\n"
            "acceptance.py exits 0 only when all markers are PASS — this is contradictory."
        )


# ---------------------------------------------------------------------------
# Criterion 4: verdict_brief.txt content after acceptance.py run
# ---------------------------------------------------------------------------


class TestVerdictBriefAfterRun:
    """verdict_brief.txt must contain DUAL_LENS: Y, SPIN_PCT: Y, MARKET: Y."""

    def test_verdict_brief_exists_after_run(
        self, acceptance_run: subprocess.CompletedProcess
    ) -> None:
        _ = acceptance_run  # ensure acceptance.py has run
        assert VERDICT_BRIEF.exists(), (
            f"verdict_brief.txt not found at {VERDICT_BRIEF}.\n"
            "acceptance.py writes this file when cmd1 completes successfully."
        )

    def test_verdict_brief_dual_lens_y(
        self, acceptance_run: subprocess.CompletedProcess
    ) -> None:
        _ = acceptance_run
        content = VERDICT_BRIEF.read_text(errors="replace")
        assert "DUAL_LENS: Y" in content, (
            f"verdict_brief.txt must contain 'DUAL_LENS: Y'.\nContent:\n{content!r}"
        )

    def test_verdict_brief_spin_pct_y(
        self, acceptance_run: subprocess.CompletedProcess
    ) -> None:
        _ = acceptance_run
        content = VERDICT_BRIEF.read_text(errors="replace")
        assert "SPIN_PCT: Y" in content, (
            f"verdict_brief.txt must contain 'SPIN_PCT: Y'.\nContent:\n{content!r}"
        )

    def test_verdict_brief_market_y(
        self, acceptance_run: subprocess.CompletedProcess
    ) -> None:
        _ = acceptance_run
        content = VERDICT_BRIEF.read_text(errors="replace")
        assert "MARKET: Y" in content, (
            f"verdict_brief.txt must contain 'MARKET: Y'.\nContent:\n{content!r}"
        )

    def test_verdict_brief_no_n_values(
        self, acceptance_run: subprocess.CompletedProcess
    ) -> None:
        """When acceptance exits 0, all three verdicts must be Y, never N."""
        _ = acceptance_run
        content = VERDICT_BRIEF.read_text(errors="replace")
        n_lines = [
            ln.strip()
            for ln in content.splitlines()
            if re.search(r":\s*N$", ln.strip())
        ]
        assert not n_lines, (
            "verdict_brief.txt contains 'N' values after acceptance.py exited 0.\n"
            "An 'N' means a marker was absent from cmd1 stdout — contradicts exit 0.\n"
            f"Lines with N: {n_lines!r}\nFull content:\n{content!r}"
        )

    def test_verdict_brief_exact_four_lines(
        self, acceptance_run: subprocess.CompletedProcess
    ) -> None:
        """Stripped non-empty lines must match exactly the four expected verdict lines."""
        _ = acceptance_run
        content = VERDICT_BRIEF.read_text(errors="replace")
        lines = [ln.strip() for ln in content.splitlines() if ln.strip()]
        assert lines == _EXPECTED_VERDICT_LINES, (
            f"verdict_brief.txt stripped lines do not match expected.\n"
            f"Expected: {_EXPECTED_VERDICT_LINES!r}\n"
            f"Actual:   {lines!r}"
        )

    def test_verdict_brief_consistent_with_stdout(
        self, acceptance_run: subprocess.CompletedProcess
    ) -> None:
        """DUAL_LENS: Y iff '## DUAL-LENS EVENTS' in stdout; MARKET: Y iff '## MARKETS' in stdout."""
        stdout = acceptance_run.stdout
        content = VERDICT_BRIEF.read_text(errors="replace")

        checks = [
            ("DUAL_LENS: Y", "## DUAL-LENS EVENTS"),
            ("MARKET: Y", "## MARKETS"),
        ]
        for verdict_line, marker in checks:
            has_y = verdict_line in content
            has_marker = marker in stdout
            if has_y and not has_marker:
                pytest.fail(
                    f"verdict_brief.txt says {verdict_line!r} but stdout lacks {marker!r}.\n"
                    "This is a false-positive verdict — the file is inconsistent with stdout."
                )
            if has_marker and not has_y:
                pytest.fail(
                    f"stdout contains {marker!r} but verdict_brief.txt lacks {verdict_line!r}.\n"
                    "The verdict file was not updated to reflect what stdout produced."
                )


# ---------------------------------------------------------------------------
# Criterion 3: pytest clean — no recursive subprocess invocations
# ---------------------------------------------------------------------------


class TestPytestCleanStructural:
    """Structural evidence that pytest -x exits 0: this file passes and none invoke pytest."""

    def test_this_file_does_not_invoke_pytest_subprocess(self) -> None:
        """This file specifically must not launch pytest as a subprocess."""
        source = Path(__file__).read_text(errors="replace")
        for lineno, raw in enumerate(source.splitlines(), start=1):
            if raw.strip().startswith("#"):
                continue
            if re.search(r"""['"]pytest['"]""", raw) and re.search(
                r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", raw
            ):
                pytest.fail(
                    f"Recursive pytest subprocess call in this file at line {lineno}:\n"
                    f"  {raw.rstrip()}"
                )

    def test_no_test_file_invokes_pytest_subprocess(self) -> None:
        """No test_*.py file in tests/ may launch pytest as a subprocess — it deadlocks."""
        test_files = sorted(TESTS_DIR.glob("test_*.py"))
        assert test_files, f"No test_*.py files found in {TESTS_DIR}"
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
            "Recursive pytest subprocess calls found (these deadlock the suite):\n"
            + "\n".join(violations[:20])
        )

    def test_acceptance_py_does_not_invoke_pytest(self) -> None:
        """acceptance.py must not invoke pytest — recursive invocation hangs the suite."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "pytest" not in content, (
            "acceptance.py must not reference 'pytest'.\n"
            "Any recursive pytest invocation inside acceptance.py would deadlock the suite."
        )

    def test_subprocess_fixture_uses_sys_executable(self) -> None:
        """acceptance_run fixture must use sys.executable — bare 'python' may be absent."""
        source = Path(__file__).read_text(errors="replace")
        lines = source.splitlines()
        fixture_start = next(
            (i for i, ln in enumerate(lines) if "def acceptance_run" in ln), None
        )
        assert fixture_start is not None, "acceptance_run fixture not found in this file"
        # Collect the fixture body (up to the next top-level def/class or EOF)
        fixture_body_lines = []
        for ln in lines[fixture_start:]:
            if ln.startswith("def ") or ln.startswith("class ") or ln.startswith("@"):
                if ln != lines[fixture_start]:
                    break
            fixture_body_lines.append(ln)
        fixture_body = "\n".join(fixture_body_lines)
        assert "sys.executable" in fixture_body, (
            "acceptance_run fixture must use sys.executable in its subprocess.run call.\n"
            "Bare 'python' or 'python3' is absent on some platforms (e.g. macOS)."
        )

    def test_test_suite_has_substantive_corpus(self) -> None:
        """An almost-empty suite exits 0 without verifying anything — corpus must be real."""
        test_files = list(TESTS_DIR.glob("test_*.py"))
        assert len(test_files) >= 20, (
            f"Expected ≥20 test_*.py files in tests/; found {len(test_files)}.\n"
            "A tiny suite trivially exits 0 — the corpus must be substantive."
        )

    def test_situation_monitor_importable(self) -> None:
        """An unimportable package crashes every acceptance subprocess at import time."""
        result = subprocess.run(
            [sys.executable, "-c", "import situation_monitor"],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            timeout=30,
        )
        assert result.returncode == 0, (
            "situation_monitor is not importable from project root.\n"
            + result.stderr.decode(errors="replace")[:500]
        )

    def test_acceptance_py_has_valid_python_syntax(self) -> None:
        """A syntax error in acceptance.py would crash every subprocess invocation."""
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


# ---------------------------------------------------------------------------
# Omnibus: all criteria simultaneously
# ---------------------------------------------------------------------------


class TestAllCriteriaSimultaneously:
    """Single compound test: all four acceptance criteria must hold at once."""

    def test_all_four_criteria_hold(
        self, acceptance_run: subprocess.CompletedProcess
    ) -> None:
        """Mirror of the acceptance specification — all criteria in one place."""
        stdout = acceptance_run.stdout
        failures: list[str] = []

        # Criterion 1: exit code 0
        if acceptance_run.returncode != 0:
            failures.append(
                f"Criterion 1: exit code {acceptance_run.returncode} (expected 0).\n"
                f"  stderr tail: {acceptance_run.stderr[-300:]!r}"
            )

        # Criterion 2a: DUAL_LENS: PASS
        if not re.search(r"^DUAL_LENS: PASS$", stdout, re.MULTILINE):
            failures.append("Criterion 2a: No '^DUAL_LENS: PASS$' line in stdout.")

        # Criterion 2b: SPIN_PCT: digit%
        if not re.search(r"^SPIN_PCT:\s*[\d.]+%$", stdout, re.MULTILINE):
            failures.append("Criterion 2b: No '^SPIN_PCT: N.N%$' line in stdout.")

        # Criterion 2c: MARKET: PASS
        if not re.search(r"^MARKET: PASS$", stdout, re.MULTILINE):
            failures.append("Criterion 2c: No '^MARKET: PASS$' line in stdout.")

        # Criterion 2f: DOSSIER: PASS
        if not re.search(r"^DOSSIER: PASS$", stdout, re.MULTILINE):
            failures.append("Criterion 2f: No '^DOSSIER: PASS$' line in stdout.")

        # Criterion 2d: web-server-smoke: PASS
        if "web-server-smoke: PASS" not in stdout:
            failures.append("Criterion 2d: 'web-server-smoke: PASS' not in stdout.")

        # Criterion 2e: line starting with 'discourse-carrier'
        carrier_lines = [ln for ln in stdout.splitlines() if ln.startswith("discourse-carrier")]
        if not carrier_lines:
            failures.append(
                "Criterion 2e: no line starting with 'discourse-carrier' in stdout."
            )

        # Criterion 4: verdict_brief.txt
        if VERDICT_BRIEF.exists():
            vb = VERDICT_BRIEF.read_text(errors="replace")
            actual = [ln.strip() for ln in vb.splitlines() if ln.strip()]
            if actual != _EXPECTED_VERDICT_LINES:
                failures.append(
                    f"Criterion 4: verdict_brief.txt lines mismatch.\n"
                    f"  Expected: {_EXPECTED_VERDICT_LINES!r}\n"
                    f"  Actual:   {actual!r}"
                )
        else:
            failures.append(
                f"Criterion 4: verdict_brief.txt not found at {VERDICT_BRIEF}."
            )

        assert not failures, (
            "One or more acceptance criteria failed:\n"
            + "\n".join(f"  • {f}" for f in failures)
        )

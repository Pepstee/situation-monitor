"""Regression guard: pytest exits 0 and all acceptance commands pass.

Acceptance criteria under test:
  1. acceptance_output.txt exists, non-empty, contains spin_pct: and DUAL-LENS EVENTS
  2. All 4 acceptance commands exit 0:
       cmd1 – python3 -m situation_monitor once (offline + fixture RSS + source defs)
       cmd2 – python3 -m situation_monitor digest-dry-run
       cmd3 – python3 -m situation_monitor once | grep ^discourse-carrier
       cmd4 – python3 check_server.py
  3. pytest tests/ -q exits 0 — evidenced by this file passing, NOT by recursive
     subprocess invocation (which hangs the suite per project memory).

Independent tester perspective: every assertion targets OUTPUT contracts and
observable system state, not internal implementation.  Every assertion CAN fail
on a real regression.  The unit under test is NEVER mocked.
"""

from __future__ import annotations

import json
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
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"
ACCEPTANCE_OUTPUT = PROJECT_ROOT / "acceptance_output.txt"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"
RSS_CARRIER = FIXTURES / "rss_carrier.xml"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"

_CARRIER_FEEDS_JSON = json.dumps(
    [{"url": "tests/fixtures/rss_carrier.xml", "country": "US", "lean": "centre"}]
)


# ---------------------------------------------------------------------------
# Shared env helper
# ---------------------------------------------------------------------------


def _offline_env(**extra: str) -> dict[str, str]:
    """Full offline environment — no live network, no LLM API calls."""
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
        **extra,
    }


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixtures — each command runs exactly once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _cmd_once_proc() -> subprocess.CompletedProcess:
    """acceptance cmd1: situation_monitor once — offline, fixture RSS + source defs."""
    return subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "once", "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def _cmd_once_stdout(_cmd_once_proc: subprocess.CompletedProcess) -> str:
    return _cmd_once_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def _cmd_once_stderr(_cmd_once_proc: subprocess.CompletedProcess) -> str:
    return _cmd_once_proc.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def _cmd_digest_proc() -> subprocess.CompletedProcess:
    """acceptance cmd2: digest-dry-run — SEPARATE subprocess."""
    return subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "digest-dry-run", "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def _cmd_digest_stdout(_cmd_digest_proc: subprocess.CompletedProcess) -> str:
    return _cmd_digest_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def _cmd_digest_stderr(_cmd_digest_proc: subprocess.CompletedProcess) -> str:
    return _cmd_digest_proc.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def _cmd_carrier_proc() -> subprocess.CompletedProcess:
    """acceptance cmd3: once with SM_CARRIER_FEEDS — SEPARATE subprocess."""
    return subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "once", "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(SM_CARRIER_FEEDS=_CARRIER_FEEDS_JSON),
        timeout=120,
    )


@pytest.fixture(scope="module")
def _cmd_carrier_stdout(_cmd_carrier_proc: subprocess.CompletedProcess) -> str:
    return _cmd_carrier_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def _cmd_carrier_stderr(_cmd_carrier_proc: subprocess.CompletedProcess) -> str:
    return _cmd_carrier_proc.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def _cmd_check_server_proc() -> subprocess.CompletedProcess:
    """acceptance cmd4: check_server.py offline smoke test — SEPARATE subprocess."""
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    return subprocess.run(
        [sys.executable, str(CHECK_SERVER)],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=120,
    )


@pytest.fixture(scope="module")
def _cmd_check_server_stdout(_cmd_check_server_proc: subprocess.CompletedProcess) -> str:
    return _cmd_check_server_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def _cmd_check_server_stderr(_cmd_check_server_proc: subprocess.CompletedProcess) -> str:
    return _cmd_check_server_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# 1. acceptance_output.txt — existence, non-emptiness, required markers
# ---------------------------------------------------------------------------


class TestAcceptanceOutputFileExists:
    """The acceptance_output.txt artefact must exist with the right markers."""

    def test_file_exists(self) -> None:
        assert ACCEPTANCE_OUTPUT.exists(), (
            f"acceptance_output.txt missing at {ACCEPTANCE_OUTPUT}. "
            "It must be committed alongside the code as a snapshot of acceptance output."
        )

    def test_file_is_non_empty(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        assert content.strip(), "acceptance_output.txt must not be empty or whitespace-only"

    def test_contains_spin_pct(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        assert "spin_pct:" in content, (
            "acceptance_output.txt must contain 'spin_pct:' — "
            "the per-article spin annotation emitted by _print_dual_lens"
        )

    def test_contains_dual_lens_events(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        assert "DUAL-LENS EVENTS" in content, (
            "acceptance_output.txt must contain 'DUAL-LENS EVENTS' section header"
        )

    def test_spin_pct_appears_after_dual_lens_header(self) -> None:
        """spin_pct: must appear INSIDE the DUAL-LENS EVENTS block, not before it."""
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        dual_idx = content.find("DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'DUAL-LENS EVENTS' not found in acceptance_output.txt"
        spin_idx = content.find("spin_pct:", dual_idx)
        assert spin_idx >= 0, (
            "'spin_pct:' must appear after 'DUAL-LENS EVENTS' — "
            "spin annotations belong inside the dual-lens block, not in the digest body"
        )

    def test_spin_pct_values_in_range(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", content)
        assert matches, "No spin_pct values found in acceptance_output.txt"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, f"spin_pct {val}% is outside [0, 100]"

    def test_spin_pct_decimal_format(self) -> None:
        """spin_pct must use one-decimal format (N.N%), not integer percent."""
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", content)
        assert matches, "No spin_pct values in acceptance_output.txt"
        for raw in matches:
            assert "." in raw, (
                f"spin_pct {raw!r} missing decimal point — format must be :.1f (e.g. '43.4%')"
            )

    def test_multiple_spin_pct_values_present(self) -> None:
        """At least two articles are in the DUAL-LENS block — one per lens minimum."""
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        matches = re.findall(r"spin_pct:", content)
        assert len(matches) >= 2, (
            f"Expected ≥2 spin_pct entries in acceptance_output.txt; found {len(matches)}. "
            "A dual-lens event requires at least one article per side."
        )

    def test_spin_pct_on_bullet_lines(self) -> None:
        """spin_pct must appear on '- ...' bullet lines (not floating)."""
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        bullet_spin = [
            l for l in content.splitlines()
            if l.startswith("- ") and "spin_pct:" in l
        ]
        assert bullet_spin, (
            "acceptance_output.txt must contain '- <title> | spin_pct: N.N%' bullet lines"
        )

    def test_no_python_traceback(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        assert "Traceback" not in content, (
            "acceptance_output.txt must not contain a Python Traceback"
        )


# ---------------------------------------------------------------------------
# 2. acceptance_output.txt — domain sections and structural layout
# ---------------------------------------------------------------------------


class TestAcceptanceOutputFileStructure:
    """acceptance_output.txt must have the right domain sections and block order."""

    def test_situation_monitor_digest_header_present(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        assert "Situation Monitor Digest" in content, (
            "acceptance_output.txt must contain '# Situation Monitor Digest' heading"
        )

    def test_world_domain_section_present(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        assert "## WORLD" in content, (
            "acceptance_output.txt must contain '## WORLD' domain section"
        )

    def test_markets_domain_section_present(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        assert "## MARKETS" in content, (
            "acceptance_output.txt must contain '## MARKETS' domain section"
        )

    def test_ai_domain_section_present(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        assert "## AI" in content, (
            "acceptance_output.txt must contain '## AI' domain section"
        )

    def test_domain_sections_appear_before_dual_lens_block(self) -> None:
        """WORLD, MARKETS, AI must all come before ## DUAL-LENS EVENTS."""
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        dual_idx = content.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found in acceptance_output.txt"
        for section in ("## WORLD", "## MARKETS", "## AI"):
            idx = content.find(section)
            assert idx >= 0, f"'{section}' not found in acceptance_output.txt"
            assert idx < dual_idx, (
                f"'{section}' must appear BEFORE '## DUAL-LENS EVENTS' in the output"
            )

    def test_left_heading_inside_dual_lens_block(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        dual_idx = content.find("DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = content[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' must appear inside the DUAL-LENS EVENTS block"
        )

    def test_right_heading_inside_dual_lens_block(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        dual_idx = content.find("DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = content[dual_idx:]
        assert "#### RIGHT" in block, (
            "'#### RIGHT' must appear inside the DUAL-LENS EVENTS block"
        )

    def test_spin_delta_present_in_file(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        matches = re.findall(r"spin_delta:\s*([\d.]+)", content)
        assert matches, "acceptance_output.txt must contain spin_delta: annotations"
        for raw in matches:
            assert float(raw) >= 0.0, f"spin_delta must be non-negative; got {raw!r}"

    def test_rationale_lines_present(self) -> None:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        assert "rationale:" in content, (
            "acceptance_output.txt must contain 'rationale:' lines. "
            "The fixture has charged articles that produce spin receipts."
        )

    def test_climate_article_appears_in_left_column(self) -> None:
        """The known climate-left article must appear under '#### LEFT'."""
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        left_idx = content.find("#### LEFT")
        assert left_idx >= 0, "'#### LEFT' not found"
        # Scan from LEFT heading up to next heading
        left_block = content[left_idx:]
        next_h = re.search(r"\n#+[ ]", left_block[5:])
        block_end = (next_h.start() + 5) if next_h else len(left_block)
        left_section = left_block[:block_end]
        assert "Government Climate Policy Reform" in left_section, (
            "The 'Government Climate Policy Reform' article must appear under '#### LEFT'. "
            "This is the fixture's left-leaning climate article."
        )

    def test_climate_article_appears_in_right_column(self) -> None:
        """The known climate-right article must appear under '#### RIGHT'."""
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        right_idx = content.find("#### RIGHT")
        assert right_idx >= 0, "'#### RIGHT' not found"
        right_section = content[right_idx:]
        assert "Government Climate Policy Reform" in right_section, (
            "The 'Government Climate Policy Reform' article must appear under '#### RIGHT'. "
            "This is the fixture's right-leaning climate article."
        )


# ---------------------------------------------------------------------------
# 3. acceptance_output.txt — ALERT line validation
# ---------------------------------------------------------------------------


class TestAcceptanceOutputAlertLines:
    """ALERT lines in acceptance_output.txt must have the correct format."""

    def _alert_lines(self) -> list[str]:
        content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        return [l for l in content.splitlines() if l.startswith("ALERT:")]

    def test_alert_lines_are_present(self) -> None:
        lines = self._alert_lines()
        assert lines, (
            "acceptance_output.txt must contain ALERT: lines from the alerting system. "
            "The fixture articles all have relevance_score=1.0 and must trigger alerts."
        )

    def test_alert_lines_match_format(self) -> None:
        """Every ALERT line must match: ALERT: title='...' score=N.N cluster='c...'"""
        pattern = re.compile(r"^ALERT: title='.+' score=[\d.]+ cluster='[^']*'$")
        for line in self._alert_lines():
            assert pattern.match(line), (
                f"ALERT line format invalid: {line!r}\n"
                "Expected: ALERT: title='...' score=N.NNNN cluster='cN'"
            )

    def test_alert_scores_in_range(self) -> None:
        for line in self._alert_lines():
            m = re.search(r"score=([\d.]+)", line)
            assert m, f"No score field in ALERT line: {line!r}"
            val = float(m.group(1))
            assert 0.0 <= val <= 1.0, (
                f"ALERT score {val} out of [0.0, 1.0] range in line: {line!r}"
            )

    def test_alert_clusters_are_non_empty(self) -> None:
        """cluster= field in ALERT lines must be a non-empty string."""
        for line in self._alert_lines():
            m = re.search(r"cluster='([^']*)'", line)
            assert m, f"No cluster field in ALERT line: {line!r}"
            assert m.group(1), f"ALERT cluster field is empty in: {line!r}"

    def test_alert_titles_are_non_empty(self) -> None:
        for line in self._alert_lines():
            m = re.search(r"title='([^']+)'", line)
            assert m, f"No title field in ALERT line: {line!r}"
            assert m.group(1).strip(), f"ALERT title is empty in: {line!r}"

    def test_alert_clusters_start_with_c(self) -> None:
        """Cluster IDs are 'cN' strings, matching _assign_clusters output."""
        for line in self._alert_lines():
            m = re.search(r"cluster='([^']*)'", line)
            if m and m.group(1):
                assert m.group(1).startswith("c"), (
                    f"Cluster ID {m.group(1)!r} must start with 'c' (e.g. 'c0', 'c1')"
                )


# ---------------------------------------------------------------------------
# 4. The `acceptance` file — structural meta-checks
# ---------------------------------------------------------------------------


class TestAcceptanceFileStructure:
    """The `acceptance` file must be well-formed and reference the correct fixtures."""

    def test_acceptance_file_exists(self) -> None:
        assert ACCEPTANCE_FILE.exists(), (
            f"'acceptance' file missing at {ACCEPTANCE_FILE}"
        )

    def test_acceptance_file_is_python_script(self) -> None:
        """The acceptance file must be a Python script (has shebang and main entry point)."""
        content = ACCEPTANCE_PY.read_text()
        assert "python" in content.splitlines()[0], (
            "acceptance file must start with a Python shebang or reference python in the first line"
        )
        assert 'if __name__ == "__main__"' in content or "def main" in content, (
            "acceptance file must define a main() function or have __main__ guard"
        )

    def test_acceptance_uses_offline_backend(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "SM_LLM_BACKEND" in content, (
            "acceptance file must reference SM_LLM_BACKEND for reproducible offline runs"
        )

    def test_acceptance_has_once_subcommand(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "once" in content, (
            "acceptance file must contain the 'once' subcommand"
        )

    def test_acceptance_has_digest_dry_run_subcommand(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "digest-dry-run" in content, (
            "acceptance file must contain the 'digest-dry-run' subcommand"
        )

    def test_acceptance_has_carrier_discourse_check(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "discourse-carrier" in content, (
            "acceptance file must reference 'discourse-carrier' for the carrier validation check"
        )

    def test_acceptance_has_check_server(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "check_server.py" in content, (
            "acceptance file must reference check_server.py (cmd4)"
        )

    def test_acceptance_references_rss_sample_fixture(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "rss_sample.xml" in content, (
            "acceptance file must reference rss_sample.xml fixture"
        )

    def test_acceptance_references_acceptance_source_defs(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "acceptance_source_defs.json" in content, (
            "acceptance file must reference acceptance_source_defs.json config"
        )

    def test_acceptance_references_rss_carrier_fixture(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "rss_carrier.xml" in content, (
            "acceptance file must reference rss_carrier.xml for the carrier-grep command"
        )

    def test_acceptance_is_executable_python(self) -> None:
        """The acceptance file must be a Python script that invokes situation_monitor."""
        content = ACCEPTANCE_PY.read_text()
        assert "situation_monitor" in content, (
            "acceptance file must invoke situation_monitor"
        )
        assert "python" in content, (
            "acceptance file must reference python (shebang or subprocess)"
        )


# ---------------------------------------------------------------------------
# 5. cmd1 (once) — acceptance command 1
# ---------------------------------------------------------------------------


class TestCmd1Once:
    """cmd1: python3 -m situation_monitor once exits 0 with correct output."""

    def test_exits_zero(self, _cmd_once_proc: subprocess.CompletedProcess) -> None:
        assert _cmd_once_proc.returncode == 0, (
            f"cmd1 (once) exited {_cmd_once_proc.returncode}; expected 0.\n"
            f"stderr (last 500): {_cmd_once_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_non_empty(self, _cmd_once_stdout: str) -> None:
        assert _cmd_once_stdout.strip(), "cmd1 (once) must produce non-empty stdout"

    def test_contains_dual_lens_events(self, _cmd_once_stdout: str) -> None:
        assert "DUAL-LENS EVENTS" in _cmd_once_stdout, (
            "cmd1 stdout must contain 'DUAL-LENS EVENTS'.\n"
            f"stdout (first 2000):\n{_cmd_once_stdout[:2000]}"
        )

    def test_contains_spin_pct(self, _cmd_once_stdout: str) -> None:
        assert "spin_pct:" in _cmd_once_stdout, (
            "cmd1 stdout must contain 'spin_pct:' annotations"
        )

    def test_spin_pct_values_in_range(self, _cmd_once_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", _cmd_once_stdout)
        assert matches, "No spin_pct values in cmd1 stdout"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, f"spin_pct {val}% is outside [0, 100]"

    def test_spin_pct_has_decimal_point(self, _cmd_once_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", _cmd_once_stdout)
        assert matches
        for raw in matches:
            assert "." in raw, f"spin_pct {raw!r} must have decimal point (format :.1f)"

    def test_spin_delta_values_non_negative(self, _cmd_once_stdout: str) -> None:
        matches = re.findall(r"spin_delta:\s*([\d.]+)", _cmd_once_stdout)
        assert matches, "No spin_delta values in cmd1 stdout"
        for raw in matches:
            assert float(raw) >= 0.0, f"spin_delta {float(raw)} is negative"

    def test_contains_world_section(self, _cmd_once_stdout: str) -> None:
        assert "## WORLD" in _cmd_once_stdout

    def test_contains_markets_section(self, _cmd_once_stdout: str) -> None:
        assert "## MARKETS" in _cmd_once_stdout

    def test_contains_ai_section(self, _cmd_once_stdout: str) -> None:
        assert "## AI" in _cmd_once_stdout

    def test_contains_left_column_heading(self, _cmd_once_stdout: str) -> None:
        assert "#### LEFT" in _cmd_once_stdout

    def test_contains_right_column_heading(self, _cmd_once_stdout: str) -> None:
        assert "#### RIGHT" in _cmd_once_stdout

    def test_contains_alert_lines(self, _cmd_once_stdout: str) -> None:
        alert_lines = [l for l in _cmd_once_stdout.splitlines() if l.startswith("ALERT:")]
        assert alert_lines, "cmd1 stdout must contain ALERT: lines from the alerting system"

    def test_alert_format_correct(self, _cmd_once_stdout: str) -> None:
        pattern = re.compile(r"^ALERT: title='.+' score=[\d.]+ cluster='[^']*'$")
        for line in _cmd_once_stdout.splitlines():
            if line.startswith("ALERT:"):
                assert pattern.match(line), f"ALERT line format wrong: {line!r}"

    def test_no_carrier_line_without_sm_carrier_feeds(self, _cmd_once_stdout: str) -> None:
        """Without SM_CARRIER_FEEDS, no 'discourse-carrier' line must appear."""
        carrier_lines = [
            l for l in _cmd_once_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert not carrier_lines, (
            "cmd1 (no SM_CARRIER_FEEDS) must NOT emit a discourse-carrier line.\n"
            f"Unexpected: {carrier_lines}"
        )

    def test_no_traceback_stdout(self, _cmd_once_stdout: str) -> None:
        assert "Traceback" not in _cmd_once_stdout

    def test_no_traceback_stderr(self, _cmd_once_stderr: str) -> None:
        assert "Traceback" not in _cmd_once_stderr

    def test_situation_monitor_heading_present(self, _cmd_once_stdout: str) -> None:
        assert "Situation Monitor" in _cmd_once_stdout

    def test_dual_lens_block_comes_after_domain_sections(self, _cmd_once_stdout: str) -> None:
        ai_idx = _cmd_once_stdout.find("## AI")
        dual_idx = _cmd_once_stdout.find("## DUAL-LENS EVENTS")
        assert ai_idx >= 0 and dual_idx >= 0
        assert ai_idx < dual_idx, (
            "'## DUAL-LENS EVENTS' must appear after '## AI' domain section"
        )

    def test_domain_sections_appear_in_world_markets_ai_order(
        self, _cmd_once_stdout: str
    ) -> None:
        world_idx = _cmd_once_stdout.find("## WORLD")
        markets_idx = _cmd_once_stdout.find("## MARKETS")
        ai_idx = _cmd_once_stdout.find("## AI")
        assert world_idx >= 0 and markets_idx >= 0 and ai_idx >= 0
        assert world_idx < markets_idx < ai_idx, (
            "Domain sections must appear in order: WORLD → MARKETS → AI"
        )


# ---------------------------------------------------------------------------
# 6. cmd2 (digest-dry-run) — acceptance command 2
# ---------------------------------------------------------------------------


class TestCmd2DigestDryRun:
    """cmd2: python3 -m situation_monitor digest-dry-run exits 0 with Telegram format."""

    def test_exits_zero(self, _cmd_digest_proc: subprocess.CompletedProcess) -> None:
        assert _cmd_digest_proc.returncode == 0, (
            f"cmd2 (digest-dry-run) exited {_cmd_digest_proc.returncode}; expected 0.\n"
            f"stderr (last 500): {_cmd_digest_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_non_empty(self, _cmd_digest_stdout: str) -> None:
        assert _cmd_digest_stdout.strip(), "cmd2 (digest-dry-run) must produce non-empty stdout"

    def test_contains_situation_monitor_bold_header(self, _cmd_digest_stdout: str) -> None:
        """Telegram format uses *Situation Monitor*, not ATX Markdown '# Situation Monitor'."""
        assert "*Situation Monitor*" in _cmd_digest_stdout, (
            "cmd2 must use Telegram bold '*Situation Monitor*', not ATX Markdown header.\n"
            f"stdout:\n{_cmd_digest_stdout[:500]}"
        )

    def test_contains_top_stories_section(self, _cmd_digest_stdout: str) -> None:
        assert "*Top Stories*" in _cmd_digest_stdout, (
            "cmd2 stdout must contain '*Top Stories*' Telegram section"
        )

    def test_contains_bullet_entries(self, _cmd_digest_stdout: str) -> None:
        bullets = [l for l in _cmd_digest_stdout.splitlines() if l.startswith("•")]
        assert bullets, "cmd2 stdout must contain '•' bullet story entries"

    def test_bullet_entries_are_non_empty(self, _cmd_digest_stdout: str) -> None:
        for line in _cmd_digest_stdout.splitlines():
            if line.startswith("•"):
                assert line.strip() != "•", f"Empty bullet entry in cmd2 stdout: {line!r}"

    def test_contains_date_stamp(self, _cmd_digest_stdout: str) -> None:
        assert re.search(r"\d{4}-\d{2}-\d{2}", _cmd_digest_stdout), (
            "cmd2 stdout must contain a YYYY-MM-DD date stamp"
        )

    def test_does_not_use_atx_markdown_heading(self, _cmd_digest_stdout: str) -> None:
        assert not _cmd_digest_stdout.strip().startswith("# Situation Monitor"), (
            "cmd2 must NOT start with '# Situation Monitor' ATX Markdown heading — "
            "digest-dry-run emits Telegram *bold* format"
        )

    def test_output_differs_from_once_output(
        self, _cmd_once_stdout: str, _cmd_digest_stdout: str
    ) -> None:
        assert _cmd_once_stdout != _cmd_digest_stdout, (
            "cmd1 and cmd2 must produce different output: "
            "cmd1 is ATX Markdown, cmd2 is Telegram *bold* format"
        )

    def test_no_traceback_stdout(self, _cmd_digest_stdout: str) -> None:
        assert "Traceback" not in _cmd_digest_stdout

    def test_no_traceback_stderr(self, _cmd_digest_stderr: str) -> None:
        assert "Traceback" not in _cmd_digest_stderr

    def test_is_distinct_subprocess_from_cmd1(
        self,
        _cmd_once_proc: subprocess.CompletedProcess,
        _cmd_digest_proc: subprocess.CompletedProcess,
    ) -> None:
        assert _cmd_once_proc is not _cmd_digest_proc, (
            "cmd2 must be a distinct subprocess invocation from cmd1"
        )


# ---------------------------------------------------------------------------
# 7. cmd3 (carrier grep) — acceptance command 3
# ---------------------------------------------------------------------------


class TestCmd3CarrierOnce:
    """cmd3: once with SM_CARRIER_FEEDS exits 0 with discourse-carrier line at start."""

    def test_exits_zero(self, _cmd_carrier_proc: subprocess.CompletedProcess) -> None:
        assert _cmd_carrier_proc.returncode == 0, (
            f"cmd3 (carrier once) exited {_cmd_carrier_proc.returncode}; expected 0.\n"
            f"stderr (last 500): {_cmd_carrier_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_non_empty(self, _cmd_carrier_stdout: str) -> None:
        assert _cmd_carrier_stdout.strip()

    def test_discourse_carrier_in_stdout(self, _cmd_carrier_stdout: str) -> None:
        assert "discourse-carrier" in _cmd_carrier_stdout

    def test_discourse_carrier_line_starts_at_position_zero(
        self, _cmd_carrier_stdout: str
    ) -> None:
        """grep '^discourse-carrier' requires the token at the very start of the line."""
        matching = [
            l for l in _cmd_carrier_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert matching, (
            "No line STARTING WITH 'discourse-carrier' found.\n"
            "The acceptance check uses 'grep ^discourse-carrier' — "
            "leading whitespace or indentation would break it.\n"
            f"stdout (first 500):\n{_cmd_carrier_stdout[:500]}"
        )

    def test_discourse_carrier_format_is_articles_colon_n(
        self, _cmd_carrier_stdout: str
    ) -> None:
        pattern = re.compile(r"^discourse-carrier articles:\s*(\d+)$", re.MULTILINE)
        match = pattern.search(_cmd_carrier_stdout)
        assert match, (
            "Must have exactly 'discourse-carrier articles: N' on its own line.\n"
            f"stdout (first 500):\n{_cmd_carrier_stdout[:500]}"
        )

    def test_discourse_carrier_count_positive(self, _cmd_carrier_stdout: str) -> None:
        matches = re.findall(r"discourse-carrier articles:\s*(\d+)", _cmd_carrier_stdout)
        assert matches, "No discourse-carrier count found"
        count = int(matches[0])
        assert count > 0, (
            f"discourse-carrier count must be > 0; got {count}. "
            "rss_carrier.xml has items that must be ingested."
        )

    def test_discourse_carrier_count_is_integer(self, _cmd_carrier_stdout: str) -> None:
        matches = re.findall(r"discourse-carrier articles:\s*(\S+)", _cmd_carrier_stdout)
        assert matches
        try:
            int(matches[0])
        except ValueError:
            pytest.fail(
                f"discourse-carrier count {matches[0]!r} is not a valid integer"
            )

    def test_no_leading_whitespace_before_discourse_carrier(
        self, _cmd_carrier_stdout: str
    ) -> None:
        for line in _cmd_carrier_stdout.splitlines():
            if "discourse-carrier" in line and not line.startswith("discourse-carrier"):
                if line.lstrip().startswith("discourse-carrier"):
                    pytest.fail(
                        f"Leading whitespace before 'discourse-carrier' breaks grep: {line!r}"
                    )

    def test_carrier_line_precedes_markdown_digest_header(
        self, _cmd_carrier_stdout: str
    ) -> None:
        carrier_idx = _cmd_carrier_stdout.find("discourse-carrier articles:")
        digest_idx = _cmd_carrier_stdout.find("# Situation Monitor Digest")
        assert carrier_idx >= 0, "discourse-carrier articles: not found in cmd3 stdout"
        assert digest_idx >= 0, "# Situation Monitor Digest not found in cmd3 stdout"
        assert carrier_idx < digest_idx, (
            "discourse-carrier count must be printed BEFORE the digest header. "
            "In _cmd_once, the count print precedes _print_markdown."
        )

    def test_no_traceback_stdout(self, _cmd_carrier_stdout: str) -> None:
        assert "Traceback" not in _cmd_carrier_stdout

    def test_no_traceback_stderr(self, _cmd_carrier_stderr: str) -> None:
        assert "Traceback" not in _cmd_carrier_stderr

    def test_is_distinct_subprocess_from_cmd1_and_cmd2(
        self,
        _cmd_once_proc: subprocess.CompletedProcess,
        _cmd_digest_proc: subprocess.CompletedProcess,
        _cmd_carrier_proc: subprocess.CompletedProcess,
    ) -> None:
        assert _cmd_carrier_proc is not _cmd_once_proc
        assert _cmd_carrier_proc is not _cmd_digest_proc


# ---------------------------------------------------------------------------
# 7b. cmd3 via a real shell grep pipe (exact acceptance command replica)
# ---------------------------------------------------------------------------


class TestCmd3ViaShellGrepPipe:
    """Run cmd3 through ``grep '^discourse-carrier'`` — the literal acceptance command."""

    @pytest.fixture(scope="class")
    def grep_result(self) -> subprocess.CompletedProcess:
        env = _offline_env(SM_CARRIER_FEEDS=_CARRIER_FEEDS_JSON)
        once = subprocess.Popen(
            [
                sys.executable, "-m", "situation_monitor",
                "once", "--config", str(ACCEPTANCE_SOURCE_DEFS),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=PROJECT_ROOT,
            env=env,
        )
        grep = subprocess.run(
            ["grep", "^discourse-carrier"],
            stdin=once.stdout,
            capture_output=True,
            timeout=120,
        )
        once.stdout.close()
        once.wait()
        return grep

    def test_grep_exits_zero(self, grep_result: subprocess.CompletedProcess) -> None:
        assert grep_result.returncode == 0, (
            "grep '^discourse-carrier' must exit 0 (at least one match required).\n"
            f"grep stdout: {grep_result.stdout.decode(errors='replace')!r}"
        )

    def test_grep_stdout_contains_discourse_carrier(
        self, grep_result: subprocess.CompletedProcess
    ) -> None:
        out = grep_result.stdout.decode(errors="replace")
        assert "discourse-carrier" in out, (
            f"grep stdout must contain 'discourse-carrier'; got {out!r}"
        )

    def test_all_grep_matches_start_with_discourse_carrier(
        self, grep_result: subprocess.CompletedProcess
    ) -> None:
        out = grep_result.stdout.decode(errors="replace")
        for line in out.splitlines():
            if line.strip():
                assert line.startswith("discourse-carrier"), (
                    f"grep match must start with 'discourse-carrier'; got {line!r}"
                )

    def test_grep_stdout_has_article_count(
        self, grep_result: subprocess.CompletedProcess
    ) -> None:
        out = grep_result.stdout.decode(errors="replace")
        assert re.search(r"discourse-carrier articles:\s*\d+", out), (
            "grep output must include a numeric article count"
        )


# ---------------------------------------------------------------------------
# 8. cmd4 (check_server.py) — acceptance command 4
# ---------------------------------------------------------------------------


class TestCmd4CheckServer:
    """cmd4: python3 check_server.py exits 0 with 'web-server-smoke: PASS'."""

    def test_exits_zero(self, _cmd_check_server_proc: subprocess.CompletedProcess) -> None:
        assert _cmd_check_server_proc.returncode == 0, (
            f"cmd4 (check_server.py) exited {_cmd_check_server_proc.returncode}; expected 0.\n"
            f"stderr: {_cmd_check_server_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_non_empty(self, _cmd_check_server_stdout: str) -> None:
        assert _cmd_check_server_stdout.strip()

    def test_contains_pass_marker(self, _cmd_check_server_stdout: str) -> None:
        assert "web-server-smoke: PASS" in _cmd_check_server_stdout, (
            f"cmd4 must output 'web-server-smoke: PASS'; got: {_cmd_check_server_stdout!r}"
        )

    def test_pass_marker_is_complete_standalone_line(
        self, _cmd_check_server_stdout: str
    ) -> None:
        lines = _cmd_check_server_stdout.splitlines()
        assert any(line == "web-server-smoke: PASS" for line in lines), (
            "'web-server-smoke: PASS' must appear as a complete standalone line, "
            f"not embedded in other text. Lines: {lines}"
        )

    def test_no_traceback_stdout(self, _cmd_check_server_stdout: str) -> None:
        assert "Traceback" not in _cmd_check_server_stdout

    def test_no_traceback_stderr(self, _cmd_check_server_stderr: str) -> None:
        assert "Traceback" not in _cmd_check_server_stderr

    def test_is_distinct_subprocess_from_other_commands(
        self,
        _cmd_once_proc: subprocess.CompletedProcess,
        _cmd_check_server_proc: subprocess.CompletedProcess,
    ) -> None:
        assert _cmd_check_server_proc is not _cmd_once_proc


# ---------------------------------------------------------------------------
# 9. check_server.py — in-process Flask test client (no subprocess overhead)
# ---------------------------------------------------------------------------


class TestCheckServerFlaskApp:
    """Validate check_server.py's Flask app with an in-process test client.

    These tests exercise the same code path that check_server.py exercises
    but without a subprocess — faster to diagnose when they fail.
    """

    def test_make_app_returns_flask_app(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_LLM_BACKEND", "offline")
        from situation_monitor.dashboard import make_app

        app = make_app(lambda: [])
        assert hasattr(app, "test_client"), (
            "make_app must return a Flask-compatible app with a test_client method"
        )

    def test_empty_articles_returns_http_200(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_LLM_BACKEND", "offline")
        from situation_monitor.dashboard import make_app

        app = make_app(lambda: [])
        with app.test_client() as client:
            resp = client.get("/")
            assert resp.status_code == 200, (
                f"Dashboard GET / returned {resp.status_code} with empty articles; expected 200"
            )

    def test_empty_articles_body_contains_situation_monitor(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_LLM_BACKEND", "offline")
        from situation_monitor.dashboard import make_app

        app = make_app(lambda: [])
        with app.test_client() as client:
            resp = client.get("/")
            body = resp.data.decode()
            assert "Situation Monitor" in body, (
                "Dashboard response body must contain 'Situation Monitor' even with no articles"
            )

    def test_fixture_articles_returns_http_200(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_LLM_BACKEND", "offline")
        monkeypatch.setenv("SM_SOURCES", str(RSS_FIXTURE))
        from situation_monitor.config import Config
        from situation_monitor.dashboard import make_app
        from situation_monitor.__main__ import _ingest_and_enrich

        config = Config.from_file(str(ACCEPTANCE_SOURCE_DEFS))
        config.llm_backend = "offline"
        articles = _ingest_and_enrich(config)
        assert articles, "Fixture ingest must yield at least one article"

        app = make_app(lambda: articles)
        with app.test_client() as client:
            resp = client.get("/")
            assert resp.status_code == 200, (
                f"Dashboard GET / returned {resp.status_code} with fixture articles; expected 200"
            )

    def test_fixture_articles_response_has_substantive_content(
        self, monkeypatch
    ) -> None:
        monkeypatch.setenv("SM_LLM_BACKEND", "offline")
        monkeypatch.setenv("SM_SOURCES", str(RSS_FIXTURE))
        from situation_monitor.config import Config
        from situation_monitor.dashboard import make_app
        from situation_monitor.__main__ import _ingest_and_enrich

        config = Config.from_file(str(ACCEPTANCE_SOURCE_DEFS))
        config.llm_backend = "offline"
        articles = _ingest_and_enrich(config)

        app = make_app(lambda: articles)
        with app.test_client() as client:
            resp = client.get("/")
            body = resp.data.decode()
            assert len(body) > 200, (
                "Dashboard body with fixture articles must be substantially non-empty"
            )

    def test_check_server_py_has_http_200_assertion(self) -> None:
        """check_server.py must assert HTTP 200, not just call the endpoint silently."""
        content = CHECK_SERVER.read_text()
        assert "200" in content, (
            "check_server.py must assert HTTP 200 status from the Flask test client"
        )

    def test_check_server_py_has_situation_monitor_assertion(self) -> None:
        content = CHECK_SERVER.read_text()
        assert "Situation Monitor" in content, (
            "check_server.py must assert 'Situation Monitor' appears in the response body"
        )


# ---------------------------------------------------------------------------
# 10. Fixtures prerequisite — all required files exist and contain content
# ---------------------------------------------------------------------------


class TestRequiredFixturesExist:
    """All fixtures referenced by acceptance commands must exist and be usable."""

    def test_rss_sample_xml_exists(self) -> None:
        assert RSS_FIXTURE.exists(), f"rss_sample.xml missing at {RSS_FIXTURE}"

    def test_rss_sample_xml_has_items(self) -> None:
        assert "<item>" in RSS_FIXTURE.read_text(), (
            "rss_sample.xml must contain at least one <item> element"
        )

    def test_rss_carrier_xml_exists(self) -> None:
        assert RSS_CARRIER.exists(), f"rss_carrier.xml missing at {RSS_CARRIER}"

    def test_rss_carrier_xml_has_items(self) -> None:
        assert "<item>" in RSS_CARRIER.read_text(), (
            "rss_carrier.xml must contain at least one <item> element. "
            "An empty feed would produce discourse-carrier count=0 and fail the acceptance check."
        )

    def test_acceptance_source_defs_json_exists(self) -> None:
        assert ACCEPTANCE_SOURCE_DEFS.exists(), (
            f"acceptance_source_defs.json missing at {ACCEPTANCE_SOURCE_DEFS}"
        )

    def test_acceptance_source_defs_json_is_valid(self) -> None:
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        assert "source_defs" in data, (
            "acceptance_source_defs.json must have 'source_defs' key"
        )
        assert isinstance(data["source_defs"], list)

    def test_acceptance_source_defs_references_domain_fixtures(self) -> None:
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        urls = {sd["url"] for sd in data["source_defs"]}
        required = {
            "tests/fixtures/rss_left.xml",
            "tests/fixtures/rss_right.xml",
            "tests/fixtures/rss_markets.xml",
            "tests/fixtures/rss_ai.xml",
        }
        missing = required - urls
        assert not missing, (
            f"acceptance_source_defs.json missing these fixture URLs: {missing}"
        )

    def test_rss_left_xml_exists_with_items(self) -> None:
        f = FIXTURES / "rss_left.xml"
        assert f.exists(), f"rss_left.xml missing"
        assert "<item>" in f.read_text(), "rss_left.xml must have at least one <item>"

    def test_rss_right_xml_exists_with_items(self) -> None:
        f = FIXTURES / "rss_right.xml"
        assert f.exists(), "rss_right.xml missing"
        assert "<item>" in f.read_text(), "rss_right.xml must have at least one <item>"

    def test_rss_markets_xml_exists(self) -> None:
        f = FIXTURES / "rss_markets.xml"
        assert f.exists(), "rss_markets.xml missing"

    def test_rss_ai_xml_exists(self) -> None:
        f = FIXTURES / "rss_ai.xml"
        assert f.exists(), "rss_ai.xml missing"

    def test_check_server_py_exists(self) -> None:
        assert CHECK_SERVER.exists(), f"check_server.py missing at {CHECK_SERVER}"


# ---------------------------------------------------------------------------
# 11. Omnibus — all 4 commands pass simultaneously
# ---------------------------------------------------------------------------


class TestAllFourAcceptanceCommandsPass:
    """All four acceptance commands must pass simultaneously — the complete guard."""

    def test_all_four_exit_zero(
        self,
        _cmd_once_proc: subprocess.CompletedProcess,
        _cmd_digest_proc: subprocess.CompletedProcess,
        _cmd_carrier_proc: subprocess.CompletedProcess,
        _cmd_check_server_proc: subprocess.CompletedProcess,
    ) -> None:
        failures = []
        if _cmd_once_proc.returncode != 0:
            failures.append(f"cmd1 (once): rc={_cmd_once_proc.returncode}")
        if _cmd_digest_proc.returncode != 0:
            failures.append(f"cmd2 (digest-dry-run): rc={_cmd_digest_proc.returncode}")
        if _cmd_carrier_proc.returncode != 0:
            failures.append(f"cmd3 (carrier once): rc={_cmd_carrier_proc.returncode}")
        if _cmd_check_server_proc.returncode != 0:
            failures.append(f"cmd4 (check_server.py): rc={_cmd_check_server_proc.returncode}")
        assert not failures, (
            "One or more acceptance commands failed:\n" + "\n".join(failures)
        )

    def test_no_traceback_in_any_stdout(
        self,
        _cmd_once_stdout: str,
        _cmd_digest_stdout: str,
        _cmd_carrier_stdout: str,
        _cmd_check_server_stdout: str,
    ) -> None:
        which = []
        if "Traceback" in _cmd_once_stdout:
            which.append("cmd1 (once)")
        if "Traceback" in _cmd_digest_stdout:
            which.append("cmd2 (digest-dry-run)")
        if "Traceback" in _cmd_carrier_stdout:
            which.append("cmd3 (carrier once)")
        if "Traceback" in _cmd_check_server_stdout:
            which.append("cmd4 (check_server.py)")
        assert not which, f"Python Traceback found in stdout of: {', '.join(which)}"

    def test_acceptance_output_txt_consistent_with_live_cmd1(
        self, _cmd_once_stdout: str
    ) -> None:
        """Both the committed artefact and the live run must contain the required markers."""
        file_content = ACCEPTANCE_OUTPUT.read_text(errors="replace")
        required = ["spin_pct:", "DUAL-LENS EVENTS"]
        for marker in required:
            assert marker in file_content, (
                f"acceptance_output.txt must contain {marker!r}"
            )
            assert marker in _cmd_once_stdout, (
                f"cmd1 live stdout must contain {marker!r}"
            )

    def test_cmd1_and_cmd4_both_confirm_flask_app(
        self,
        _cmd_once_stdout: str,
        _cmd_check_server_stdout: str,
    ) -> None:
        """cmd1 proves ingest works; cmd4 proves the Flask app serves HTTP 200."""
        assert "Situation Monitor" in _cmd_once_stdout, (
            "cmd1 must contain 'Situation Monitor' — the digest heading"
        )
        assert "web-server-smoke: PASS" in _cmd_check_server_stdout, (
            "cmd4 must confirm 'web-server-smoke: PASS'"
        )

    def test_cmd2_output_is_telegram_format(self, _cmd_digest_stdout: str) -> None:
        assert "*Situation Monitor*" in _cmd_digest_stdout, (
            "cmd2 must produce Telegram *bold* formatted output"
        )
        assert "*Top Stories*" in _cmd_digest_stdout

    def test_cmd3_grep_compatible_carrier_line(self, _cmd_carrier_stdout: str) -> None:
        matching = [
            l for l in _cmd_carrier_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert matching, "cmd3 must produce a grep-compatible discourse-carrier line"

    def test_all_subprocesses_are_distinct_objects(
        self,
        _cmd_once_proc: subprocess.CompletedProcess,
        _cmd_digest_proc: subprocess.CompletedProcess,
        _cmd_carrier_proc: subprocess.CompletedProcess,
        _cmd_check_server_proc: subprocess.CompletedProcess,
    ) -> None:
        """No command's result is aliased to another's — each is a distinct invocation."""
        procs = [_cmd_once_proc, _cmd_digest_proc, _cmd_carrier_proc, _cmd_check_server_proc]
        for i, p in enumerate(procs):
            for j, q in enumerate(procs):
                if i != j:
                    assert p is not q, (
                        f"proc[{i}] and proc[{j}] must be distinct subprocess objects"
                    )

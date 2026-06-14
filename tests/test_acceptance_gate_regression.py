"""Independent regression gate: all 4 acceptance commands run as isolated subprocesses.

Acceptance commands under test (from ./acceptance):
  cmd1 — situation_monitor once      (offline, fixture RSS + source defs)
  cmd2 — situation_monitor digest-dry-run
  cmd3 — situation_monitor once with SM_CARRIER_FEEDS (produces discourse-carrier lines)
  cmd4 — check_server.py             (Flask smoke test → prints PASS)

Each command runs in its own module-scoped fixture with cwd=PROJECT_ROOT and
timeout=120.  A failure in one fixture does NOT affect the others — no exit-code
masking, no sequential dependency, no recursive pytest invocation.
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
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"
RSS_CARRIER = FIXTURES / "rss_carrier.xml"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"

_CARRIER_FEEDS_JSON = json.dumps(
    [{"url": "tests/fixtures/rss_carrier.xml", "country": "US", "lean": "centre"}]
)


# ---------------------------------------------------------------------------
# Shared environment helpers
# ---------------------------------------------------------------------------


def _offline_env(**extra: str) -> dict[str, str]:
    """Return an environment dict with the offline LLM backend forced on."""
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
        **extra,
    }


def _offline_env_no_sources(**extra: str) -> dict[str, str]:
    """Offline env without SM_SOURCES override — used for check_server.py."""
    base = dict(os.environ)
    base["SM_LLM_BACKEND"] = "offline"
    base.update(extra)
    return base


# ---------------------------------------------------------------------------
# Fixture prerequisites
# ---------------------------------------------------------------------------


class TestFixtureFiles:
    """Required fixture files must exist before any subprocess can succeed."""

    def test_rss_sample_exists(self) -> None:
        assert RSS_FIXTURE.exists(), f"Missing fixture: {RSS_FIXTURE}"

    def test_rss_carrier_exists(self) -> None:
        assert RSS_CARRIER.exists(), f"Missing fixture: {RSS_CARRIER}"

    def test_acceptance_source_defs_exists(self) -> None:
        assert ACCEPTANCE_SOURCE_DEFS.exists(), (
            f"Missing fixture: {ACCEPTANCE_SOURCE_DEFS}"
        )

    def test_check_server_exists(self) -> None:
        assert CHECK_SERVER.exists(), f"Missing script: {CHECK_SERVER}"

    def test_acceptance_source_defs_valid_json(self) -> None:
        try:
            data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        except Exception as exc:
            pytest.fail(f"acceptance_source_defs.json is not valid JSON: {exc}")
        assert isinstance(data.get("source_defs"), list), (
            "acceptance_source_defs.json must contain a 'source_defs' list"
        )

    def test_carrier_json_encodes_carrier_fixture_path(self) -> None:
        feeds = json.loads(_CARRIER_FEEDS_JSON)
        assert len(feeds) == 1
        assert feeds[0]["url"] == "tests/fixtures/rss_carrier.xml"


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixtures — one per acceptance command
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cmd1_result() -> subprocess.CompletedProcess:
    """cmd1: situation_monitor once — offline, fixture sources."""
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
def cmd1_stdout(cmd1_result: subprocess.CompletedProcess) -> str:
    return cmd1_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd2_result() -> subprocess.CompletedProcess:
    """cmd2: situation_monitor digest-dry-run — independent subprocess."""
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
def cmd2_stdout(cmd2_result: subprocess.CompletedProcess) -> str:
    return cmd2_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd3_result() -> subprocess.CompletedProcess:
    """cmd3: situation_monitor once with SM_CARRIER_FEEDS — carrier discourse output."""
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
def cmd3_stdout(cmd3_result: subprocess.CompletedProcess) -> str:
    return cmd3_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd4_result() -> subprocess.CompletedProcess:
    """cmd4: check_server.py — Flask web-server smoke test."""
    return subprocess.run(
        [sys.executable, str(CHECK_SERVER)],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env_no_sources(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def cmd4_stdout(cmd4_result: subprocess.CompletedProcess) -> str:
    return cmd4_result.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# Exit-code assertions: all 4 commands must exit 0
# ---------------------------------------------------------------------------


class TestExitCodes:
    """Each acceptance command must exit 0 in its own subprocess."""

    def test_cmd1_exits_zero(self, cmd1_result: subprocess.CompletedProcess) -> None:
        assert cmd1_result.returncode == 0, (
            f"cmd1 (once) exited {cmd1_result.returncode}; expected 0.\n"
            f"stderr:\n{cmd1_result.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout tail:\n{cmd1_result.stdout.decode(errors='replace')[-500:]}"
        )

    def test_cmd2_exits_zero(self, cmd2_result: subprocess.CompletedProcess) -> None:
        assert cmd2_result.returncode == 0, (
            f"cmd2 (digest-dry-run) exited {cmd2_result.returncode}; expected 0.\n"
            f"stderr:\n{cmd2_result.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout tail:\n{cmd2_result.stdout.decode(errors='replace')[-500:]}"
        )

    def test_cmd3_exits_zero(self, cmd3_result: subprocess.CompletedProcess) -> None:
        assert cmd3_result.returncode == 0, (
            f"cmd3 (once+carrier) exited {cmd3_result.returncode}; expected 0.\n"
            f"stderr:\n{cmd3_result.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout tail:\n{cmd3_result.stdout.decode(errors='replace')[-500:]}"
        )

    def test_cmd4_exits_zero(self, cmd4_result: subprocess.CompletedProcess) -> None:
        assert cmd4_result.returncode == 0, (
            f"cmd4 (check_server.py) exited {cmd4_result.returncode}; expected 0.\n"
            f"stderr:\n{cmd4_result.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout tail:\n{cmd4_result.stdout.decode(errors='replace')[-500:]}"
        )


# ---------------------------------------------------------------------------
# Non-empty stdout: all 4 commands must produce output
# ---------------------------------------------------------------------------


class TestNonEmptyStdout:
    """Each command must write at least one non-whitespace byte to stdout."""

    def test_cmd1_stdout_nonempty(self, cmd1_stdout: str) -> None:
        assert cmd1_stdout.strip(), "cmd1 (once) produced no stdout output"

    def test_cmd2_stdout_nonempty(self, cmd2_stdout: str) -> None:
        assert cmd2_stdout.strip(), "cmd2 (digest-dry-run) produced no stdout output"

    def test_cmd3_stdout_nonempty(self, cmd3_stdout: str) -> None:
        assert cmd3_stdout.strip(), "cmd3 (once+carrier) produced no stdout output"

    def test_cmd4_stdout_nonempty(self, cmd4_stdout: str) -> None:
        assert cmd4_stdout.strip(), "cmd4 (check_server.py) produced no stdout output"


# ---------------------------------------------------------------------------
# cmd1 content contract
# ---------------------------------------------------------------------------


class TestCmd1SectionHeaders:
    """cmd1 stdout must contain all required Markdown section headers."""

    def test_contains_world_header(self, cmd1_stdout: str) -> None:
        assert "## WORLD" in cmd1_stdout, (
            "cmd1 stdout must contain '## WORLD' section header"
        )

    def test_contains_markets_header(self, cmd1_stdout: str) -> None:
        assert "## MARKETS" in cmd1_stdout, (
            "cmd1 stdout must contain '## MARKETS' section header"
        )

    def test_contains_ai_header(self, cmd1_stdout: str) -> None:
        assert "## AI" in cmd1_stdout, (
            "cmd1 stdout must contain '## AI' section header"
        )

    def test_contains_dual_lens_header(self, cmd1_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in cmd1_stdout, (
            "cmd1 stdout must contain '## DUAL-LENS EVENTS' section header"
        )

    def test_section_headers_are_h2_lines(self, cmd1_stdout: str) -> None:
        lines = cmd1_stdout.splitlines()
        h2_headers = [l for l in lines if l.startswith("## ")]
        labels = {l[3:].strip() for l in h2_headers}
        for expected in ("WORLD", "MARKETS", "AI", "DUAL-LENS EVENTS"):
            assert expected in labels, (
                f"'## {expected}' not found as a proper H2 heading line.\n"
                f"H2 lines found: {h2_headers}"
            )


class TestCmd1DualLensColumns:
    """cmd1 stdout must contain LEFT and RIGHT column headings inside DUAL-LENS block."""

    def test_contains_left_heading(self, cmd1_stdout: str) -> None:
        assert "#### LEFT" in cmd1_stdout, (
            "cmd1 stdout must contain '#### LEFT' dual-lens column heading"
        )

    def test_contains_right_heading(self, cmd1_stdout: str) -> None:
        assert "#### RIGHT" in cmd1_stdout, (
            "cmd1 stdout must contain '#### RIGHT' dual-lens column heading"
        )

    def test_left_heading_is_h4_line(self, cmd1_stdout: str) -> None:
        h4_left = [l for l in cmd1_stdout.splitlines() if l.startswith("#### LEFT")]
        assert h4_left, "No line starting with '#### LEFT' found in cmd1 stdout"

    def test_right_heading_is_h4_line(self, cmd1_stdout: str) -> None:
        h4_right = [l for l in cmd1_stdout.splitlines() if l.startswith("#### RIGHT")]
        assert h4_right, "No line starting with '#### RIGHT' found in cmd1 stdout"

    def test_left_and_right_inside_dual_lens_block(self, cmd1_stdout: str) -> None:
        idx = cmd1_stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0, "'## DUAL-LENS EVENTS' not found in cmd1 stdout"
        block = cmd1_stdout[idx:]
        assert "#### LEFT" in block, "'#### LEFT' must appear after '## DUAL-LENS EVENTS'"
        assert "#### RIGHT" in block, "'#### RIGHT' must appear after '## DUAL-LENS EVENTS'"

    def test_left_heading_precedes_right_in_dual_lens_block(
        self, cmd1_stdout: str
    ) -> None:
        idx = cmd1_stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0
        block = cmd1_stdout[idx:]
        left_pos = block.find("#### LEFT")
        right_pos = block.find("#### RIGHT")
        assert left_pos < right_pos, (
            "'#### LEFT' must appear before '#### RIGHT' in the DUAL-LENS block;\n"
            f"left_pos={left_pos}, right_pos={right_pos}"
        )


class TestCmd1SpinPct:
    """cmd1 stdout must contain spin_pct: annotations with % symbol."""

    def test_spin_pct_keyword_present(self, cmd1_stdout: str) -> None:
        assert "spin_pct:" in cmd1_stdout, (
            "cmd1 stdout must contain 'spin_pct:' annotation"
        )

    def test_spin_pct_has_percent_symbol(self, cmd1_stdout: str) -> None:
        matches = re.findall(r"spin_pct:[^\n]*%", cmd1_stdout)
        assert matches, (
            "cmd1 stdout must contain 'spin_pct:' followed by a '%' on the same line"
        )

    def test_spin_pct_numeric_value_before_percent(self, cmd1_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", cmd1_stdout)
        assert matches, (
            "cmd1 stdout must contain 'spin_pct: N.N%' with a numeric value"
        )
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range"
            )

    def test_spin_pct_in_dual_lens_block(self, cmd1_stdout: str) -> None:
        idx = cmd1_stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0, "'## DUAL-LENS EVENTS' block not found"
        block = cmd1_stdout[idx:]
        assert "spin_pct:" in block, (
            "'spin_pct:' must appear inside the '## DUAL-LENS EVENTS' block"
        )
        assert "%" in block[block.find("spin_pct:"):block.find("spin_pct:") + 50], (
            "'spin_pct:' in DUAL-LENS block must be followed by a '%' symbol"
        )

    def test_spin_pct_on_bullet_line(self, cmd1_stdout: str) -> None:
        spin_bullets = [
            l for l in cmd1_stdout.splitlines()
            if "spin_pct:" in l and "%" in l
        ]
        assert spin_bullets, (
            "No line containing both 'spin_pct:' and '%' found in cmd1 stdout"
        )

    def test_multiple_spin_pct_values(self, cmd1_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*[\d.]+%", cmd1_stdout)
        assert len(matches) >= 2, (
            f"Expected at least 2 spin_pct annotations (one per dual-lens article), "
            f"found {len(matches)}: {matches}"
        )


# ---------------------------------------------------------------------------
# cmd3 content contract
# ---------------------------------------------------------------------------


class TestCmd3DiscoursCarrier:
    """cmd3 stdout must contain a line starting with 'discourse-carrier'."""

    def test_discourse_carrier_line_present(self, cmd3_stdout: str) -> None:
        lines = cmd3_stdout.splitlines()
        matching = [l for l in lines if l.startswith("discourse-carrier")]
        assert matching, (
            "cmd3 stdout must contain at least one line starting with 'discourse-carrier'.\n"
            "This mirrors the acceptance check: grep '^discourse-carrier'.\n"
            f"stdout (first 2000 chars):\n{cmd3_stdout[:2000]}"
        )

    def test_discourse_carrier_line_starts_at_column_zero(
        self, cmd3_stdout: str
    ) -> None:
        # grep '^discourse-carrier' matches only if the token is at position 0
        lines = cmd3_stdout.splitlines()
        matching = [l for l in lines if l.startswith("discourse-carrier")]
        assert matching, (
            "No line found STARTING with 'discourse-carrier' (column 0).\n"
            "Lines that contain but do not start with the token would fail grep '^discourse-carrier'."
        )
        # Confirm there's no leading whitespace on any matching line
        for line in matching:
            assert not line[0].isspace(), (
                f"discourse-carrier line has leading whitespace: {line!r}"
            )

    def test_discourse_carrier_count_is_positive(self, cmd3_stdout: str) -> None:
        match = re.search(r"discourse-carrier articles:\s*(\d+)", cmd3_stdout)
        assert match, (
            "cmd3 stdout must contain 'discourse-carrier articles: N' count line"
        )
        count = int(match.group(1))
        assert count > 0, (
            f"discourse-carrier article count must be > 0; got {count}"
        )

    def test_cmd3_no_sm_sources_override_in_env(self) -> None:
        # cmd3 uses SM_CARRIER_FEEDS — verify we don't accidentally pass SM_SOURCES
        # by checking the carrier JSON parses to the correct fixture path
        feeds = json.loads(_CARRIER_FEEDS_JSON)
        assert feeds[0]["url"] == "tests/fixtures/rss_carrier.xml", (
            "cmd3 must load from rss_carrier.xml via SM_CARRIER_FEEDS"
        )


# ---------------------------------------------------------------------------
# cmd4 content contract
# ---------------------------------------------------------------------------


class TestCmd4Pass:
    """cmd4 (check_server.py) must print 'PASS'."""

    def test_pass_token_present(self, cmd4_stdout: str) -> None:
        assert "PASS" in cmd4_stdout, (
            "cmd4 (check_server.py) stdout must contain 'PASS'.\n"
            f"stdout received:\n{cmd4_stdout}"
        )

    def test_pass_on_its_own_line(self, cmd4_stdout: str) -> None:
        pass_lines = [l for l in cmd4_stdout.splitlines() if "PASS" in l]
        assert pass_lines, (
            "No line containing 'PASS' found in cmd4 stdout"
        )

    def test_no_traceback_in_cmd4(self, cmd4_result: subprocess.CompletedProcess) -> None:
        stdout = cmd4_result.stdout.decode(errors="replace")
        stderr = cmd4_result.stderr.decode(errors="replace")
        assert "Traceback" not in stdout, (
            f"cmd4 stdout must not contain a Python traceback:\n{stdout[:2000]}"
        )
        assert "Traceback" not in stderr, (
            f"cmd4 stderr must not contain a Python traceback:\n{stderr[:2000]}"
        )

    def test_cmd4_cwd_is_project_root(self) -> None:
        # Smoke-test: check_server.py uses relative path 'tests/fixtures/...'
        # so PROJECT_ROOT must exist and contain tests/
        assert (PROJECT_ROOT / "tests").is_dir(), (
            f"PROJECT_ROOT ({PROJECT_ROOT}) must contain tests/ for check_server.py "
            "relative paths to resolve"
        )


# ---------------------------------------------------------------------------
# Subprocess isolation: independence between all 4 fixtures
# ---------------------------------------------------------------------------


class TestSubprocessIsolation:
    """All 4 subprocess objects must be distinct, independent process objects."""

    def test_all_four_are_distinct_objects(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
        cmd3_result: subprocess.CompletedProcess,
        cmd4_result: subprocess.CompletedProcess,
    ) -> None:
        results = [cmd1_result, cmd2_result, cmd3_result, cmd4_result]
        ids = [id(r) for r in results]
        assert len(set(ids)) == 4, (
            "All 4 cmd fixtures must be distinct CompletedProcess objects"
        )

    def test_each_uses_sys_executable(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
        cmd3_result: subprocess.CompletedProcess,
        cmd4_result: subprocess.CompletedProcess,
    ) -> None:
        for label, proc in [
            ("cmd1", cmd1_result),
            ("cmd2", cmd2_result),
            ("cmd3", cmd3_result),
            ("cmd4", cmd4_result),
        ]:
            assert isinstance(proc.args, list), (
                f"{label} must be launched as an args list, not a shell string"
            )
            assert proc.args[0] == sys.executable, (
                f"{label} args[0] must be sys.executable ({sys.executable!r}); "
                f"got {proc.args[0]!r}"
            )

    def test_no_recursive_pytest_invocation(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
        cmd3_result: subprocess.CompletedProcess,
        cmd4_result: subprocess.CompletedProcess,
    ) -> None:
        for label, proc in [
            ("cmd1", cmd1_result),
            ("cmd2", cmd2_result),
            ("cmd3", cmd3_result),
            ("cmd4", cmd4_result),
        ]:
            args = [str(a) for a in proc.args]
            # Detect "pytest" as a direct argument or "python -m pytest" pattern
            has_pytest_arg = "pytest" in args
            has_m_pytest = ("-m" in args and args[args.index("-m") + 1] == "pytest") if "-m" in args else False
            assert not has_pytest_arg and not has_m_pytest, (
                f"{label} must not invoke pytest recursively; args={proc.args!r}"
            )

    def test_cmd1_subcommand(self, cmd1_result: subprocess.CompletedProcess) -> None:
        assert "once" in cmd1_result.args, (
            f"cmd1 args must contain 'once'; got {cmd1_result.args!r}"
        )
        assert "digest-dry-run" not in cmd1_result.args, (
            "cmd1 must not include 'digest-dry-run' in args"
        )

    def test_cmd2_subcommand(self, cmd2_result: subprocess.CompletedProcess) -> None:
        assert "digest-dry-run" in cmd2_result.args, (
            f"cmd2 args must contain 'digest-dry-run'; got {cmd2_result.args!r}"
        )

    def test_cmd3_carrier_env_set(self, cmd3_result: subprocess.CompletedProcess) -> None:
        # The env is not stored on CompletedProcess, but we verify cmd3 produced
        # discourse-carrier output — which only happens when SM_CARRIER_FEEDS is set
        stdout = cmd3_result.stdout.decode(errors="replace")
        assert "discourse-carrier" in stdout, (
            "cmd3 must produce 'discourse-carrier' output, confirming SM_CARRIER_FEEDS was set"
        )

    def test_cmd4_invokes_check_server(
        self, cmd4_result: subprocess.CompletedProcess
    ) -> None:
        assert any(
            "check_server" in str(a) for a in cmd4_result.args
        ), (
            f"cmd4 args must reference check_server.py; got {cmd4_result.args!r}"
        )

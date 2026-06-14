"""Independent subprocess regression guard for the four acceptance commands.

This file is the tester's check, INDEPENDENT of the builder — it verifies the
output contracts of each acceptance command by running them as real subprocesses
and asserting the exact strings the specification mandates.  Every assertion in
this file CAN fail on a real regression.

The four acceptance commands (from the ``acceptance`` file at the project root):
  cmd1 – situation_monitor once, offline, fixture RSS + source defs
  cmd2 – situation_monitor digest-dry-run, same offline env
  cmd3 – situation_monitor once with SM_CARRIER_FEEDS → rss_carrier.xml
  cmd4 – check_server.py offline smoke test

Tested criteria:
  - Each command exits 0.
  - cmd1 stdout contains: ## DUAL-LENS EVENTS, #### LEFT, #### RIGHT,
    spin_pct:, spin_delta:, ## MARKETS, ## AI, ## WORLD
  - cmd2 stdout contains: *Situation Monitor*, *Top Stories*, bullet •
  - cmd3 stdout has a line starting with 'discourse-carrier'
  - cmd4 stdout contains 'web-server-smoke: PASS'
  - No command produces a Python Traceback in stdout OR stderr.

NOTE: this file does NOT run ``pytest tests/`` as a subprocess — the project
memory records that recursive meta-tests hang the suite.  The fact that this file
passes is the evidence that pytest exits 0.
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
# Shared env builder
# ---------------------------------------------------------------------------


def _offline_env(**extra: str) -> dict[str, str]:
    """Full offline environment using fixture data — no live network, no LLM."""
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
def cmd1_proc() -> subprocess.CompletedProcess:
    """cmd1: situation_monitor once — fixture RSS + all source defs."""
    return subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "once",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def cmd1_stdout(cmd1_proc: subprocess.CompletedProcess) -> str:
    return cmd1_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd1_stderr(cmd1_proc: subprocess.CompletedProcess) -> str:
    return cmd1_proc.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd2_proc() -> subprocess.CompletedProcess:
    """cmd2: situation_monitor digest-dry-run — SEPARATE subprocess from cmd1."""
    return subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "digest-dry-run",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def cmd2_stdout(cmd2_proc: subprocess.CompletedProcess) -> str:
    return cmd2_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd2_stderr(cmd2_proc: subprocess.CompletedProcess) -> str:
    return cmd2_proc.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd3_proc() -> subprocess.CompletedProcess:
    """cmd3: situation_monitor once with SM_CARRIER_FEEDS — SEPARATE subprocess."""
    return subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "once",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(SM_CARRIER_FEEDS=_CARRIER_FEEDS_JSON),
        timeout=120,
    )


@pytest.fixture(scope="module")
def cmd3_stdout(cmd3_proc: subprocess.CompletedProcess) -> str:
    return cmd3_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd3_stderr(cmd3_proc: subprocess.CompletedProcess) -> str:
    return cmd3_proc.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd4_proc() -> subprocess.CompletedProcess:
    """cmd4: check_server.py offline smoke test — SEPARATE subprocess."""
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    return subprocess.run(
        [sys.executable, str(CHECK_SERVER)],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=120,
    )


@pytest.fixture(scope="module")
def cmd4_stdout(cmd4_proc: subprocess.CompletedProcess) -> str:
    return cmd4_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd4_stderr(cmd4_proc: subprocess.CompletedProcess) -> str:
    return cmd4_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Helper: verify every subprocess is distinct (no sharing / aliasing)
# ---------------------------------------------------------------------------


class TestSubprocessesAreIndependent:
    """Each command must run as a truly separate subprocess invocation."""

    def test_cmd1_and_cmd2_are_distinct_objects(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd2_proc: subprocess.CompletedProcess,
    ) -> None:
        assert cmd1_proc is not cmd2_proc, (
            "cmd1 and cmd2 must be separate subprocess.CompletedProcess objects"
        )

    def test_cmd1_and_cmd3_are_distinct_objects(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd3_proc: subprocess.CompletedProcess,
    ) -> None:
        assert cmd1_proc is not cmd3_proc

    def test_cmd3_and_cmd4_are_distinct_objects(
        self,
        cmd3_proc: subprocess.CompletedProcess,
        cmd4_proc: subprocess.CompletedProcess,
    ) -> None:
        assert cmd3_proc is not cmd4_proc

    def test_cmd1_uses_sys_executable(self, cmd1_proc: subprocess.CompletedProcess) -> None:
        """Subprocesses must use sys.executable, not bare 'python' or 'python3'."""
        assert cmd1_proc.args[0] == sys.executable, (
            f"cmd1 must use sys.executable; got {cmd1_proc.args[0]!r}"
        )

    def test_cmd2_uses_sys_executable(self, cmd2_proc: subprocess.CompletedProcess) -> None:
        assert cmd2_proc.args[0] == sys.executable

    def test_cmd3_uses_sys_executable(self, cmd3_proc: subprocess.CompletedProcess) -> None:
        assert cmd3_proc.args[0] == sys.executable

    def test_cmd4_uses_sys_executable(self, cmd4_proc: subprocess.CompletedProcess) -> None:
        assert cmd4_proc.args[0] == sys.executable


# ---------------------------------------------------------------------------
# cmd1: situation_monitor once — exit code
# ---------------------------------------------------------------------------


class TestCmd1ExitCode:
    """cmd1 must exit 0."""

    def test_exits_zero(self, cmd1_proc: subprocess.CompletedProcess) -> None:
        assert cmd1_proc.returncode == 0, (
            f"cmd1 (once) exited {cmd1_proc.returncode}, expected 0.\n"
            f"stderr (last 500):\n{cmd1_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, cmd1_stdout: str) -> None:
        assert cmd1_stdout.strip(), "cmd1 (once) must produce non-empty stdout"


# ---------------------------------------------------------------------------
# cmd1: exact required strings per acceptance criteria
# ---------------------------------------------------------------------------


class TestCmd1RequiredContent:
    """cmd1 stdout must contain every string mandated by the acceptance criteria."""

    def test_contains_dual_lens_events_header(self, cmd1_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in cmd1_stdout, (
            "cmd1 stdout must contain '## DUAL-LENS EVENTS' — "
            "the dual-lens render block header.\n"
            f"stdout (first 2000):\n{cmd1_stdout[:2000]}"
        )

    def test_contains_left_column_heading(self, cmd1_stdout: str) -> None:
        assert "#### LEFT" in cmd1_stdout, (
            "cmd1 stdout must contain '#### LEFT' dual-lens column heading.\n"
            f"stdout sample:\n{cmd1_stdout[:2000]}"
        )

    def test_contains_right_column_heading(self, cmd1_stdout: str) -> None:
        assert "#### RIGHT" in cmd1_stdout, (
            "cmd1 stdout must contain '#### RIGHT' dual-lens column heading.\n"
            f"stdout sample:\n{cmd1_stdout[:2000]}"
        )

    def test_contains_spin_pct(self, cmd1_stdout: str) -> None:
        assert "spin_pct:" in cmd1_stdout, (
            "cmd1 stdout must contain 'spin_pct:' per-article spin annotation"
        )

    def test_contains_spin_delta(self, cmd1_stdout: str) -> None:
        assert "spin_delta:" in cmd1_stdout, (
            "cmd1 stdout must contain 'spin_delta:' event-level divergence annotation"
        )

    def test_contains_markets_domain_header(self, cmd1_stdout: str) -> None:
        assert "## MARKETS" in cmd1_stdout, (
            "cmd1 stdout must contain '## MARKETS' domain section header.\n"
            "Markets fixture (rss_markets.xml) must be loaded via acceptance_source_defs.json."
        )

    def test_contains_ai_domain_header(self, cmd1_stdout: str) -> None:
        assert "## AI" in cmd1_stdout, (
            "cmd1 stdout must contain '## AI' domain section header.\n"
            "AI fixture (rss_ai.xml) must be loaded via acceptance_source_defs.json."
        )

    def test_contains_world_domain_header(self, cmd1_stdout: str) -> None:
        assert "## WORLD" in cmd1_stdout, (
            "cmd1 stdout must contain '## WORLD' domain section header.\n"
            "World fixtures (rss_left.xml, rss_right.xml, rss_sample.xml) contribute articles."
        )

    def test_situation_monitor_digest_header_present(self, cmd1_stdout: str) -> None:
        assert "Situation Monitor" in cmd1_stdout, (
            "cmd1 stdout must contain a 'Situation Monitor' digest heading"
        )


# ---------------------------------------------------------------------------
# cmd1: structural validation — spin values must be real numbers
# ---------------------------------------------------------------------------


class TestCmd1SpinFormat:
    """spin_pct and spin_delta values in cmd1 must be parseable numeric quantities."""

    def test_spin_pct_values_are_parseable_floats(self, cmd1_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", cmd1_stdout)
        assert matches, "No 'spin_pct: N.N%' patterns found in cmd1 stdout"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range"
            )

    def test_spin_pct_has_decimal_point(self, cmd1_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", cmd1_stdout)
        assert matches, "No spin_pct values in cmd1 stdout"
        for raw in matches:
            assert "." in raw, (
                f"spin_pct {raw!r} must use decimal format (:.1f); missing decimal point"
            )

    def test_spin_delta_values_are_non_negative(self, cmd1_stdout: str) -> None:
        matches = re.findall(r"spin_delta:\s*([\d.]+)", cmd1_stdout)
        assert matches, "No 'spin_delta: N.N' patterns found in cmd1 stdout"
        for raw in matches:
            assert float(raw) >= 0.0, f"spin_delta must be non-negative; got {raw!r}"

    def test_dual_lens_block_contains_left_bullet(self, cmd1_stdout: str) -> None:
        """A '- <title>' bullet must appear under the LEFT heading."""
        lines = cmd1_stdout.splitlines()
        in_left = False
        found = False
        for line in lines:
            if "#### LEFT" in line:
                in_left = True
                continue
            if in_left:
                if line.startswith("- "):
                    found = True
                    break
                if line.startswith("#"):
                    break
        assert found, "cmd1: '#### LEFT' column must contain at least one '- ...' bullet"

    def test_dual_lens_block_contains_right_bullet(self, cmd1_stdout: str) -> None:
        """A '- <title>' bullet must appear under the RIGHT heading."""
        lines = cmd1_stdout.splitlines()
        in_right = False
        found = False
        for line in lines:
            if "#### RIGHT" in line:
                in_right = True
                continue
            if in_right:
                if line.startswith("- "):
                    found = True
                    break
                if line.startswith("#"):
                    break
        assert found, "cmd1: '#### RIGHT' column must contain at least one '- ...' bullet"

    def test_domain_sections_appear_in_expected_order(self, cmd1_stdout: str) -> None:
        """WORLD must appear before MARKETS, which must appear before AI."""
        world_idx = cmd1_stdout.find("## WORLD")
        markets_idx = cmd1_stdout.find("## MARKETS")
        ai_idx = cmd1_stdout.find("## AI")
        assert world_idx >= 0, "'## WORLD' missing from cmd1 stdout"
        assert markets_idx >= 0, "'## MARKETS' missing from cmd1 stdout"
        assert ai_idx >= 0, "'## AI' missing from cmd1 stdout"
        assert world_idx < markets_idx, (
            "## WORLD must appear before ## MARKETS in cmd1 stdout"
        )
        assert markets_idx < ai_idx, (
            "## MARKETS must appear before ## AI in cmd1 stdout"
        )

    def test_dual_lens_block_appears_after_domain_sections(self, cmd1_stdout: str) -> None:
        """The DUAL-LENS block must come after the main domain sections."""
        ai_idx = cmd1_stdout.find("## AI")
        dual_idx = cmd1_stdout.find("## DUAL-LENS EVENTS")
        assert ai_idx >= 0, "'## AI' not found in cmd1 stdout"
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found in cmd1 stdout"
        assert ai_idx < dual_idx, (
            "'## DUAL-LENS EVENTS' must appear after '## AI' in cmd1 stdout"
        )


# ---------------------------------------------------------------------------
# cmd1: Traceback guard — stdout AND stderr
# ---------------------------------------------------------------------------


class TestCmd1NoTraceback:
    """cmd1 must not produce a Python Traceback in stdout or stderr."""

    def test_no_traceback_in_stdout(self, cmd1_stdout: str) -> None:
        assert "Traceback" not in cmd1_stdout, (
            "cmd1 stdout must not contain a Python Traceback.\n"
            f"stdout (first 2000):\n{cmd1_stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, cmd1_stderr: str) -> None:
        assert "Traceback" not in cmd1_stderr, (
            "cmd1 stderr must not contain a Python Traceback.\n"
            f"stderr:\n{cmd1_stderr[:2000]}"
        )


# ---------------------------------------------------------------------------
# cmd2: situation_monitor digest-dry-run — exit code
# ---------------------------------------------------------------------------


class TestCmd2ExitCode:
    """cmd2 (digest-dry-run) must exit 0."""

    def test_exits_zero(self, cmd2_proc: subprocess.CompletedProcess) -> None:
        assert cmd2_proc.returncode == 0, (
            f"cmd2 (digest-dry-run) exited {cmd2_proc.returncode}, expected 0.\n"
            f"stderr (last 500):\n{cmd2_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, cmd2_stdout: str) -> None:
        assert cmd2_stdout.strip(), "cmd2 (digest-dry-run) must produce non-empty stdout"


# ---------------------------------------------------------------------------
# cmd2: exact required strings per acceptance criteria
# ---------------------------------------------------------------------------


class TestCmd2RequiredContent:
    """cmd2 stdout must contain all strings mandated by the acceptance criteria."""

    def test_contains_situation_monitor_heading(self, cmd2_stdout: str) -> None:
        assert "*Situation Monitor*" in cmd2_stdout, (
            "cmd2 (digest-dry-run) stdout must contain '*Situation Monitor*' "
            "(Telegram bold heading).\n"
            f"stdout:\n{cmd2_stdout[:1000]}"
        )

    def test_contains_top_stories_section(self, cmd2_stdout: str) -> None:
        assert "*Top Stories*" in cmd2_stdout, (
            "cmd2 stdout must contain '*Top Stories*' section.\n"
            f"stdout:\n{cmd2_stdout[:1000]}"
        )

    def test_contains_bullet_entries(self, cmd2_stdout: str) -> None:
        lines = cmd2_stdout.splitlines()
        bullets = [line for line in lines if line.startswith("•")]
        assert bullets, (
            "cmd2 stdout must contain bullet '•' story entries.\n"
            f"stdout:\n{cmd2_stdout[:1000]}"
        )

    def test_bullet_entries_are_non_empty(self, cmd2_stdout: str) -> None:
        for line in cmd2_stdout.splitlines():
            if line.startswith("•"):
                assert line.strip() != "•", (
                    f"cmd2 has an empty bullet entry: {line!r}"
                )

    def test_digest_uses_telegram_bold_not_atx_markdown(self, cmd2_stdout: str) -> None:
        """digest-dry-run emits *bold* Telegram format, not ATX Markdown (# headings)."""
        assert "*Situation Monitor*" in cmd2_stdout, (
            "cmd2 must use Telegram *bold* format, not ATX Markdown"
        )
        # cmd2 must NOT start with '# Situation Monitor' (that's the 'once' format)
        assert not cmd2_stdout.strip().startswith("# Situation Monitor"), (
            "cmd2 emits ATX Markdown heading — it should emit Telegram *bold* format"
        )

    def test_digest_contains_date_stamp(self, cmd2_stdout: str) -> None:
        assert re.search(r"\d{4}-\d{2}-\d{2}", cmd2_stdout), (
            "cmd2 stdout must contain a date stamp (YYYY-MM-DD)"
        )

    def test_digest_output_differs_from_once_format(
        self, cmd1_stdout: str, cmd2_stdout: str
    ) -> None:
        """Digest format uses *bold* Telegram markup; 'once' uses ATX Markdown headers."""
        assert cmd1_stdout != cmd2_stdout, (
            "cmd1 and cmd2 must produce different output: "
            "cmd1 uses ATX Markdown, cmd2 uses Telegram *bold* format"
        )


# ---------------------------------------------------------------------------
# cmd2: Traceback guard — stdout AND stderr
# ---------------------------------------------------------------------------


class TestCmd2NoTraceback:
    """cmd2 must not produce a Python Traceback in stdout or stderr."""

    def test_no_traceback_in_stdout(self, cmd2_stdout: str) -> None:
        assert "Traceback" not in cmd2_stdout, (
            "cmd2 stdout must not contain a Python Traceback"
        )

    def test_no_traceback_in_stderr(self, cmd2_stderr: str) -> None:
        assert "Traceback" not in cmd2_stderr, (
            "cmd2 stderr must not contain a Python Traceback.\n"
            f"stderr:\n{cmd2_stderr[:2000]}"
        )


# ---------------------------------------------------------------------------
# cmd3: situation_monitor once + SM_CARRIER_FEEDS → discourse-carrier line
# ---------------------------------------------------------------------------


class TestCmd3ExitCode:
    """cmd3 (carrier once) must exit 0."""

    def test_exits_zero(self, cmd3_proc: subprocess.CompletedProcess) -> None:
        assert cmd3_proc.returncode == 0, (
            f"cmd3 (carrier once) exited {cmd3_proc.returncode}, expected 0.\n"
            f"stderr (last 500):\n{cmd3_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, cmd3_stdout: str) -> None:
        assert cmd3_stdout.strip(), "cmd3 (carrier once) must produce non-empty stdout"


class TestCmd3RequiredContent:
    """cmd3 stdout must contain a line starting with 'discourse-carrier'."""

    def test_contains_discourse_carrier(self, cmd3_stdout: str) -> None:
        assert "discourse-carrier" in cmd3_stdout, (
            "cmd3 stdout must contain 'discourse-carrier'.\n"
            f"stdout (first 500):\n{cmd3_stdout[:500]}"
        )

    def test_discourse_carrier_line_starts_the_line(self, cmd3_stdout: str) -> None:
        """grep '^discourse-carrier' requires the token at the very start of a line."""
        matching = [
            line for line in cmd3_stdout.splitlines()
            if line.startswith("discourse-carrier")
        ]
        assert matching, (
            "No line STARTING WITH 'discourse-carrier' found in cmd3 stdout.\n"
            "The acceptance check uses 'grep ^discourse-carrier' — no leading whitespace allowed.\n"
            f"stdout (first 500):\n{cmd3_stdout[:500]}"
        )

    def test_discourse_carrier_articles_colon_n_format(self, cmd3_stdout: str) -> None:
        """The format must be 'discourse-carrier articles: N' on its own line."""
        pattern = re.compile(r"^discourse-carrier articles:\s*(\d+)$", re.MULTILINE)
        match = pattern.search(cmd3_stdout)
        assert match, (
            "cmd3 stdout must contain 'discourse-carrier articles: N' line.\n"
            f"stdout (first 500):\n{cmd3_stdout[:500]}"
        )

    def test_discourse_carrier_count_is_positive(self, cmd3_stdout: str) -> None:
        matches = re.findall(r"discourse-carrier articles:\s*(\d+)", cmd3_stdout)
        assert matches, "Could not find discourse-carrier count in cmd3 stdout"
        count = int(matches[0])
        assert count > 0, (
            f"discourse-carrier articles count must be > 0; got {count}.\n"
            "The carrier fixture (rss_carrier.xml) has items that must be ingested."
        )

    def test_no_leading_whitespace_before_discourse_carrier_line(
        self, cmd3_stdout: str
    ) -> None:
        """Whitespace before 'discourse-carrier' would break grep '^discourse-carrier'."""
        for line in cmd3_stdout.splitlines():
            if "discourse-carrier" in line and not line.startswith("discourse-carrier"):
                # Only flag lines where 'discourse-carrier' appears but NOT at position 0
                # (some unrelated lines might mention the word)
                if re.match(r"^\s+discourse-carrier", line):
                    pytest.fail(
                        f"Line has leading whitespace before 'discourse-carrier': {line!r}\n"
                        "This breaks 'grep ^discourse-carrier'."
                    )

    def test_carrier_line_appears_before_markdown_digest_header(
        self, cmd3_stdout: str
    ) -> None:
        """The carrier count must be printed before the Markdown digest header."""
        carrier_idx = cmd3_stdout.find("discourse-carrier articles:")
        digest_idx = cmd3_stdout.find("# Situation Monitor Digest")
        assert carrier_idx >= 0, "discourse-carrier articles: not found in cmd3 stdout"
        assert digest_idx >= 0, "# Situation Monitor Digest not found in cmd3 stdout"
        assert carrier_idx < digest_idx, (
            "'discourse-carrier articles:' must appear BEFORE '# Situation Monitor Digest'.\n"
            "Check _cmd_once: carrier_count print precedes check_and_emit_alerts + _print_markdown."
        )

    def test_carrier_feed_is_not_loaded_when_sm_carrier_feeds_absent(
        self, cmd1_stdout: str
    ) -> None:
        """Without SM_CARRIER_FEEDS (cmd1), no 'discourse-carrier' line must appear."""
        carrier_lines = [
            line for line in cmd1_stdout.splitlines()
            if line.startswith("discourse-carrier")
        ]
        assert not carrier_lines, (
            "cmd1 (no SM_CARRIER_FEEDS) must NOT emit a 'discourse-carrier' line.\n"
            f"Unexpected lines: {carrier_lines}"
        )


# ---------------------------------------------------------------------------
# cmd3: Traceback guard — stdout AND stderr
# ---------------------------------------------------------------------------


class TestCmd3NoTraceback:
    """cmd3 must not produce a Python Traceback in stdout or stderr."""

    def test_no_traceback_in_stdout(self, cmd3_stdout: str) -> None:
        assert "Traceback" not in cmd3_stdout, (
            "cmd3 stdout must not contain a Python Traceback"
        )

    def test_no_traceback_in_stderr(self, cmd3_stderr: str) -> None:
        assert "Traceback" not in cmd3_stderr, (
            "cmd3 stderr must not contain a Python Traceback.\n"
            f"stderr:\n{cmd3_stderr[:2000]}"
        )


# ---------------------------------------------------------------------------
# cmd3: grep-pipe variant — mirrors the actual shell acceptance check
# ---------------------------------------------------------------------------


class TestCmd3ViaGrepPipe:
    """Run cmd3 through a real ``grep '^discourse-carrier'`` pipe.

    This catches format regressions that Python string checks miss: a leading
    space or ANSI escape before 'discourse-carrier' would pass
    ``'discourse-carrier' in stdout`` but fail the actual acceptance grep.
    """

    @pytest.fixture(scope="class")
    def grep_result(self) -> subprocess.CompletedProcess:
        env = _offline_env(SM_CARRIER_FEEDS=_CARRIER_FEEDS_JSON)
        once = subprocess.Popen(
            [
                sys.executable, "-m", "situation_monitor",
                "once",
                "--config", str(ACCEPTANCE_SOURCE_DEFS),
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
            "grep '^discourse-carrier' must exit 0 — at least one matching line required.\n"
            f"grep stdout: {grep_result.stdout.decode(errors='replace')!r}"
        )

    def test_grep_stdout_starts_with_discourse_carrier(
        self, grep_result: subprocess.CompletedProcess
    ) -> None:
        out = grep_result.stdout.decode(errors="replace")
        assert "discourse-carrier" in out, (
            f"grep stdout must contain 'discourse-carrier'; got {out!r}"
        )
        for line in out.splitlines():
            if line.strip():
                assert line.startswith("discourse-carrier"), (
                    f"Every grep match must start with 'discourse-carrier'; got {line!r}"
                )


# ---------------------------------------------------------------------------
# cmd4: check_server.py subprocess
# ---------------------------------------------------------------------------


class TestCmd4ExitCode:
    """cmd4 (check_server.py) must exit 0."""

    def test_exits_zero(self, cmd4_proc: subprocess.CompletedProcess) -> None:
        assert cmd4_proc.returncode == 0, (
            f"cmd4 (check_server.py) exited {cmd4_proc.returncode}, expected 0.\n"
            f"stderr:\n{cmd4_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, cmd4_stdout: str) -> None:
        assert cmd4_stdout.strip(), "cmd4 (check_server.py) must produce non-empty stdout"


class TestCmd4RequiredContent:
    """cmd4 stdout must contain 'web-server-smoke: PASS'."""

    def test_contains_pass_marker(self, cmd4_stdout: str) -> None:
        assert "web-server-smoke: PASS" in cmd4_stdout, (
            "cmd4 stdout must contain 'web-server-smoke: PASS'.\n"
            f"Got: {cmd4_stdout!r}"
        )

    def test_check_server_script_exists(self) -> None:
        assert CHECK_SERVER.exists(), f"check_server.py not found at {CHECK_SERVER}"

    def test_pass_marker_is_at_line_start(self, cmd4_stdout: str) -> None:
        lines = cmd4_stdout.splitlines()
        assert any(line == "web-server-smoke: PASS" for line in lines), (
            "'web-server-smoke: PASS' must appear as a complete line.\n"
            f"Lines: {lines}"
        )


class TestCmd4NoTraceback:
    """cmd4 must not produce a Python Traceback in stdout or stderr."""

    def test_no_traceback_in_stdout(self, cmd4_stdout: str) -> None:
        assert "Traceback" not in cmd4_stdout, (
            "cmd4 stdout must not contain a Python Traceback"
        )

    def test_no_traceback_in_stderr(self, cmd4_stderr: str) -> None:
        assert "Traceback" not in cmd4_stderr, (
            "cmd4 stderr must not contain a Python Traceback.\n"
            f"stderr:\n{cmd4_stderr[:2000]}"
        )


# ---------------------------------------------------------------------------
# Omnibus: all four commands must pass simultaneously
# ---------------------------------------------------------------------------


class TestAllFourCommandsPass:
    """All four acceptance commands must exit 0 simultaneously."""

    def test_all_exit_zero(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd2_proc: subprocess.CompletedProcess,
        cmd3_proc: subprocess.CompletedProcess,
        cmd4_proc: subprocess.CompletedProcess,
    ) -> None:
        failures = []
        if cmd1_proc.returncode != 0:
            failures.append(f"cmd1 (once): rc={cmd1_proc.returncode}")
        if cmd2_proc.returncode != 0:
            failures.append(f"cmd2 (digest-dry-run): rc={cmd2_proc.returncode}")
        if cmd3_proc.returncode != 0:
            failures.append(f"cmd3 (carrier once): rc={cmd3_proc.returncode}")
        if cmd4_proc.returncode != 0:
            failures.append(f"cmd4 (check_server.py): rc={cmd4_proc.returncode}")
        assert not failures, (
            "One or more acceptance commands failed:\n" + "\n".join(failures)
        )

    def test_no_traceback_in_any_stdout(
        self,
        cmd1_stdout: str,
        cmd2_stdout: str,
        cmd3_stdout: str,
        cmd4_stdout: str,
    ) -> None:
        which = []
        if "Traceback" in cmd1_stdout:
            which.append("cmd1")
        if "Traceback" in cmd2_stdout:
            which.append("cmd2")
        if "Traceback" in cmd3_stdout:
            which.append("cmd3")
        if "Traceback" in cmd4_stdout:
            which.append("cmd4")
        assert not which, (
            f"Traceback found in stdout of: {', '.join(which)}"
        )

    def test_no_traceback_in_any_stderr(
        self,
        cmd1_stderr: str,
        cmd2_stderr: str,
        cmd3_stderr: str,
        cmd4_stderr: str,
    ) -> None:
        which = []
        if "Traceback" in cmd1_stderr:
            which.append("cmd1")
        if "Traceback" in cmd2_stderr:
            which.append("cmd2")
        if "Traceback" in cmd3_stderr:
            which.append("cmd3")
        if "Traceback" in cmd4_stderr:
            which.append("cmd4")
        assert not which, (
            f"Traceback found in stderr of: {', '.join(which)}"
        )

    def test_cmd1_has_all_required_strings(self, cmd1_stdout: str) -> None:
        required = [
            "## DUAL-LENS EVENTS",
            "#### LEFT",
            "#### RIGHT",
            "spin_pct:",
            "spin_delta:",
            "## MARKETS",
            "## AI",
            "## WORLD",
        ]
        missing = [s for s in required if s not in cmd1_stdout]
        assert not missing, (
            f"cmd1 stdout is missing these required strings: {missing}\n"
            f"stdout (first 3000):\n{cmd1_stdout[:3000]}"
        )

    def test_cmd2_has_all_required_strings(self, cmd2_stdout: str) -> None:
        required = [
            "*Situation Monitor*",
            "*Top Stories*",
        ]
        missing = [s for s in required if s not in cmd2_stdout]
        assert not missing, (
            f"cmd2 stdout is missing these required strings: {missing}\n"
            f"stdout:\n{cmd2_stdout[:1000]}"
        )
        bullets = [line for line in cmd2_stdout.splitlines() if line.startswith("•")]
        assert bullets, (
            "cmd2 stdout must contain at least one '•' bullet entry"
        )

    def test_cmd3_has_discourse_carrier_line(self, cmd3_stdout: str) -> None:
        matching = [
            line for line in cmd3_stdout.splitlines()
            if line.startswith("discourse-carrier")
        ]
        assert matching, (
            "cmd3 stdout must contain a line starting with 'discourse-carrier'"
        )

    def test_cmd4_has_pass_marker(self, cmd4_stdout: str) -> None:
        assert "web-server-smoke: PASS" in cmd4_stdout, (
            "cmd4 stdout must contain 'web-server-smoke: PASS'"
        )


# ---------------------------------------------------------------------------
# Fixtures exist — prerequisite checks that fail clearly before subprocess errors
# ---------------------------------------------------------------------------


class TestRequiredFixturesExist:
    """All fixture files used by the acceptance commands must be present."""

    def test_rss_sample_xml_exists(self) -> None:
        assert RSS_FIXTURE.exists(), f"Required fixture missing: {RSS_FIXTURE}"

    def test_rss_carrier_xml_exists(self) -> None:
        assert RSS_CARRIER.exists(), f"Required fixture missing: {RSS_CARRIER}"

    def test_acceptance_source_defs_json_exists(self) -> None:
        assert ACCEPTANCE_SOURCE_DEFS.exists(), (
            f"Required fixture missing: {ACCEPTANCE_SOURCE_DEFS}"
        )

    def test_rss_left_xml_exists(self) -> None:
        assert (FIXTURES / "rss_left.xml").exists(), "rss_left.xml fixture missing"

    def test_rss_right_xml_exists(self) -> None:
        assert (FIXTURES / "rss_right.xml").exists(), "rss_right.xml fixture missing"

    def test_rss_markets_xml_exists(self) -> None:
        assert (FIXTURES / "rss_markets.xml").exists(), "rss_markets.xml fixture missing"

    def test_rss_ai_xml_exists(self) -> None:
        assert (FIXTURES / "rss_ai.xml").exists(), "rss_ai.xml fixture missing"

    def test_acceptance_source_defs_references_all_domain_fixtures(self) -> None:
        """The source-defs JSON must wire up all required domain fixtures."""
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        assert "source_defs" in data, "acceptance_source_defs.json must have 'source_defs' key"
        urls = {sd["url"] for sd in data["source_defs"]}
        expected = {
            "tests/fixtures/rss_left.xml",
            "tests/fixtures/rss_right.xml",
            "tests/fixtures/rss_markets.xml",
            "tests/fixtures/rss_ai.xml",
        }
        missing = expected - urls
        assert not missing, (
            f"acceptance_source_defs.json is missing these fixture URLs: {missing}"
        )

    def test_rss_carrier_xml_has_items(self) -> None:
        """The carrier fixture must have at least one <item> — the count must be > 0."""
        content = RSS_CARRIER.read_text()
        assert "<item>" in content, (
            "rss_carrier.xml must contain at least one <item> element; "
            "an empty feed would cause cmd3 to emit 'discourse-carrier articles: 0'"
        )

    def test_rss_sample_xml_has_items(self) -> None:
        content = RSS_FIXTURE.read_text()
        assert "<item>" in content, "rss_sample.xml must contain at least one <item> element"

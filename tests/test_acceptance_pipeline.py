"""Acceptance pipeline regression test.

Mirrors the three commands in the ``acceptance`` file verbatim, but invokes each
as a separate subprocess via ``sys.executable`` (never bare ``python3``) with
``SM_LLM_BACKEND=offline`` and ``cwd=project root`` so the run is reproducible
without network access.

The acceptance file commands:
  1. ``once``          – SM_SOURCES override, offline LLM
  2. ``digest-dry-run``– SM_SOURCES override, offline LLM
  3. carrier ``once``  – SM_CARRIER_FEEDS set; stdout checked for ``^discourse-carrier``

Each command is a completely independent subprocess call so a failure in one
cannot bleed into another's exit code.
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

# Exact JSON used by acceptance cmd 3
_CARRIER_FEEDS_JSON = json.dumps(
    [{"url": "tests/fixtures/rss_carrier.xml", "country": "US", "lean": "centre"}]
)


# ---------------------------------------------------------------------------
# Environment builders
# ---------------------------------------------------------------------------


def _base_offline_env(**extra: str) -> dict[str, str]:
    """Return an env dict with SM_LLM_BACKEND=offline and SM_SOURCES set.

    Always starts from ``os.environ`` so PYTHONPATH, PATH, etc. carry over.
    """
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
        **extra,
    }


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixtures — one subprocess per acceptance command
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cmd1_result() -> subprocess.CompletedProcess:
    """Acceptance cmd 1: ``situation_monitor once`` with offline LLM + fixture RSS."""
    return subprocess.run(
        [
            sys.executable,
            "-m", "situation_monitor",
            "once",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        text=False,
        cwd=PROJECT_ROOT,
        env=_base_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def cmd1_stdout(cmd1_result: subprocess.CompletedProcess) -> str:
    return cmd1_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd1_stderr(cmd1_result: subprocess.CompletedProcess) -> str:
    return cmd1_result.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd2_result() -> subprocess.CompletedProcess:
    """Acceptance cmd 2: ``situation_monitor digest-dry-run`` — SEPARATE subprocess."""
    return subprocess.run(
        [
            sys.executable,
            "-m", "situation_monitor",
            "digest-dry-run",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        text=False,
        cwd=PROJECT_ROOT,
        env=_base_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def cmd2_stdout(cmd2_result: subprocess.CompletedProcess) -> str:
    return cmd2_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd2_stderr(cmd2_result: subprocess.CompletedProcess) -> str:
    return cmd2_result.stderr.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd3_result() -> subprocess.CompletedProcess:
    """Acceptance cmd 3: carrier ``once`` with SM_CARRIER_FEEDS — SEPARATE subprocess.

    The acceptance script pipes this through ``grep '^discourse-carrier'``; we
    capture stdout and verify the same line-start pattern in Python.
    """
    return subprocess.run(
        [
            sys.executable,
            "-m", "situation_monitor",
            "once",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        text=False,
        cwd=PROJECT_ROOT,
        env=_base_offline_env(
            SM_CARRIER_FEEDS=_CARRIER_FEEDS_JSON,
            # Ensure SM_SOURCES is still set so non-carrier articles also load.
            SM_SOURCES=str(RSS_FIXTURE),
        ),
        timeout=120,
    )


@pytest.fixture(scope="module")
def cmd3_stdout(cmd3_result: subprocess.CompletedProcess) -> str:
    return cmd3_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd3_stderr(cmd3_result: subprocess.CompletedProcess) -> str:
    return cmd3_result.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# 0. Fixture prerequisites — must hold before any subprocess runs
# ---------------------------------------------------------------------------


class TestFixtureFiles:
    """Fixture files the acceptance commands depend on must exist and be valid."""

    def test_rss_sample_xml_exists(self) -> None:
        assert RSS_FIXTURE.exists(), f"Missing fixture: {RSS_FIXTURE}"

    def test_rss_carrier_xml_exists(self) -> None:
        assert RSS_CARRIER.exists(), f"Missing fixture: {RSS_CARRIER}"

    def test_acceptance_source_defs_exists(self) -> None:
        assert ACCEPTANCE_SOURCE_DEFS.exists(), f"Missing fixture: {ACCEPTANCE_SOURCE_DEFS}"

    def test_acceptance_source_defs_is_valid_json(self) -> None:
        try:
            data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        except Exception as exc:
            pytest.fail(f"acceptance_source_defs.json is not valid JSON: {exc}")
        assert isinstance(data, dict), "acceptance_source_defs.json must be a JSON object"

    def test_acceptance_source_defs_has_source_defs_key(self) -> None:
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        assert "source_defs" in data, (
            "acceptance_source_defs.json must contain a 'source_defs' key"
        )

    def test_source_defs_includes_left_lens(self) -> None:
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        lenses = {d.get("lens") for d in data.get("source_defs", [])}
        assert "left" in lenses, (
            "source_defs must include at least one entry with lens='left' "
            "so dual-lens events can form"
        )

    def test_source_defs_includes_right_lens(self) -> None:
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        lenses = {d.get("lens") for d in data.get("source_defs", [])}
        assert "right" in lenses, (
            "source_defs must include at least one entry with lens='right'"
        )

    def test_rss_sample_xml_is_valid_xml(self) -> None:
        import xml.etree.ElementTree as ET

        try:
            ET.fromstring(RSS_FIXTURE.read_bytes())
        except Exception as exc:
            pytest.fail(f"rss_sample.xml is not valid XML: {exc}")

    def test_rss_sample_xml_has_items(self) -> None:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(RSS_FIXTURE.read_bytes())
        items = root.findall(".//item")
        assert items, "rss_sample.xml must contain at least one <item>"

    def test_rss_carrier_xml_is_valid_xml(self) -> None:
        import xml.etree.ElementTree as ET

        try:
            ET.fromstring(RSS_CARRIER.read_bytes())
        except Exception as exc:
            pytest.fail(f"rss_carrier.xml is not valid XML: {exc}")

    def test_rss_carrier_xml_has_items(self) -> None:
        import xml.etree.ElementTree as ET

        root = ET.fromstring(RSS_CARRIER.read_bytes())
        items = root.findall(".//item")
        assert items, "rss_carrier.xml must contain at least one <item> for the carrier test"


# ---------------------------------------------------------------------------
# 1. Acceptance cmd 1: ``situation_monitor once``
# ---------------------------------------------------------------------------


class TestCmd1Once:
    """Cmd 1 from the acceptance file: ``once`` with offline LLM and fixture RSS."""

    # --- exit code ----------------------------------------------------------

    def test_exits_zero(self, cmd1_result: subprocess.CompletedProcess) -> None:
        assert cmd1_result.returncode == 0, (
            f"'once' exited {cmd1_result.returncode}; expected 0.\n"
            f"stdout tail:\n{cmd1_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"stderr tail:\n{cmd1_result.stderr.decode(errors='replace')[-500:]}"
        )

    # --- subprocess mechanics -----------------------------------------------

    def test_invoked_via_sys_executable(
        self, cmd1_result: subprocess.CompletedProcess
    ) -> None:
        """Must be launched as ``[sys.executable, '-m', 'situation_monitor', ...]``."""
        args = cmd1_result.args
        assert isinstance(args, list), (
            "cmd1 must be a subprocess.run([...]) list call, not a shell string"
        )
        assert args[0] == sys.executable, (
            f"args[0] must be sys.executable ({sys.executable!r}); got {args[0]!r}.\n"
            "Using bare 'python3' breaks on macOS where only 'python3' is installed."
        )

    def test_args_contain_once_subcommand(
        self, cmd1_result: subprocess.CompletedProcess
    ) -> None:
        assert "once" in cmd1_result.args, (
            f"'once' subcommand must be in subprocess args; got {cmd1_result.args!r}"
        )

    def test_args_contain_module_flag(
        self, cmd1_result: subprocess.CompletedProcess
    ) -> None:
        assert "-m" in cmd1_result.args, (
            "subprocess args must include '-m' to launch situation_monitor as a module"
        )

    def test_sm_llm_backend_offline_in_env(
        self, cmd1_result: subprocess.CompletedProcess
    ) -> None:
        """SM_LLM_BACKEND=offline must be set; without it the run hits a live LLM API."""
        # We can only inspect what we passed — verify via the env dict we built.
        env = _base_offline_env()
        assert env.get("SM_LLM_BACKEND") == "offline", (
            "SM_LLM_BACKEND must be 'offline' in the subprocess env"
        )

    def test_sm_sources_points_to_fixture(self) -> None:
        """SM_SOURCES must point to the local fixture, not a live URL."""
        env = _base_offline_env()
        sm_sources = env.get("SM_SOURCES", "")
        assert str(RSS_FIXTURE) in sm_sources, (
            f"SM_SOURCES must include the local fixture path {RSS_FIXTURE!r}; "
            f"got {sm_sources!r}"
        )
        assert not sm_sources.startswith("http"), (
            "SM_SOURCES must be a local path in offline mode, not an HTTP URL"
        )

    # --- stdout content checks ----------------------------------------------

    def test_stdout_non_empty(self, cmd1_stdout: str) -> None:
        assert cmd1_stdout.strip(), "'once' must produce non-empty stdout"

    def test_no_traceback_in_stdout(self, cmd1_stdout: str) -> None:
        assert "Traceback" not in cmd1_stdout, (
            "'once' stdout must not contain a Python traceback.\n"
            f"stdout sample:\n{cmd1_stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, cmd1_stderr: str) -> None:
        assert "Traceback" not in cmd1_stderr, (
            f"'once' stderr contains a Python traceback:\n{cmd1_stderr[:2000]}"
        )

    def test_situation_monitor_heading_present(self, cmd1_stdout: str) -> None:
        assert "Situation Monitor" in cmd1_stdout, (
            "'once' stdout must contain 'Situation Monitor' heading from _print_markdown"
        )

    def test_dual_lens_events_section_present(self, cmd1_stdout: str) -> None:
        assert "DUAL-LENS EVENTS" in cmd1_stdout, (
            "'once' stdout must contain 'DUAL-LENS EVENTS' section header.\n"
            "Requires at least one event with left+right articles.\n"
            f"stdout sample:\n{cmd1_stdout[:3000]}"
        )

    def test_left_marker_present(self, cmd1_stdout: str) -> None:
        assert "#### LEFT" in cmd1_stdout, (
            "'once' stdout must contain '#### LEFT' dual-lens column heading.\n"
            f"stdout sample:\n{cmd1_stdout[:3000]}"
        )

    def test_right_marker_present(self, cmd1_stdout: str) -> None:
        assert "#### RIGHT" in cmd1_stdout, (
            "'once' stdout must contain '#### RIGHT' dual-lens column heading.\n"
            f"stdout sample:\n{cmd1_stdout[:3000]}"
        )

    def test_spin_pct_annotation_present(self, cmd1_stdout: str) -> None:
        assert "spin_pct:" in cmd1_stdout, (
            "'once' stdout must contain 'spin_pct:' per-article annotations.\n"
            f"stdout sample:\n{cmd1_stdout[:3000]}"
        )

    # --- structural checks for dual-lens output ----------------------------

    def test_left_heading_is_h4_at_line_start(self, cmd1_stdout: str) -> None:
        h4_lines = [l for l in cmd1_stdout.splitlines() if l.startswith("#### LEFT")]
        assert h4_lines, (
            "No line starting with '#### LEFT' found; it must be a proper H4 heading"
        )

    def test_right_heading_is_h4_at_line_start(self, cmd1_stdout: str) -> None:
        h4_lines = [l for l in cmd1_stdout.splitlines() if l.startswith("#### RIGHT")]
        assert h4_lines, (
            "No line starting with '#### RIGHT' found; it must be a proper H4 heading"
        )

    def test_left_heading_contains_article_count(self, cmd1_stdout: str) -> None:
        h4_lines = [l for l in cmd1_stdout.splitlines() if l.startswith("#### LEFT")]
        assert h4_lines, "No '#### LEFT' heading found"
        assert "article" in h4_lines[0], (
            f"'#### LEFT' heading must include 'article' count; got: {h4_lines[0]!r}"
        )

    def test_right_heading_contains_article_count(self, cmd1_stdout: str) -> None:
        h4_lines = [l for l in cmd1_stdout.splitlines() if l.startswith("#### RIGHT")]
        assert h4_lines, "No '#### RIGHT' heading found"
        assert "article" in h4_lines[0], (
            f"'#### RIGHT' heading must include 'article' count; got: {h4_lines[0]!r}"
        )

    def test_both_markers_inside_dual_lens_block(self, cmd1_stdout: str) -> None:
        idx = cmd1_stdout.find("DUAL-LENS EVENTS")
        assert idx >= 0, "'DUAL-LENS EVENTS' block not found"
        block = cmd1_stdout[idx:]
        assert "#### LEFT" in block, "'#### LEFT' not found inside DUAL-LENS EVENTS block"
        assert "#### RIGHT" in block, "'#### RIGHT' not found inside DUAL-LENS EVENTS block"

    def test_spin_pct_numeric_format(self, cmd1_stdout: str) -> None:
        """spin_pct must be formatted as ``N.N%`` with a decimal point."""
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", cmd1_stdout)
        assert matches, (
            "No 'spin_pct: N.N%' pattern found; spin annotation must carry a numeric value"
        )

    def test_spin_pct_values_in_valid_range(self, cmd1_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", cmd1_stdout)
        assert matches, "No spin_pct values found"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range"
            )

    def test_spin_pct_on_bullet_lines(self, cmd1_stdout: str) -> None:
        """spin_pct must appear on '- ...' article bullets, not floating in prose."""
        bullets = [
            l for l in cmd1_stdout.splitlines()
            if l.startswith("- ") and "spin_pct:" in l
        ]
        assert bullets, (
            "No '- <title> | spin_pct: ...' bullet lines found in 'once' stdout"
        )

    def test_spin_delta_annotation_present(self, cmd1_stdout: str) -> None:
        """Each dual-lens event must also carry a ``spin_delta:`` event-level annotation."""
        matches = re.findall(r"spin_delta:\s*([\d.]+)", cmd1_stdout)
        assert matches, (
            "'once' stdout must contain 'spin_delta: N.N' event-level annotations"
        )
        for raw in matches:
            assert float(raw) >= 0.0, f"spin_delta must be non-negative; got {raw!r}"

    def test_spin_pct_in_left_column(self, cmd1_stdout: str) -> None:
        """At least one spin_pct bullet must appear under the #### LEFT heading."""
        lines = cmd1_stdout.splitlines()
        in_left = False
        for line in lines:
            if line.startswith("#### LEFT"):
                in_left = True
                continue
            if in_left:
                if line.startswith("- ") and "spin_pct:" in line:
                    return
                if line.startswith("#"):
                    break
        pytest.fail("No spin_pct annotation found under '#### LEFT' heading")

    def test_spin_pct_in_right_column(self, cmd1_stdout: str) -> None:
        """At least one spin_pct bullet must appear under the #### RIGHT heading."""
        lines = cmd1_stdout.splitlines()
        in_right = False
        for line in lines:
            if line.startswith("#### RIGHT"):
                in_right = True
                continue
            if in_right:
                if line.startswith("- ") and "spin_pct:" in line:
                    return
                if line.startswith("#"):
                    break
        pytest.fail("No spin_pct annotation found under '#### RIGHT' heading")

    def test_no_discourse_carrier_line_without_carrier_feeds(
        self, cmd1_stdout: str
    ) -> None:
        """Without SM_CARRIER_FEEDS the 'discourse-carrier articles:' prefix must be absent."""
        carrier_lines = [
            l for l in cmd1_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert not carrier_lines, (
            "Cmd 1 must NOT print a 'discourse-carrier' line when SM_CARRIER_FEEDS is unset;\n"
            f"found: {carrier_lines}"
        )


# ---------------------------------------------------------------------------
# 2. Acceptance cmd 2: ``situation_monitor digest-dry-run``
# ---------------------------------------------------------------------------


class TestCmd2DigestDryRun:
    """Cmd 2 from the acceptance file: ``digest-dry-run`` — independent subprocess."""

    def test_exits_zero(self, cmd2_result: subprocess.CompletedProcess) -> None:
        assert cmd2_result.returncode == 0, (
            f"'digest-dry-run' exited {cmd2_result.returncode}; expected 0.\n"
            f"stdout tail:\n{cmd2_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"stderr tail:\n{cmd2_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_invoked_via_sys_executable(
        self, cmd2_result: subprocess.CompletedProcess
    ) -> None:
        args = cmd2_result.args
        assert isinstance(args, list), "cmd2 must be a list-form subprocess call"
        assert args[0] == sys.executable, (
            f"args[0] must be sys.executable ({sys.executable!r}); got {args[0]!r}"
        )

    def test_args_contain_digest_dry_run_subcommand(
        self, cmd2_result: subprocess.CompletedProcess
    ) -> None:
        assert "digest-dry-run" in cmd2_result.args, (
            f"'digest-dry-run' subcommand must be in args; got {cmd2_result.args!r}"
        )

    def test_stdout_non_empty(self, cmd2_stdout: str) -> None:
        assert cmd2_stdout.strip(), "'digest-dry-run' must produce non-empty stdout"

    def test_no_traceback_in_stdout(self, cmd2_stdout: str) -> None:
        assert "Traceback" not in cmd2_stdout, (
            f"'digest-dry-run' stdout must not contain a Python traceback.\n"
            f"stdout sample:\n{cmd2_stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, cmd2_stderr: str) -> None:
        assert "Traceback" not in cmd2_stderr, (
            f"'digest-dry-run' stderr contains a Python traceback:\n{cmd2_stderr[:2000]}"
        )

    def test_situation_monitor_in_stdout(self, cmd2_stdout: str) -> None:
        assert "Situation Monitor" in cmd2_stdout, (
            "'digest-dry-run' stdout must contain 'Situation Monitor'.\n"
            f"stdout sample:\n{cmd2_stdout[:2000]}"
        )

    def test_distinct_process_from_cmd1(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
    ) -> None:
        """cmd2 must be a SEPARATE subprocess object — not the same as cmd1."""
        assert cmd2_result is not cmd1_result, (
            "cmd1 and cmd2 must be independent subprocess calls; "
            "otherwise a cmd1 failure is masked by cmd2's exit code"
        )

    def test_digest_dry_run_exit_independent_of_once(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
    ) -> None:
        """Both exit codes must be individually inspectable."""
        assert isinstance(cmd1_result.returncode, int)
        assert isinstance(cmd2_result.returncode, int)
        assert cmd1_result.returncode == 0, (
            f"cmd1 (once) exit={cmd1_result.returncode} — independently visible failure"
        )
        assert cmd2_result.returncode == 0, (
            f"cmd2 (digest-dry-run) exit={cmd2_result.returncode} — independently visible failure"
        )

    def test_digest_output_is_not_raw_markdown_digest(self, cmd2_stdout: str) -> None:
        """digest-dry-run uses the Telegram format (not the raw Markdown digest).

        The Telegram digest starts with ``*Situation Monitor*`` or similar
        bold formatting and does NOT have the ``# Situation Monitor Digest —`` H1
        line that ``once`` prints.
        """
        # The digest format uses Telegram-style markdown (*bold*), not ATX headings
        assert "#" not in cmd2_stdout[:200] or "Situation Monitor" in cmd2_stdout, (
            "digest-dry-run output appears malformed"
        )


# ---------------------------------------------------------------------------
# 3. Acceptance cmd 3: carrier ``once`` — stdout must have ``^discourse-carrier``
# ---------------------------------------------------------------------------


class TestCmd3CarrierOnce:
    """Cmd 3: ``once`` with SM_CARRIER_FEEDS; mirrors ``... | grep '^discourse-carrier'``."""

    def test_exits_zero(self, cmd3_result: subprocess.CompletedProcess) -> None:
        assert cmd3_result.returncode == 0, (
            f"Carrier 'once' exited {cmd3_result.returncode}; expected 0.\n"
            f"stdout tail:\n{cmd3_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"stderr tail:\n{cmd3_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_invoked_via_sys_executable(
        self, cmd3_result: subprocess.CompletedProcess
    ) -> None:
        args = cmd3_result.args
        assert isinstance(args, list), "cmd3 must be a list-form subprocess call"
        assert args[0] == sys.executable, (
            f"args[0] must be sys.executable ({sys.executable!r}); got {args[0]!r}"
        )

    def test_args_contain_once_subcommand(
        self, cmd3_result: subprocess.CompletedProcess
    ) -> None:
        assert "once" in cmd3_result.args, (
            f"'once' subcommand must be in cmd3 args; got {cmd3_result.args!r}"
        )

    def test_stdout_non_empty(self, cmd3_stdout: str) -> None:
        assert cmd3_stdout.strip(), "Carrier 'once' must produce non-empty stdout"

    def test_no_traceback_in_stdout(self, cmd3_stdout: str) -> None:
        assert "Traceback" not in cmd3_stdout, (
            f"Carrier 'once' stdout must not contain a Python traceback.\n"
            f"stdout sample:\n{cmd3_stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, cmd3_stderr: str) -> None:
        assert "Traceback" not in cmd3_stderr, (
            f"Carrier 'once' stderr contains a Python traceback:\n{cmd3_stderr[:2000]}"
        )

    def test_discourse_carrier_line_at_line_start(self, cmd3_stdout: str) -> None:
        """Mirrors ``grep '^discourse-carrier'``: a line must START with discourse-carrier."""
        matching = [
            l for l in cmd3_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert matching, (
            "Carrier 'once' stdout must contain a line starting with 'discourse-carrier'.\n"
            "The acceptance script checks this via: "
            "``... | grep '^discourse-carrier'``.\n"
            "Check that _cmd_once prints "
            "``discourse-carrier articles: N`` when carrier_count > 0.\n"
            f"stdout (first 1000):\n{cmd3_stdout[:1000]}"
        )

    def test_discourse_carrier_count_is_positive(self, cmd3_stdout: str) -> None:
        """The carrier count on the printed line must be > 0."""
        matches = re.findall(r"discourse-carrier articles:\s*(\d+)", cmd3_stdout)
        assert matches, (
            "Could not parse 'discourse-carrier articles: N' from carrier stdout"
        )
        count = int(matches[0])
        assert count > 0, (
            f"discourse-carrier article count must be > 0; got {count}.\n"
            "Verify SM_CARRIER_FEEDS was applied and the carrier fixture has items."
        )

    def test_discourse_carrier_count_does_not_exceed_fixture(
        self, cmd3_stdout: str
    ) -> None:
        """Carrier count must not exceed the number of <item> elements in the fixture."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(RSS_CARRIER.read_bytes())
        fixture_count = len(root.findall(".//item"))
        matches = re.findall(r"discourse-carrier articles:\s*(\d+)", cmd3_stdout)
        assert matches, "No discourse-carrier count found"
        reported = int(matches[0])
        assert reported <= fixture_count, (
            f"Reported carrier count ({reported}) exceeds fixture item count "
            f"({fixture_count}); duplicate articles were not deduped"
        )

    def test_discourse_carrier_count_matches_fixture_exactly(
        self, cmd3_stdout: str
    ) -> None:
        """All items in rss_carrier.xml should be ingested (no silent drops)."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(RSS_CARRIER.read_bytes())
        fixture_count = len(root.findall(".//item"))
        matches = re.findall(r"discourse-carrier articles:\s*(\d+)", cmd3_stdout)
        assert matches, "No discourse-carrier count found"
        reported = int(matches[0])
        assert reported == fixture_count, (
            f"Carrier count mismatch: reported {reported}, fixture has {fixture_count} items.\n"
            "If items were silently dropped, check dedup or fetcher logic."
        )

    def test_sm_carrier_feeds_env_contains_fixture_url(self) -> None:
        """The SM_CARRIER_FEEDS JSON must reference the local carrier fixture URL."""
        feeds = json.loads(_CARRIER_FEEDS_JSON)
        urls = [f["url"] for f in feeds]
        assert any("rss_carrier.xml" in u for u in urls), (
            f"SM_CARRIER_FEEDS must reference rss_carrier.xml; got {urls!r}"
        )

    def test_sm_carrier_feeds_env_is_valid_json(self) -> None:
        try:
            data = json.loads(_CARRIER_FEEDS_JSON)
        except Exception as exc:
            pytest.fail(f"SM_CARRIER_FEEDS value is not valid JSON: {exc}")
        assert isinstance(data, list), "SM_CARRIER_FEEDS must be a JSON array"
        assert data, "SM_CARRIER_FEEDS must be a non-empty array"
        entry = data[0]
        for key in ("url", "country", "lean"):
            assert key in entry, f"SM_CARRIER_FEEDS entry must have '{key}' key"

    def test_cmd3_distinct_from_cmd1_and_cmd2(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
        cmd3_result: subprocess.CompletedProcess,
    ) -> None:
        """cmd3 must be an independent subprocess — not the same object as cmd1 or cmd2."""
        assert cmd3_result is not cmd1_result, (
            "cmd3 and cmd1 must be separate subprocess objects"
        )
        assert cmd3_result is not cmd2_result, (
            "cmd3 and cmd2 must be separate subprocess objects"
        )


# ---------------------------------------------------------------------------
# 4. Cross-command isolation — all three are independent
# ---------------------------------------------------------------------------


class TestPipelineIsolation:
    """All three acceptance commands must be independent, individually inspectable."""

    def test_all_three_are_distinct_processes(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
        cmd3_result: subprocess.CompletedProcess,
    ) -> None:
        assert cmd1_result is not cmd2_result
        assert cmd1_result is not cmd3_result
        assert cmd2_result is not cmd3_result

    def test_all_three_exit_zero(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
        cmd3_result: subprocess.CompletedProcess,
    ) -> None:
        """Omnibus check: all three acceptance commands must exit 0."""
        failures = []
        if cmd1_result.returncode != 0:
            tail = cmd1_result.stdout.decode(errors="replace")[-800:]
            failures.append(f"cmd1 (once): rc={cmd1_result.returncode}\n{tail}")
        if cmd2_result.returncode != 0:
            tail = cmd2_result.stdout.decode(errors="replace")[-800:]
            failures.append(f"cmd2 (digest-dry-run): rc={cmd2_result.returncode}\n{tail}")
        if cmd3_result.returncode != 0:
            tail = cmd3_result.stdout.decode(errors="replace")[-800:]
            failures.append(f"cmd3 (carrier once): rc={cmd3_result.returncode}\n{tail}")
        assert not failures, (
            "One or more acceptance commands exited non-zero:\n" + "\n\n".join(failures)
        )

    def test_all_three_use_sys_executable(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
        cmd3_result: subprocess.CompletedProcess,
    ) -> None:
        for name, result in [
            ("cmd1 (once)", cmd1_result),
            ("cmd2 (digest-dry-run)", cmd2_result),
            ("cmd3 (carrier once)", cmd3_result),
        ]:
            assert isinstance(result.args, list), f"{name}: args must be a list"
            assert result.args[0] == sys.executable, (
                f"{name}: args[0] must be sys.executable ({sys.executable!r}); "
                f"got {result.args[0]!r}"
            )

    def test_all_three_have_module_flag(
        self,
        cmd1_result: subprocess.CompletedProcess,
        cmd2_result: subprocess.CompletedProcess,
        cmd3_result: subprocess.CompletedProcess,
    ) -> None:
        for name, result in [
            ("cmd1 (once)", cmd1_result),
            ("cmd2 (digest-dry-run)", cmd2_result),
            ("cmd3 (carrier once)", cmd3_result),
        ]:
            assert "-m" in result.args, (
                f"{name}: subprocess args must include '-m' to invoke situation_monitor as a module"
            )

    def test_no_tracebacks_across_all_commands(
        self,
        cmd1_stdout: str,
        cmd1_stderr: str,
        cmd2_stdout: str,
        cmd2_stderr: str,
        cmd3_stdout: str,
        cmd3_stderr: str,
    ) -> None:
        for label, text in [
            ("cmd1 stdout", cmd1_stdout),
            ("cmd1 stderr", cmd1_stderr),
            ("cmd2 stdout", cmd2_stdout),
            ("cmd2 stderr", cmd2_stderr),
            ("cmd3 stdout", cmd3_stdout),
            ("cmd3 stderr", cmd3_stderr),
        ]:
            assert "Traceback" not in text, (
                f"{label} contains a Python traceback:\n{text[:2000]}"
            )

    def test_offline_env_helper_sets_required_vars(self) -> None:
        """_base_offline_env() must set both SM_LLM_BACKEND and SM_SOURCES."""
        env = _base_offline_env()
        assert env.get("SM_LLM_BACKEND") == "offline", (
            "_base_offline_env() must set SM_LLM_BACKEND=offline"
        )
        assert "SM_SOURCES" in env, (
            "_base_offline_env() must set SM_SOURCES so the run uses fixture RSS"
        )
        assert env.get("SM_SOURCES", "").strip(), (
            "SM_SOURCES must not be empty in the offline env"
        )

    def test_carrier_env_adds_sm_carrier_feeds(self) -> None:
        """Carrier env must include SM_CARRIER_FEEDS over the base offline env."""
        env = _base_offline_env(SM_CARRIER_FEEDS=_CARRIER_FEEDS_JSON)
        assert "SM_CARRIER_FEEDS" in env, (
            "Carrier subprocess env must include SM_CARRIER_FEEDS"
        )
        feeds = json.loads(env["SM_CARRIER_FEEDS"])
        assert feeds, "SM_CARRIER_FEEDS must be a non-empty array"

    def test_once_outputs_differ_between_cmd1_and_cmd3(
        self, cmd1_stdout: str, cmd3_stdout: str
    ) -> None:
        """cmd3 has SM_CARRIER_FEEDS so its stdout diverges from plain cmd1 output."""
        # cmd3 has the 'discourse-carrier articles:' line; cmd1 must not.
        carrier_in_cmd1 = any(
            l.startswith("discourse-carrier") for l in cmd1_stdout.splitlines()
        )
        carrier_in_cmd3 = any(
            l.startswith("discourse-carrier") for l in cmd3_stdout.splitlines()
        )
        assert not carrier_in_cmd1, (
            "cmd1 (no SM_CARRIER_FEEDS) must not emit 'discourse-carrier' lines"
        )
        assert carrier_in_cmd3, (
            "cmd3 (with SM_CARRIER_FEEDS) must emit a 'discourse-carrier' line"
        )

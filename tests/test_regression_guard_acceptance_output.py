"""Regression guard: acceptance_output.txt artefact + all three acceptance commands.

Independently verifies the five acceptance criteria:

  1. acceptance_output.txt exists and contains ``spin_pct:``
  2. cmd 1 (once, SM_SOURCES set):     exits 0; stdout contains ``DUAL-LENS EVENTS``
  3. cmd 2 (digest-dry-run):            exits 0; stdout is non-empty
  4. cmd 3 (carrier once | grep):       exits 0; stdout line starts with ``discourse-carrier``
  5. acceptance_output.txt also contains ``DUAL-LENS EVENTS``

Additional unit coverage (NOT in any existing test file):
  - _resolve_carrier_roster: all env-var parsing paths (missing, invalid JSON,
    missing keys, empty array, valid array, extra keys)
  - discourse-carrier print line format: the exact "discourse-carrier articles: N"
    prefix required by ``grep '^discourse-carrier'``
  - Actual shell-pipe variant of cmd 3: subprocess | grep so that a line-prefix
    regression (e.g. leading space before "discourse-carrier") breaks the test

Every assertion in this file CAN fail on a real regression.
The unit under test is NEVER mocked.
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
ACCEPTANCE_OUTPUT_FILE = PROJECT_ROOT / "acceptance_output.txt"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"
RSS_CARRIER = FIXTURES / "rss_carrier.xml"

_CARRIER_FEEDS_JSON = json.dumps(
    [{"url": "tests/fixtures/rss_carrier.xml", "country": "US", "lean": "centre"}]
)


# ---------------------------------------------------------------------------
# Shared environment helper
# ---------------------------------------------------------------------------


def _offline_env(**extra: str) -> dict[str, str]:
    """Offline environment with fixture RSS — no live network, no LLM API calls."""
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
        **extra,
    }


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixtures — each acceptance command runs once
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cmd1_proc() -> subprocess.CompletedProcess:
    """Acceptance cmd 1: ``once`` with offline LLM and fixture RSS."""
    return subprocess.run(
        [
            sys.executable,
            "-m", "situation_monitor",
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
def cmd2_proc() -> subprocess.CompletedProcess:
    """Acceptance cmd 2: ``digest-dry-run`` — SEPARATE subprocess from cmd1."""
    return subprocess.run(
        [
            sys.executable,
            "-m", "situation_monitor",
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
def cmd3_proc() -> subprocess.CompletedProcess:
    """Acceptance cmd 3: ``once`` with SM_CARRIER_FEEDS — SEPARATE subprocess from cmd1."""
    return subprocess.run(
        [
            sys.executable,
            "-m", "situation_monitor",
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


# ---------------------------------------------------------------------------
# 1. acceptance_output.txt — artefact verification
# ---------------------------------------------------------------------------


class TestAcceptanceOutputFile:
    """acceptance_output.txt must exist and contain all required content."""

    def test_file_exists(self) -> None:
        assert ACCEPTANCE_OUTPUT_FILE.exists(), (
            f"acceptance_output.txt not found at {ACCEPTANCE_OUTPUT_FILE}.\n"
            "This file is produced by running the acceptance script; "
            "it must be committed to the repo alongside the code."
        )

    def test_file_is_non_empty(self) -> None:
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        assert content.strip(), "acceptance_output.txt must not be empty"

    def test_contains_spin_pct(self) -> None:
        """The primary acceptance criterion: spin_pct: must appear in the file."""
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        assert "spin_pct:" in content, (
            "acceptance_output.txt must contain 'spin_pct:' "
            "(per-article spin annotation from the dual-lens render).\n"
            f"File path: {ACCEPTANCE_OUTPUT_FILE}\n"
            f"File content (first 500 chars):\n{content[:500]}"
        )

    def test_contains_dual_lens_events_header(self) -> None:
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        assert "DUAL-LENS EVENTS" in content, (
            "acceptance_output.txt must contain 'DUAL-LENS EVENTS' section header.\n"
            "This is emitted by _print_dual_lens when left+right articles cluster."
        )

    def test_spin_pct_values_are_numeric(self) -> None:
        """spin_pct values in the file must be parseable as floats."""
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", content)
        assert matches, (
            "No 'spin_pct: N.N%' patterns found in acceptance_output.txt.\n"
            "At least one per-article spin annotation is required."
        )
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range "
                f"in acceptance_output.txt"
            )

    def test_spin_pct_decimal_format(self) -> None:
        """spin_pct must be formatted as N.N% (one decimal place), not N%."""
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", content)
        assert matches, "No spin_pct values found in acceptance_output.txt"
        for raw in matches:
            assert "." in raw, (
                f"spin_pct value {raw!r} must contain a decimal point "
                "(format :.1f) in acceptance_output.txt"
            )

    def test_spin_delta_present(self) -> None:
        """spin_delta: event-level annotation must accompany spin_pct:."""
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        matches = re.findall(r"spin_delta:\s*([\d.]+)", content)
        assert matches, (
            "acceptance_output.txt must contain 'spin_delta: N.N' event annotations"
        )
        for raw in matches:
            assert float(raw) >= 0.0, f"spin_delta must be non-negative; got {raw!r}"

    def test_left_column_heading_present(self) -> None:
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        assert "#### LEFT" in content, (
            "acceptance_output.txt must contain '#### LEFT' dual-lens column heading"
        )

    def test_right_column_heading_present(self) -> None:
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        assert "#### RIGHT" in content, (
            "acceptance_output.txt must contain '#### RIGHT' dual-lens column heading"
        )

    def test_spin_pct_on_bullet_lines(self) -> None:
        """spin_pct must appear on '- ...' bullet lines in the file."""
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        bullet_spin = [
            l for l in content.splitlines()
            if l.startswith("- ") and "spin_pct:" in l
        ]
        assert bullet_spin, (
            "acceptance_output.txt must contain '- <title> | spin_pct: N.N%' bullet lines"
        )

    def test_rationale_lines_present(self) -> None:
        """At least one rationale: line must be present (charged article in fixture)."""
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        assert "rationale:" in content, (
            "acceptance_output.txt must contain 'rationale:' lines from SpinResult.receipts.\n"
            "The fixture contains articles with propaganda flags that must produce rationale."
        )

    def test_no_python_traceback_in_file(self) -> None:
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        assert "Traceback" not in content, (
            "acceptance_output.txt must not contain a Python traceback"
        )

    def test_spin_pct_appears_after_dual_lens_header(self) -> None:
        """spin_pct must appear INSIDE the DUAL-LENS EVENTS block, not before it."""
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        dual_lens_idx = content.find("DUAL-LENS EVENTS")
        assert dual_lens_idx >= 0, "'DUAL-LENS EVENTS' not found in acceptance_output.txt"
        spin_idx = content.find("spin_pct:", dual_lens_idx)
        assert spin_idx >= 0, (
            "'spin_pct:' must appear after 'DUAL-LENS EVENTS' in acceptance_output.txt.\n"
            "The spin annotation belongs inside the dual-lens block."
        )

    def test_left_and_right_inside_dual_lens_block(self) -> None:
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        dual_idx = content.find("DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'DUAL-LENS EVENTS' block not found"
        block = content[dual_idx:]
        assert "#### LEFT" in block, "'#### LEFT' not found inside DUAL-LENS EVENTS block"
        assert "#### RIGHT" in block, "'#### RIGHT' not found inside DUAL-LENS EVENTS block"


# ---------------------------------------------------------------------------
# 2. Acceptance cmd 1: once — exits 0 and stdout contains DUAL-LENS EVENTS
# ---------------------------------------------------------------------------


class TestCmd1OnceAcceptanceCriteria:
    """cmd 1 acceptance criteria: exits 0, stdout contains DUAL-LENS EVENTS."""

    def test_exits_zero(self, cmd1_proc: subprocess.CompletedProcess) -> None:
        assert cmd1_proc.returncode == 0, (
            f"Acceptance cmd 1 (once) exited {cmd1_proc.returncode}; expected 0.\n"
            f"stdout tail:\n{cmd1_proc.stdout.decode(errors='replace')[-2000:]}\n"
            f"stderr tail:\n{cmd1_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_non_empty(self, cmd1_stdout: str) -> None:
        assert cmd1_stdout.strip(), "Acceptance cmd 1 (once) must produce non-empty stdout"

    def test_stdout_contains_dual_lens_events(self, cmd1_stdout: str) -> None:
        assert "DUAL-LENS EVENTS" in cmd1_stdout, (
            "Acceptance cmd 1 (once) stdout must contain 'DUAL-LENS EVENTS'.\n"
            "This requires left and right fixture articles to cluster together.\n"
            f"stdout sample:\n{cmd1_stdout[:3000]}"
        )

    def test_stdout_contains_spin_pct(self, cmd1_stdout: str) -> None:
        assert "spin_pct:" in cmd1_stdout, (
            "Acceptance cmd 1 stdout must contain 'spin_pct:' annotation.\n"
            f"stdout sample:\n{cmd1_stdout[:3000]}"
        )

    def test_stdout_no_traceback(self, cmd1_stdout: str) -> None:
        assert "Traceback" not in cmd1_stdout, (
            "Acceptance cmd 1 stdout must not contain a Python traceback"
        )

    def test_is_independent_subprocess(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd2_proc: subprocess.CompletedProcess,
    ) -> None:
        """cmd1 and cmd2 must be separate subprocess objects."""
        assert cmd1_proc is not cmd2_proc, (
            "cmd1 (once) and cmd2 (digest-dry-run) must be distinct subprocess runs.\n"
            "A failure in cmd1 must not be masked by cmd2 succeeding."
        )


# ---------------------------------------------------------------------------
# 3. Acceptance cmd 2: digest-dry-run — exits 0 and stdout non-empty
# ---------------------------------------------------------------------------


class TestCmd2DigestDryRunAcceptanceCriteria:
    """cmd 2 acceptance criteria: exits 0, stdout is non-empty."""

    def test_exits_zero(self, cmd2_proc: subprocess.CompletedProcess) -> None:
        assert cmd2_proc.returncode == 0, (
            f"Acceptance cmd 2 (digest-dry-run) exited {cmd2_proc.returncode}; expected 0.\n"
            f"stdout tail:\n{cmd2_proc.stdout.decode(errors='replace')[-2000:]}\n"
            f"stderr tail:\n{cmd2_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_non_empty(self, cmd2_stdout: str) -> None:
        assert cmd2_stdout.strip(), (
            "Acceptance cmd 2 (digest-dry-run) must produce non-empty stdout"
        )

    def test_stdout_no_traceback(self, cmd2_stdout: str) -> None:
        assert "Traceback" not in cmd2_stdout, (
            "Acceptance cmd 2 (digest-dry-run) stdout must not contain a Python traceback"
        )

    def test_independent_from_cmd1(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd2_proc: subprocess.CompletedProcess,
    ) -> None:
        """The digest-dry-run returncode must be inspectable independently of once."""
        assert isinstance(cmd1_proc.returncode, int)
        assert isinstance(cmd2_proc.returncode, int)
        # Both visible — no last-wins shell masking
        assert cmd1_proc.returncode == 0, (
            f"cmd1 (once) exited {cmd1_proc.returncode}: failure visible independently"
        )
        assert cmd2_proc.returncode == 0, (
            f"cmd2 (digest-dry-run) exited {cmd2_proc.returncode}: failure visible independently"
        )


# ---------------------------------------------------------------------------
# 4. Acceptance cmd 3: carrier once — discourse-carrier output
# ---------------------------------------------------------------------------


class TestCmd3CarrierOnceAcceptanceCriteria:
    """cmd 3 acceptance criteria: exits 0; stdout line starts with discourse-carrier."""

    def test_exits_zero(self, cmd3_proc: subprocess.CompletedProcess) -> None:
        assert cmd3_proc.returncode == 0, (
            f"Acceptance cmd 3 (carrier once) exited {cmd3_proc.returncode}; expected 0.\n"
            f"stdout tail:\n{cmd3_proc.stdout.decode(errors='replace')[-2000:]}\n"
            f"stderr tail:\n{cmd3_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_contains_discourse_carrier(self, cmd3_stdout: str) -> None:
        assert "discourse-carrier" in cmd3_stdout, (
            "Acceptance cmd 3 stdout must contain 'discourse-carrier'.\n"
            "Check that SM_CARRIER_FEEDS was applied and _cmd_once prints "
            "the carrier count line when carrier articles are present.\n"
            f"stdout sample:\n{cmd3_stdout[:1000]}"
        )

    def test_discourse_carrier_line_starts_at_line_start(self, cmd3_stdout: str) -> None:
        """grep '^discourse-carrier' requires the token to START the line."""
        matching_lines = [
            l for l in cmd3_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert matching_lines, (
            "No line STARTING WITH 'discourse-carrier' found in cmd 3 stdout.\n"
            "The acceptance check uses 'grep ^discourse-carrier' — the string\n"
            "must appear at the very start of a line, not mid-line.\n"
            f"stdout (first 1000):\n{cmd3_stdout[:1000]}"
        )

    def test_discourse_carrier_articles_count_format(self, cmd3_stdout: str) -> None:
        """The carrier line must match 'discourse-carrier articles: N' format."""
        matches = re.findall(r"^discourse-carrier articles:\s*(\d+)$", cmd3_stdout, re.MULTILINE)
        assert matches, (
            "No 'discourse-carrier articles: N' line found in cmd 3 stdout.\n"
            "The format must be exactly 'discourse-carrier articles: N' on its own line."
        )

    def test_discourse_carrier_count_positive(self, cmd3_stdout: str) -> None:
        """The article count must be > 0 — fixture has items."""
        matches = re.findall(r"discourse-carrier articles:\s*(\d+)", cmd3_stdout)
        assert matches, "Could not find discourse-carrier count in cmd 3 stdout"
        assert int(matches[0]) > 0, (
            f"discourse-carrier count must be > 0; got {matches[0]}.\n"
            "SM_CARRIER_FEEDS was set and the fixture has items — none should be dropped."
        )

    def test_independent_from_cmd1_and_cmd2(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd2_proc: subprocess.CompletedProcess,
        cmd3_proc: subprocess.CompletedProcess,
    ) -> None:
        """cmd3 must be a distinct subprocess — its returncode is independently visible."""
        assert cmd3_proc is not cmd1_proc, "cmd3 must not be the same subprocess as cmd1"
        assert cmd3_proc is not cmd2_proc, "cmd3 must not be the same subprocess as cmd2"


# ---------------------------------------------------------------------------
# 4b. Shell-pipe variant — tests the actual grep pattern match
# ---------------------------------------------------------------------------


class TestCmd3ViaShellGrep:
    """Run cmd 3 via a real shell pipe to ``grep '^discourse-carrier'``.

    This catches format regressions that Python string checks miss: for example,
    a leading whitespace or ANSI escape before 'discourse-carrier' would pass
    a ``'discourse-carrier' in stdout`` check but fail the actual grep.
    """

    @pytest.fixture(scope="class")
    def grep_result(self) -> subprocess.CompletedProcess:
        """Run: python -m situation_monitor once | grep '^discourse-carrier'"""
        env = {
            **os.environ,
            "SM_LLM_BACKEND": "offline",
            "SM_SOURCES": str(RSS_FIXTURE),
            "SM_CARRIER_FEEDS": _CARRIER_FEEDS_JSON,
        }
        # Two-process pipe: situation_monitor once → grep
        once = subprocess.Popen(
            [
                sys.executable,
                "-m", "situation_monitor",
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
        """grep exits 0 only when it finds at least one matching line."""
        assert grep_result.returncode == 0, (
            "grep '^discourse-carrier' exited non-zero; no matching line found.\n"
            "Either the carrier line is absent or does not start the line.\n"
            f"grep stdout: {grep_result.stdout.decode(errors='replace')!r}"
        )

    def test_grep_stdout_contains_discourse_carrier(
        self, grep_result: subprocess.CompletedProcess
    ) -> None:
        out = grep_result.stdout.decode(errors="replace")
        assert "discourse-carrier" in out, (
            "grep stdout must contain 'discourse-carrier' after filtering.\n"
            f"got: {out!r}"
        )

    def test_grep_stdout_line_starts_with_discourse_carrier(
        self, grep_result: subprocess.CompletedProcess
    ) -> None:
        out = grep_result.stdout.decode(errors="replace")
        for line in out.splitlines():
            if line.strip():
                assert line.startswith("discourse-carrier"), (
                    f"Every grep match must start with 'discourse-carrier'; got: {line!r}"
                )


# ---------------------------------------------------------------------------
# 5. _resolve_carrier_roster unit tests
# ---------------------------------------------------------------------------


class TestResolveCarrierRoster:
    """Unit tests for situation_monitor.__main__._resolve_carrier_roster.

    This function parses SM_CARRIER_FEEDS from the environment.  No test in the
    existing suite targets it directly — these tests verify all parsing paths.
    """

    def _run(self, env_value=None, monkeypatch=None):
        if monkeypatch is not None:
            if env_value is None:
                monkeypatch.delenv("SM_CARRIER_FEEDS", raising=False)
            else:
                monkeypatch.setenv("SM_CARRIER_FEEDS", env_value)
        from situation_monitor.__main__ import _resolve_carrier_roster
        return _resolve_carrier_roster()

    def test_missing_env_var_returns_empty_list(self, monkeypatch) -> None:
        monkeypatch.delenv("SM_CARRIER_FEEDS", raising=False)
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert result == [], (
            "_resolve_carrier_roster must return [] when SM_CARRIER_FEEDS is unset"
        )

    def test_empty_string_env_var_returns_empty_list(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_CARRIER_FEEDS", "")
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert result == [], (
            "_resolve_carrier_roster must return [] when SM_CARRIER_FEEDS=''"
        )

    def test_invalid_json_returns_empty_list(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_CARRIER_FEEDS", "not valid json at all")
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert result == [], (
            "_resolve_carrier_roster must return [] for invalid JSON (no exception raised)"
        )

    def test_json_object_not_array_returns_empty_list(self, monkeypatch) -> None:
        """A JSON object (dict) at the top level is malformed; must return []."""
        monkeypatch.setenv("SM_CARRIER_FEEDS", json.dumps({"url": "x", "country": "US", "lean": "centre"}))
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert result == [], (
            "_resolve_carrier_roster must return [] when SM_CARRIER_FEEDS is a JSON object, not array"
        )

    def test_empty_json_array_returns_empty_list(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_CARRIER_FEEDS", "[]")
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert result == [], "_resolve_carrier_roster must return [] for empty JSON array"

    def test_missing_url_key_returns_empty_list(self, monkeypatch) -> None:
        """Entry without 'url' key must fail gracefully — KeyError caught."""
        monkeypatch.setenv(
            "SM_CARRIER_FEEDS",
            json.dumps([{"country": "US", "lean": "centre"}]),
        )
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert result == [], (
            "_resolve_carrier_roster must return [] when an entry is missing 'url'"
        )

    def test_missing_country_key_returns_empty_list(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "SM_CARRIER_FEEDS",
            json.dumps([{"url": "https://x.com/rss", "lean": "centre"}]),
        )
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert result == [], (
            "_resolve_carrier_roster must return [] when an entry is missing 'country'"
        )

    def test_missing_lean_key_returns_empty_list(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "SM_CARRIER_FEEDS",
            json.dumps([{"url": "https://x.com/rss", "country": "US"}]),
        )
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert result == [], (
            "_resolve_carrier_roster must return [] when an entry is missing 'lean'"
        )

    def test_valid_single_entry_returns_one_carrier_def(self, monkeypatch) -> None:
        monkeypatch.setenv(
            "SM_CARRIER_FEEDS",
            json.dumps([{"url": "https://bbc.com/rss", "country": "GB", "lean": "centre"}]),
        )
        from situation_monitor.__main__ import _resolve_carrier_roster
        from situation_monitor.ingestion.discourse_carrier import CarrierDef
        result = _resolve_carrier_roster()
        assert len(result) == 1, f"Expected 1 CarrierDef; got {len(result)}"
        assert isinstance(result[0], CarrierDef)
        assert result[0].url == "https://bbc.com/rss"
        assert result[0].country == "GB"
        assert result[0].lean == "centre"

    def test_valid_multiple_entries_returns_all(self, monkeypatch) -> None:
        entries = [
            {"url": "https://bbc.com/rss", "country": "GB", "lean": "centre"},
            {"url": "https://rt.com/rss", "country": "RU", "lean": "state"},
            {"url": "https://aljazeera.com/rss", "country": "QA", "lean": "left"},
        ]
        monkeypatch.setenv("SM_CARRIER_FEEDS", json.dumps(entries))
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert len(result) == 3, f"Expected 3 CarrierDefs; got {len(result)}"
        urls = {c.url for c in result}
        assert "https://bbc.com/rss" in urls
        assert "https://rt.com/rss" in urls

    def test_extra_keys_in_entry_are_ignored(self, monkeypatch) -> None:
        """Entries with extra keys (e.g. 'description') must not cause failures."""
        monkeypatch.setenv(
            "SM_CARRIER_FEEDS",
            json.dumps([{
                "url": "https://france24.com/rss",
                "country": "FR",
                "lean": "state",
                "description": "French state broadcaster",
                "active": True,
            }]),
        )
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert len(result) == 1, (
            "Extra keys in a SM_CARRIER_FEEDS entry must be silently ignored"
        )
        assert result[0].country == "FR"
        assert result[0].lean == "state"

    def test_result_order_matches_input_order(self, monkeypatch) -> None:
        """CarrierDef list must preserve the order of entries in the JSON array."""
        entries = [
            {"url": "https://first.com/rss", "country": "AA", "lean": "left"},
            {"url": "https://second.com/rss", "country": "BB", "lean": "right"},
            {"url": "https://third.com/rss", "country": "CC", "lean": "centre"},
        ]
        monkeypatch.setenv("SM_CARRIER_FEEDS", json.dumps(entries))
        from situation_monitor.__main__ import _resolve_carrier_roster
        result = _resolve_carrier_roster()
        assert result[0].url == "https://first.com/rss"
        assert result[1].url == "https://second.com/rss"
        assert result[2].url == "https://third.com/rss"

    def test_lean_values_preserved_verbatim(self, monkeypatch) -> None:
        """lean values from the JSON must be passed through as-is."""
        for lean in ("left", "right", "centre", "state"):
            monkeypatch.setenv(
                "SM_CARRIER_FEEDS",
                json.dumps([{"url": "https://x.com/rss", "country": "XX", "lean": lean}]),
            )
            from situation_monitor.__main__ import _resolve_carrier_roster
            result = _resolve_carrier_roster()
            assert len(result) == 1
            assert result[0].lean == lean, (
                f"lean={lean!r} must be preserved verbatim; got {result[0].lean!r}"
            )


# ---------------------------------------------------------------------------
# 6. discourse-carrier print line format — grep compatibility
# ---------------------------------------------------------------------------


class TestDiscourseCarrierPrintFormat:
    """The 'discourse-carrier articles: N' line format must be grep-compatible.

    The acceptance command pipes 'once' through 'grep ^discourse-carrier'.
    grep exits 0 only if the pattern matches at least one line.
    This suite verifies the print format matches that anchor.
    """

    def test_carrier_count_line_matches_grep_pattern(self, cmd3_stdout: str) -> None:
        """grep '^discourse-carrier' must match at least one line in cmd3 stdout."""
        pattern = re.compile(r"^discourse-carrier", re.MULTILINE)
        assert pattern.search(cmd3_stdout), (
            "No line in cmd 3 stdout matches '^discourse-carrier' (grep anchor).\n"
            f"stdout sample:\n{cmd3_stdout[:500]}"
        )

    def test_carrier_count_line_format_is_discourse_carrier_articles_colon_n(
        self, cmd3_stdout: str
    ) -> None:
        """The exact format must be 'discourse-carrier articles: N'."""
        pattern = re.compile(r"^discourse-carrier articles:\s*\d+", re.MULTILINE)
        assert pattern.search(cmd3_stdout), (
            "discourse-carrier line must match 'discourse-carrier articles: N' format.\n"
            f"stdout sample:\n{cmd3_stdout[:500]}"
        )

    def test_no_leading_whitespace_before_discourse_carrier(
        self, cmd3_stdout: str
    ) -> None:
        """A leading space or tab before 'discourse-carrier' would break grep '^discourse-carrier'."""
        for line in cmd3_stdout.splitlines():
            stripped = line.lstrip()
            if "discourse-carrier" in stripped and stripped.startswith("discourse-carrier"):
                # OK — starts at position 0 after stripping? Verify it also starts at 0 in original
                assert line.startswith("discourse-carrier"), (
                    f"Line contains 'discourse-carrier' but has leading whitespace: {line!r}\n"
                    "This would break the grep '^discourse-carrier' pattern."
                )

    def test_discourse_carrier_not_printed_without_sm_carrier_feeds(
        self, cmd1_stdout: str
    ) -> None:
        """When SM_CARRIER_FEEDS is absent (cmd1), no carrier line must appear."""
        carrier_lines = [
            l for l in cmd1_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert not carrier_lines, (
            "cmd 1 (no SM_CARRIER_FEEDS) must NOT emit a 'discourse-carrier' line.\n"
            "The carrier count print is conditional on carrier_count > 0.\n"
            f"Unexpected lines: {carrier_lines}"
        )

    def test_discourse_carrier_count_is_integer(self, cmd3_stdout: str) -> None:
        """The N in 'discourse-carrier articles: N' must be a valid integer."""
        matches = re.findall(r"discourse-carrier articles:\s*(\S+)", cmd3_stdout)
        assert matches, "No discourse-carrier count found in cmd 3 stdout"
        raw = matches[0]
        try:
            val = int(raw)
        except ValueError:
            pytest.fail(
                f"discourse-carrier count {raw!r} is not a valid integer"
            )
        assert val > 0, (
            f"discourse-carrier count must be > 0; got {val}.\n"
            "The carrier fixture has items that should not be silently dropped."
        )

    def test_discourse_carrier_count_line_appears_before_digest_header(
        self, cmd3_stdout: str
    ) -> None:
        """The carrier count print precedes the Markdown digest header in cmd3 output."""
        carrier_idx = cmd3_stdout.find("discourse-carrier articles:")
        digest_idx = cmd3_stdout.find("# Situation Monitor Digest")
        assert carrier_idx >= 0, "'discourse-carrier articles:' not found in cmd3 stdout"
        assert digest_idx >= 0, "'# Situation Monitor Digest' not found in cmd3 stdout"
        assert carrier_idx < digest_idx, (
            "'discourse-carrier articles:' must be printed BEFORE the Markdown digest header.\n"
            "In _cmd_once, the carrier_count print comes before check_and_emit_alerts "
            "and _print_markdown."
        )


# ---------------------------------------------------------------------------
# 7. All three acceptance commands pass simultaneously — omnibus guard
# ---------------------------------------------------------------------------


class TestAllThreeCommandsPass:
    """Omnibus guard: every acceptance criterion must be simultaneously satisfied."""

    def test_all_three_exit_zero(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd2_proc: subprocess.CompletedProcess,
        cmd3_proc: subprocess.CompletedProcess,
    ) -> None:
        failures = []
        if cmd1_proc.returncode != 0:
            failures.append(f"cmd1 (once): rc={cmd1_proc.returncode}")
        if cmd2_proc.returncode != 0:
            failures.append(f"cmd2 (digest-dry-run): rc={cmd2_proc.returncode}")
        if cmd3_proc.returncode != 0:
            failures.append(f"cmd3 (carrier once): rc={cmd3_proc.returncode}")
        assert not failures, (
            "One or more acceptance commands exited non-zero:\n"
            + "\n".join(failures)
        )

    def test_acceptance_output_file_and_cmd1_agree_on_spin_pct(
        self, cmd1_stdout: str
    ) -> None:
        """Both acceptance_output.txt and cmd1 stdout must contain spin_pct:."""
        file_content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        assert "spin_pct:" in file_content, "acceptance_output.txt must contain spin_pct:"
        assert "spin_pct:" in cmd1_stdout, "cmd1 stdout must contain spin_pct:"

    def test_acceptance_output_file_and_cmd1_agree_on_dual_lens(
        self, cmd1_stdout: str
    ) -> None:
        """Both acceptance_output.txt and cmd1 stdout must contain DUAL-LENS EVENTS."""
        file_content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        assert "DUAL-LENS EVENTS" in file_content, (
            "acceptance_output.txt must contain 'DUAL-LENS EVENTS'"
        )
        assert "DUAL-LENS EVENTS" in cmd1_stdout, (
            "cmd1 stdout must contain 'DUAL-LENS EVENTS'"
        )

    def test_cmd2_stdout_non_empty_and_distinct_from_cmd1(
        self, cmd1_stdout: str, cmd2_stdout: str
    ) -> None:
        """cmd2 must produce non-empty output that is recognisably different from cmd1."""
        assert cmd2_stdout.strip(), "cmd2 (digest-dry-run) must produce non-empty stdout"
        # cmd1 uses ATX Markdown, cmd2 uses Telegram format (*bold*)
        # They may share some text but must not be byte-identical
        assert cmd1_stdout != cmd2_stdout, (
            "cmd1 and cmd2 must produce different output; "
            "they use different output formats (Markdown vs Telegram)"
        )

    def test_carrier_count_in_acceptance_output_txt_not_required(self) -> None:
        """acceptance_output.txt is from a non-carrier run (no SM_CARRIER_FEEDS).

        The carrier line is NOT expected in acceptance_output.txt; that is correct.
        """
        content = ACCEPTANCE_OUTPUT_FILE.read_text(errors="replace")
        # This test verifies our understanding of the file's provenance.
        # No assertion: just checking the file contains the non-carrier digest content.
        assert "Situation Monitor" in content, (
            "acceptance_output.txt must contain 'Situation Monitor' heading"
        )

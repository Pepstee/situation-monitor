"""Acceptance command isolation: each of the three acceptance file lines runs as its own subprocess.

The acceptance file contains three commands:
  1. ``situation_monitor once``            — ingest, enrich, print Markdown + dual-lens output
  2. ``situation_monitor digest-dry-run``  — assemble Telegram digest and print it (must be ≤10 s)
  3. ``situation_monitor once`` with carrier feeds | grep ``^discourse-carrier``

Running all three via a single shell pipeline masks failures: only the last exit code
propagates.  This file launches each as a **separate** subprocess so a failure in any
command is visible independently — and the third command's grep check is replicated by
inspecting stdout directly rather than piping to an external process.

Primary acceptance functions (named exactly to match the acceptance spec):
  test_once_offline          — line 1: returncode==0, DUAL-LENS section, LEFT/RIGHT/spin_pct
  test_digest_dry_run_offline — line 2: returncode==0, ≤10 s, '*Situation Monitor*' in stdout
  test_carrier_grep          — line 3: returncode==0, stdout contains a 'discourse-carrier' line
  test_domain_headers        — once stdout contains ## WORLD, ## MARKETS, ## AI section headers
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"
RSS_CARRIER = FIXTURES / "rss_carrier.xml"

# Maximum wall-clock seconds allowed for digest-dry-run in offline mode.
_DIGEST_TIMEOUT = 10


# ---------------------------------------------------------------------------
# Shared env helpers
# ---------------------------------------------------------------------------


def _offline_env(**extra: str) -> dict[str, str]:
    """Return an environment dict with SM_LLM_BACKEND=offline and the RSS fixture source."""
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
        **extra,
    }


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixtures
# Each line of the acceptance file becomes one fixture; tests share them.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _once_proc() -> subprocess.CompletedProcess:
    """Line 1 of the acceptance file: 'once' with offline backend + acceptance_source_defs.json."""
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
def _once_stdout(_once_proc: subprocess.CompletedProcess) -> str:
    return _once_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def _digest_proc() -> subprocess.CompletedProcess:
    """Line 2 of the acceptance file: 'digest-dry-run', must complete within _DIGEST_TIMEOUT s."""
    # timeout= enforces the wall-clock limit at the OS level; TimeoutExpired propagates as an error.
    start = time.monotonic()
    result = subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "digest-dry-run",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=_DIGEST_TIMEOUT,
    )
    result._elapsed = time.monotonic() - start  # type: ignore[attr-defined]
    return result


@pytest.fixture(scope="module")
def _carrier_proc() -> subprocess.CompletedProcess:
    """Line 3 of the acceptance file: 'once' with SM_CARRIER_FEEDS pointing to the fixture.

    Note: the acceptance file does NOT set SM_SOURCES for this line, matching the fact
    that only the carrier feeds (and source_defs config) are active.
    """
    carrier_payload = json.dumps([
        {"url": str(RSS_CARRIER), "country": "US", "lean": "centre"},
    ])
    env = {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_CARRIER_FEEDS": carrier_payload,
    }
    return subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "once",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=120,
    )


# ---------------------------------------------------------------------------
# Fixture prerequisite guards (fast, no subprocess)
# ---------------------------------------------------------------------------


class TestFixtureGuards:
    """All fixture files the subprocess commands depend on must exist and be parseable."""

    def test_acceptance_source_defs_exists(self) -> None:
        assert ACCEPTANCE_SOURCE_DEFS.exists(), f"Missing fixture: {ACCEPTANCE_SOURCE_DEFS}"

    def test_rss_sample_exists(self) -> None:
        assert RSS_FIXTURE.exists(), f"Missing fixture: {RSS_FIXTURE}"

    def test_rss_carrier_exists(self) -> None:
        assert RSS_CARRIER.exists(), f"Missing fixture: {RSS_CARRIER}"

    def test_acceptance_source_defs_is_valid_json(self) -> None:
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        assert "source_defs" in data, "acceptance_source_defs.json must contain 'source_defs' key"

    def test_source_defs_has_left_right_and_domain_entries(self) -> None:
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        defs = data.get("source_defs", [])
        lenses = {d.get("lens") for d in defs}
        domains = {d.get("domain") for d in defs}
        assert "left" in lenses, "source_defs must include a 'left' lens entry for DUAL-LENS output"
        assert "right" in lenses, "source_defs must include a 'right' lens entry for DUAL-LENS output"
        assert "WORLD" in domains, "source_defs must include a WORLD domain entry"
        assert "MARKETS" in domains, "source_defs must include a MARKETS domain entry"
        assert "AI" in domains, "source_defs must include an AI domain entry"

    def test_carrier_fixture_is_valid_rss(self) -> None:
        import xml.etree.ElementTree as ET
        tree = ET.fromstring(RSS_CARRIER.read_bytes())
        assert tree.tag == "rss", "rss_carrier.xml root element must be <rss>"
        channel = tree.find("channel")
        assert channel is not None, "rss_carrier.xml must have a <channel> element"
        items = channel.findall("item")
        assert len(items) >= 1, "rss_carrier.xml must have at least one <item>"


# ---------------------------------------------------------------------------
# test_once_offline — line 1 acceptance criteria
# ---------------------------------------------------------------------------


def test_once_offline(
    _once_proc: subprocess.CompletedProcess,
    _once_stdout: str,
) -> None:
    """'once' offline exits 0, produces non-empty stdout, has DUAL-LENS block with LEFT/RIGHT/spin_pct."""
    stderr = _once_proc.stderr.decode(errors="replace")
    assert _once_proc.returncode == 0, (
        f"'once' exited {_once_proc.returncode}; expected 0.\n"
        f"stdout tail:\n{_once_stdout[-2000:]}\n"
        f"stderr:\n{stderr[:500]}"
    )
    assert _once_stdout.strip(), "'once' produced no stdout"
    assert "## DUAL-LENS EVENTS" in _once_stdout, (
        "'once' stdout missing '## DUAL-LENS EVENTS' section header.\n"
        f"stdout (first 3000 chars):\n{_once_stdout[:3000]}"
    )
    assert "#### LEFT" in _once_stdout, (
        "'once' stdout missing '#### LEFT' dual-lens column heading.\n"
        f"stdout (first 3000 chars):\n{_once_stdout[:3000]}"
    )
    assert "#### RIGHT" in _once_stdout, (
        "'once' stdout missing '#### RIGHT' dual-lens column heading.\n"
        f"stdout (first 3000 chars):\n{_once_stdout[:3000]}"
    )
    assert "spin_pct:" in _once_stdout, (
        "'once' stdout missing 'spin_pct:' article-level annotation.\n"
        f"stdout (first 3000 chars):\n{_once_stdout[:3000]}"
    )


# ---------------------------------------------------------------------------
# test_digest_dry_run_offline — line 2 acceptance criteria (≤10 s wall-clock)
# ---------------------------------------------------------------------------


def test_digest_dry_run_offline(_digest_proc: subprocess.CompletedProcess) -> None:
    """'digest-dry-run' offline exits 0, completes in ≤10 s, contains '*Situation Monitor*'."""
    stdout = _digest_proc.stdout.decode(errors="replace")
    stderr = _digest_proc.stderr.decode(errors="replace")

    assert _digest_proc.returncode == 0, (
        f"'digest-dry-run' exited {_digest_proc.returncode}; expected 0.\n"
        f"stdout tail:\n{stdout[-2000:]}\n"
        f"stderr:\n{stderr[:500]}"
    )
    assert stdout.strip(), "'digest-dry-run' produced no stdout"
    assert "*Situation Monitor*" in stdout, (
        "'digest-dry-run' stdout missing '*Situation Monitor*' Telegram header.\n"
        f"stdout:\n{stdout[:1000]}"
    )
    # Wall-clock budget: _DIGEST_TIMEOUT enforces it via subprocess timeout; the
    # _elapsed attribute is the measured runtime for diagnostics when available.
    elapsed = getattr(_digest_proc, "_elapsed", None)
    if elapsed is not None:
        assert elapsed <= _DIGEST_TIMEOUT, (
            f"'digest-dry-run' took {elapsed:.2f} s — must complete within {_DIGEST_TIMEOUT} s "
            "in offline mode (no network, no LLM API calls)"
        )


# ---------------------------------------------------------------------------
# test_carrier_grep — line 3 acceptance criteria
# ---------------------------------------------------------------------------


def test_carrier_grep(_carrier_proc: subprocess.CompletedProcess) -> None:
    """'once' with SM_CARRIER_FEEDS exits 0 and emits a line starting with 'discourse-carrier'."""
    stdout = _carrier_proc.stdout.decode(errors="replace")
    stderr = _carrier_proc.stderr.decode(errors="replace")

    assert _carrier_proc.returncode == 0, (
        f"'once' with carrier feeds exited {_carrier_proc.returncode}; expected 0.\n"
        f"stderr:\n{stderr[:500]}"
    )
    assert stdout.strip(), "'once' with carrier feeds produced no stdout"

    carrier_lines = [ln for ln in stdout.splitlines() if ln.startswith("discourse-carrier")]
    assert carrier_lines, (
        "No line starting with 'discourse-carrier' found in stdout.\n"
        "Expected a summary line like 'discourse-carrier articles: N' when "
        "SM_CARRIER_FEEDS is set to a non-empty carrier roster.\n"
        f"stdout (first 2000 chars):\n{stdout[:2000]}"
    )


# ---------------------------------------------------------------------------
# test_domain_headers — 'once' stdout must contain all three domain section headers
# ---------------------------------------------------------------------------


def test_domain_headers(_once_stdout: str) -> None:
    """'once' stdout contains ## WORLD, ## MARKETS, and ## AI section headers."""
    assert "## WORLD" in _once_stdout, (
        "'once' stdout missing '## WORLD' section header.\n"
        "Check that acceptance_source_defs.json contains WORLD-domain source entries "
        "and the RSS fixtures are valid.\n"
        f"stdout (first 3000 chars):\n{_once_stdout[:3000]}"
    )
    assert "## MARKETS" in _once_stdout, (
        "'once' stdout missing '## MARKETS' section header.\n"
        "Check that rss_markets.xml is present and contains MARKETS-domain articles.\n"
        f"stdout (first 3000 chars):\n{_once_stdout[:3000]}"
    )
    assert "## AI" in _once_stdout, (
        "'once' stdout missing '## AI' section header.\n"
        "Check that rss_ai.xml is present and contains AI-domain articles.\n"
        f"stdout (first 3000 chars):\n{_once_stdout[:3000]}"
    )


# ---------------------------------------------------------------------------
# Edge-case and structural tests
# ---------------------------------------------------------------------------


class TestOnceOutputStructure:
    """Structural invariants of the 'once' command output beyond the primary criteria."""

    def test_no_traceback_in_stdout(self, _once_stdout: str) -> None:
        assert "Traceback" not in _once_stdout, (
            "'once' stdout must not contain a Python traceback.\n"
            f"stdout (first 2000 chars):\n{_once_stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, _once_proc: subprocess.CompletedProcess) -> None:
        stderr = _once_proc.stderr.decode(errors="replace")
        assert "Traceback" not in stderr, (
            f"'once' stderr contains a Python traceback:\n{stderr[:2000]}"
        )

    def test_situation_monitor_heading_present(self, _once_stdout: str) -> None:
        assert "Situation Monitor" in _once_stdout, (
            "'once' stdout must contain a 'Situation Monitor' heading"
        )

    def test_left_heading_is_h4_line(self, _once_stdout: str) -> None:
        h4_left = [ln for ln in _once_stdout.splitlines() if ln.startswith("#### LEFT")]
        assert h4_left, (
            "No line starting with '#### LEFT' found — LEFT must be an H4 heading, "
            "not embedded in prose"
        )

    def test_right_heading_is_h4_line(self, _once_stdout: str) -> None:
        h4_right = [ln for ln in _once_stdout.splitlines() if ln.startswith("#### RIGHT")]
        assert h4_right, (
            "No line starting with '#### RIGHT' found — RIGHT must be an H4 heading"
        )

    def test_left_inside_dual_lens_block(self, _once_stdout: str) -> None:
        idx = _once_stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0, "'## DUAL-LENS EVENTS' block not found"
        assert "#### LEFT" in _once_stdout[idx:], (
            "'#### LEFT' must appear inside the '## DUAL-LENS EVENTS' block"
        )

    def test_right_inside_dual_lens_block(self, _once_stdout: str) -> None:
        idx = _once_stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0, "'## DUAL-LENS EVENTS' block not found"
        assert "#### RIGHT" in _once_stdout[idx:], (
            "'#### RIGHT' must appear inside the '## DUAL-LENS EVENTS' block"
        )

    def test_spin_pct_format_is_decimal(self, _once_stdout: str) -> None:
        """spin_pct values must include a decimal point (e.g. '43.4%', not '43%')."""
        matches = re.findall(r"spin_pct:\s*(\d+\.\d+)%", _once_stdout)
        assert matches, (
            "No 'spin_pct: N.N%' (decimal format) found in 'once' stdout.\n"
            "Expected format: 'spin_pct: 50.0%'"
        )

    def test_spin_pct_values_in_range(self, _once_stdout: str) -> None:
        """All spin_pct values must be in the valid [0, 100] range."""
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", _once_stdout)
        assert matches, "No spin_pct values found — cannot verify range"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range"
            )

    def test_spin_pct_on_bullet_lines(self, _once_stdout: str) -> None:
        """spin_pct must appear on '- ...' article bullet lines, not standalone."""
        spin_bullets = [
            ln for ln in _once_stdout.splitlines()
            if ln.startswith("- ") and "spin_pct:" in ln
        ]
        assert spin_bullets, (
            "No '- ...' bullet line containing 'spin_pct:' found.\n"
            "Expected format: '- <title> | spin_pct: N.N%'"
        )

    def test_spin_delta_present(self, _once_stdout: str) -> None:
        """spin_delta event annotation must co-occur with spin_pct."""
        matches = re.findall(r"spin_delta:\s*([\d.]+)", _once_stdout)
        assert matches, (
            "'once' stdout must contain 'spin_delta: N.N' event-level annotations"
        )

    def test_spin_delta_non_negative(self, _once_stdout: str) -> None:
        for raw in re.findall(r"spin_delta:\s*([\d.]+)", _once_stdout):
            assert float(raw) >= 0.0, f"spin_delta must be non-negative; got {raw!r}"

    def test_domain_headers_ordered_world_markets_ai(self, _once_stdout: str) -> None:
        """Domain sections must appear in WORLD → MARKETS → AI order."""
        idx_world = _once_stdout.find("## WORLD")
        idx_markets = _once_stdout.find("## MARKETS")
        idx_ai = _once_stdout.find("## AI")
        assert idx_world < idx_markets, (
            "'## WORLD' must appear before '## MARKETS' in 'once' stdout"
        )
        assert idx_markets < idx_ai, (
            "'## MARKETS' must appear before '## AI' in 'once' stdout"
        )

    def test_dual_lens_block_after_domain_sections(self, _once_stdout: str) -> None:
        """The DUAL-LENS EVENTS block must come after the domain sections."""
        idx_ai = _once_stdout.find("## AI")
        idx_dual = _once_stdout.find("## DUAL-LENS EVENTS")
        assert idx_ai >= 0, "'## AI' not found in 'once' stdout"
        assert idx_dual >= 0, "'## DUAL-LENS EVENTS' not found in 'once' stdout"
        assert idx_dual > idx_ai, (
            "'## DUAL-LENS EVENTS' must appear after the domain sections, not before"
        )


class TestDigestOutputStructure:
    """Structural invariants of the digest-dry-run output."""

    def test_no_traceback_in_stdout(self, _digest_proc: subprocess.CompletedProcess) -> None:
        stdout = _digest_proc.stdout.decode(errors="replace")
        assert "Traceback" not in stdout, (
            f"'digest-dry-run' stdout must not contain a Python traceback.\n"
            f"stdout:\n{stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, _digest_proc: subprocess.CompletedProcess) -> None:
        stderr = _digest_proc.stderr.decode(errors="replace")
        assert "Traceback" not in stderr, (
            f"'digest-dry-run' stderr contains a Python traceback:\n{stderr[:2000]}"
        )

    def test_digest_contains_utc_timestamp(
        self, _digest_proc: subprocess.CompletedProcess
    ) -> None:
        stdout = _digest_proc.stdout.decode(errors="replace")
        assert "UTC" in stdout, (
            "'digest-dry-run' output must include a UTC timestamp"
        )

    def test_digest_situation_monitor_is_bold_markdown(
        self, _digest_proc: subprocess.CompletedProcess
    ) -> None:
        """The '*Situation Monitor*' label must be Telegram bold-markdown format."""
        stdout = _digest_proc.stdout.decode(errors="replace")
        assert "*Situation Monitor*" in stdout, (
            "Telegram digest must use '*Situation Monitor*' (bold markdown), not a plain heading"
        )


class TestCarrierOutputStructure:
    """Structural properties of the carrier-feeds 'once' run."""

    def test_no_traceback_in_stdout(self, _carrier_proc: subprocess.CompletedProcess) -> None:
        stdout = _carrier_proc.stdout.decode(errors="replace")
        assert "Traceback" not in stdout, (
            f"carrier 'once' stdout must not contain a Python traceback:\n{stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, _carrier_proc: subprocess.CompletedProcess) -> None:
        stderr = _carrier_proc.stderr.decode(errors="replace")
        assert "Traceback" not in stderr, (
            f"carrier 'once' stderr contains a Python traceback:\n{stderr[:2000]}"
        )

    def test_carrier_line_contains_positive_count(
        self, _carrier_proc: subprocess.CompletedProcess
    ) -> None:
        """The discourse-carrier summary line must report at least 1 article."""
        stdout = _carrier_proc.stdout.decode(errors="replace")
        carrier_lines = [ln for ln in stdout.splitlines() if ln.startswith("discourse-carrier")]
        assert carrier_lines, "No 'discourse-carrier' line found"
        line = carrier_lines[0]
        match = re.search(r"(\d+)", line)
        assert match, f"No integer count found in carrier line: {line!r}"
        count = int(match.group(1))
        assert count >= 1, (
            f"Carrier article count must be >= 1; got {count} in line: {line!r}"
        )

    def test_carrier_line_format(self, _carrier_proc: subprocess.CompletedProcess) -> None:
        """The carrier summary line must follow the 'discourse-carrier articles: N' format."""
        stdout = _carrier_proc.stdout.decode(errors="replace")
        carrier_lines = [ln for ln in stdout.splitlines() if ln.startswith("discourse-carrier")]
        assert carrier_lines, "No 'discourse-carrier' line found"
        assert re.match(r"discourse-carrier articles: \d+", carrier_lines[0]), (
            f"Carrier line does not match expected format 'discourse-carrier articles: N'; "
            f"got: {carrier_lines[0]!r}"
        )

    def test_carrier_markdown_still_present(
        self, _carrier_proc: subprocess.CompletedProcess
    ) -> None:
        """Even with carrier feeds active, 'once' must still emit the Situation Monitor header."""
        stdout = _carrier_proc.stdout.decode(errors="replace")
        assert "Situation Monitor" in stdout, (
            "Carrier 'once' run must still emit the Situation Monitor heading"
        )


class TestSubprocessIsolation:
    """Confirm that the three acceptance commands run as genuinely independent subprocesses."""

    def test_once_and_digest_are_different_processes(
        self,
        _once_proc: subprocess.CompletedProcess,
        _digest_proc: subprocess.CompletedProcess,
    ) -> None:
        assert _once_proc is not _digest_proc, (
            "'once' and 'digest-dry-run' must be separate subprocess objects"
        )

    def test_once_and_carrier_are_different_processes(
        self,
        _once_proc: subprocess.CompletedProcess,
        _carrier_proc: subprocess.CompletedProcess,
    ) -> None:
        assert _once_proc is not _carrier_proc, (
            "'once' (offline) and 'once' (carrier) must be separate subprocess objects"
        )

    def test_once_invoked_via_sys_executable(
        self, _once_proc: subprocess.CompletedProcess
    ) -> None:
        args = _once_proc.args
        assert isinstance(args, list), f"'once' must use args list, got {type(args)}"
        assert args[0] == sys.executable, (
            f"'once' must be launched via sys.executable; got {args[0]!r}"
        )
        assert "once" in args, f"'once' subcommand missing from args: {args!r}"

    def test_digest_invoked_via_sys_executable(
        self, _digest_proc: subprocess.CompletedProcess
    ) -> None:
        args = _digest_proc.args
        assert isinstance(args, list), f"'digest-dry-run' must use args list"
        assert args[0] == sys.executable, (
            f"'digest-dry-run' must be launched via sys.executable; got {args[0]!r}"
        )
        assert "digest-dry-run" in args, (
            f"'digest-dry-run' subcommand missing from args: {args!r}"
        )

    def test_carrier_invoked_via_sys_executable(
        self, _carrier_proc: subprocess.CompletedProcess
    ) -> None:
        args = _carrier_proc.args
        assert isinstance(args, list), f"'once' (carrier) must use args list"
        assert args[0] == sys.executable, (
            f"'once' (carrier) must be launched via sys.executable; got {args[0]!r}"
        )

    def test_once_returncode_independent_of_digest(
        self,
        _once_proc: subprocess.CompletedProcess,
        _digest_proc: subprocess.CompletedProcess,
    ) -> None:
        """Each returncode is independently accessible — no last-wins pipeline masking."""
        assert isinstance(_once_proc.returncode, int)
        assert isinstance(_digest_proc.returncode, int)
        assert _once_proc.returncode == 0, (
            f"once returncode={_once_proc.returncode} visible independently of "
            f"digest-dry-run returncode={_digest_proc.returncode}"
        )
        assert _digest_proc.returncode == 0, (
            f"digest-dry-run returncode={_digest_proc.returncode} visible independently of "
            f"once returncode={_once_proc.returncode}"
        )

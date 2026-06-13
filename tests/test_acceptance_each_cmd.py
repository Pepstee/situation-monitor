"""Independent acceptance guard: each acceptance command runs in its own subprocess.

The acceptance script contains two commands:
  1. ``situation_monitor once``            — ingest, enrich, print Markdown + dual-lens output
  2. ``situation_monitor digest-dry-run``  — assemble Telegram digest and print it

Running them via the combined shell acceptance file hides failures in the first
command when the second succeeds: only the last exit code propagates in a shell
pipeline.  This file runs each command as a **separate** subprocess via
``sys.executable`` so that a failure in ``once`` cannot be masked by
``digest-dry-run`` succeeding.

Acceptance criteria verified:
  - ``once`` subprocess exits 0
  - ``digest-dry-run`` subprocess exits 0  (separate call, separate returncode)
  - ``once`` stdout contains ``#### LEFT``
  - ``once`` stdout contains ``#### RIGHT``
  - ``once`` stdout contains ``spin_pct:``
  - Both commands are invoked via ``sys.executable``, not a shell string
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"


# ---------------------------------------------------------------------------
# Shared offline environment — no live network, no LLM API calls
# ---------------------------------------------------------------------------


def _offline_env() -> dict[str, str]:
    """Force the deterministic offline LLM backend and RSS fixture.

    Mirrors the environment the acceptance script uses so the commands are
    byte-for-byte equivalent, but launched via sys.executable instead of
    a bare shell ``python3``.
    """
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
    }


# ---------------------------------------------------------------------------
# Module-scoped fixtures — each subprocess runs exactly once per test session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def once_result() -> subprocess.CompletedProcess:
    """Run ``situation_monitor once`` as an isolated subprocess."""
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
def once_stdout(once_result: subprocess.CompletedProcess) -> str:
    return once_result.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def digest_dry_run_result() -> subprocess.CompletedProcess:
    """Run ``situation_monitor digest-dry-run`` as a SEPARATE isolated subprocess.

    This is the key invariant: a non-zero exit from ``once`` does not bleed
    into this call, so failures in either command are independently visible.
    """
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
def digest_dry_run_stdout(digest_dry_run_result: subprocess.CompletedProcess) -> str:
    return digest_dry_run_result.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# Guard: verify the two fixture paths the commands depend on exist
# ---------------------------------------------------------------------------


class TestFixturePrerequisites:
    """Fixtures must exist before either command can run meaningfully."""

    def test_acceptance_source_defs_exists(self) -> None:
        assert ACCEPTANCE_SOURCE_DEFS.exists(), (
            f"Missing fixture: {ACCEPTANCE_SOURCE_DEFS}"
        )

    def test_rss_sample_fixture_exists(self) -> None:
        assert RSS_FIXTURE.exists(), (
            f"Missing fixture: {RSS_FIXTURE}"
        )

    def test_acceptance_source_defs_is_valid_json(self) -> None:
        import json
        try:
            data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        except Exception as exc:
            pytest.fail(f"acceptance_source_defs.json is not valid JSON: {exc}")
        assert "source_defs" in data, (
            "acceptance_source_defs.json must contain a 'source_defs' key"
        )

    def test_acceptance_source_defs_has_left_and_right_entries(self) -> None:
        import json
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        lenses = {d.get("lens") for d in data.get("source_defs", [])}
        assert "left" in lenses, "source_defs must include at least one 'left' lens entry"
        assert "right" in lenses, "source_defs must include at least one 'right' lens entry"


# ---------------------------------------------------------------------------
# 1. ``once`` command: exits 0
# ---------------------------------------------------------------------------


class TestOnceExitsZero:
    """``situation_monitor once`` must exit 0 in a standalone subprocess."""

    def test_once_returncode_is_zero(self, once_result: subprocess.CompletedProcess) -> None:
        assert once_result.returncode == 0, (
            f"'once' subprocess exited {once_result.returncode}; expected 0.\n"
            "A non-zero exit here would be hidden when running the acceptance file\n"
            "as a combined shell command (last exit code wins).\n"
            f"stdout tail:\n{once_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"stderr tail:\n{once_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_once_produces_output(self, once_stdout: str) -> None:
        assert once_stdout.strip(), (
            "'once' subprocess produced no stdout output"
        )

    def test_once_no_traceback_in_stdout(self, once_stdout: str) -> None:
        assert "Traceback" not in once_stdout, (
            "'once' stdout must not contain a Python traceback.\n"
            f"stdout sample:\n{once_stdout[:2000]}"
        )

    def test_once_no_traceback_in_stderr(self, once_result: subprocess.CompletedProcess) -> None:
        stderr = once_result.stderr.decode(errors="replace")
        assert "Traceback" not in stderr, (
            f"'once' stderr contains a Python traceback:\n{stderr[:2000]}"
        )

    def test_once_emits_situation_monitor_heading(self, once_stdout: str) -> None:
        assert "Situation Monitor" in once_stdout, (
            "'once' stdout must contain 'Situation Monitor' heading"
        )


# ---------------------------------------------------------------------------
# 2. ``digest-dry-run`` command: exits 0 — SEPARATE subprocess call
# ---------------------------------------------------------------------------


class TestDigestDryRunExitsZero:
    """``situation_monitor digest-dry-run`` must exit 0 in its own subprocess.

    The fixture for this test is INDEPENDENT of the ``once`` fixture.  A
    failure in ``once`` does NOT affect this test's subprocess or its returncode.
    """

    def test_digest_dry_run_returncode_is_zero(
        self, digest_dry_run_result: subprocess.CompletedProcess
    ) -> None:
        assert digest_dry_run_result.returncode == 0, (
            f"'digest-dry-run' subprocess exited {digest_dry_run_result.returncode}; expected 0.\n"
            f"stdout tail:\n{digest_dry_run_result.stdout.decode(errors='replace')[-3000:]}\n"
            f"stderr tail:\n{digest_dry_run_result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_digest_dry_run_produces_output(self, digest_dry_run_stdout: str) -> None:
        assert digest_dry_run_stdout.strip(), (
            "'digest-dry-run' subprocess produced no stdout output"
        )

    def test_digest_dry_run_no_traceback_in_stdout(self, digest_dry_run_stdout: str) -> None:
        assert "Traceback" not in digest_dry_run_stdout, (
            f"'digest-dry-run' stdout must not contain a Python traceback.\n"
            f"stdout sample:\n{digest_dry_run_stdout[:2000]}"
        )

    def test_digest_dry_run_no_traceback_in_stderr(
        self, digest_dry_run_result: subprocess.CompletedProcess
    ) -> None:
        stderr = digest_dry_run_result.stderr.decode(errors="replace")
        assert "Traceback" not in stderr, (
            f"'digest-dry-run' stderr contains a Python traceback:\n{stderr[:2000]}"
        )

    def test_digest_dry_run_emits_situation_monitor_label(
        self, digest_dry_run_stdout: str
    ) -> None:
        assert "Situation Monitor" in digest_dry_run_stdout, (
            "'digest-dry-run' output must contain 'Situation Monitor'"
        )


# ---------------------------------------------------------------------------
# 3. ``once`` stdout: ``#### LEFT`` marker present
# ---------------------------------------------------------------------------


class TestOnceLEFTMarker:
    """``once`` stdout must contain ``#### LEFT`` (dual-lens left column heading)."""

    def test_left_marker_present(self, once_stdout: str) -> None:
        assert "#### LEFT" in once_stdout, (
            "'once' stdout must contain '#### LEFT' dual-lens column marker.\n"
            "This is emitted by _print_dual_lens when both left and right sources\n"
            "provide articles for the same event cluster.\n"
            f"stdout (first 3000 chars):\n{once_stdout[:3000]}"
        )

    def test_left_marker_is_h4_heading(self, once_stdout: str) -> None:
        """``#### LEFT`` must appear as an H4 heading line, not embedded in prose."""
        h4_left = [l for l in once_stdout.splitlines() if l.startswith("#### LEFT")]
        assert h4_left, (
            "No line starting with '#### LEFT' found in 'once' stdout.\n"
            "The marker must appear as a proper H4 heading, not embedded mid-line."
        )

    def test_left_marker_inside_dual_lens_block(self, once_stdout: str) -> None:
        """``#### LEFT`` must appear after the ``## DUAL-LENS EVENTS`` section header."""
        idx = once_stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0, (
            "'once' stdout must contain '## DUAL-LENS EVENTS' section header before '#### LEFT'"
        )
        block_after = once_stdout[idx:]
        assert "#### LEFT" in block_after, (
            "'#### LEFT' must appear inside the '## DUAL-LENS EVENTS' block"
        )

    def test_left_heading_includes_article_count(self, once_stdout: str) -> None:
        """``#### LEFT (N article[s])`` must include an article count."""
        h4_left = [l for l in once_stdout.splitlines() if l.startswith("#### LEFT")]
        assert h4_left, "No '#### LEFT' heading found"
        heading = h4_left[0]
        assert "article" in heading, (
            f"'#### LEFT' heading must include article count; got: {heading!r}"
        )

    def test_left_column_has_bullet(self, once_stdout: str) -> None:
        """At least one ``- ...`` bullet must appear under the LEFT heading."""
        lines = once_stdout.splitlines()
        in_left = False
        for line in lines:
            if line.startswith("#### LEFT"):
                in_left = True
                continue
            if in_left:
                if line.startswith("- "):
                    return
                if line.startswith("#"):
                    break
        pytest.fail(
            "No '- ...' article bullet found under '#### LEFT' heading in 'once' stdout"
        )


# ---------------------------------------------------------------------------
# 4. ``once`` stdout: ``#### RIGHT`` marker present
# ---------------------------------------------------------------------------


class TestOnceRIGHTMarker:
    """``once`` stdout must contain ``#### RIGHT`` (dual-lens right column heading)."""

    def test_right_marker_present(self, once_stdout: str) -> None:
        assert "#### RIGHT" in once_stdout, (
            "'once' stdout must contain '#### RIGHT' dual-lens column marker.\n"
            f"stdout (first 3000 chars):\n{once_stdout[:3000]}"
        )

    def test_right_marker_is_h4_heading(self, once_stdout: str) -> None:
        h4_right = [l for l in once_stdout.splitlines() if l.startswith("#### RIGHT")]
        assert h4_right, (
            "No line starting with '#### RIGHT' found in 'once' stdout.\n"
            "The marker must appear as a proper H4 heading, not embedded mid-line."
        )

    def test_right_marker_inside_dual_lens_block(self, once_stdout: str) -> None:
        idx = once_stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0, (
            "'once' stdout must contain '## DUAL-LENS EVENTS' before '#### RIGHT'"
        )
        block_after = once_stdout[idx:]
        assert "#### RIGHT" in block_after, (
            "'#### RIGHT' must appear inside the '## DUAL-LENS EVENTS' block"
        )

    def test_right_heading_includes_article_count(self, once_stdout: str) -> None:
        h4_right = [l for l in once_stdout.splitlines() if l.startswith("#### RIGHT")]
        assert h4_right, "No '#### RIGHT' heading found"
        heading = h4_right[0]
        assert "article" in heading, (
            f"'#### RIGHT' heading must include article count; got: {heading!r}"
        )

    def test_right_column_has_bullet(self, once_stdout: str) -> None:
        lines = once_stdout.splitlines()
        in_right = False
        for line in lines:
            if line.startswith("#### RIGHT"):
                in_right = True
                continue
            if in_right:
                if line.startswith("- "):
                    return
                if line.startswith("#"):
                    break
        pytest.fail(
            "No '- ...' article bullet found under '#### RIGHT' heading in 'once' stdout"
        )

    def test_both_left_and_right_in_same_dual_lens_block(self, once_stdout: str) -> None:
        """LEFT and RIGHT must co-exist inside the same DUAL-LENS EVENTS block."""
        idx = once_stdout.find("## DUAL-LENS EVENTS")
        assert idx >= 0, "'## DUAL-LENS EVENTS' block not found"
        block = once_stdout[idx:]
        assert "#### LEFT" in block, "'#### LEFT' not found in DUAL-LENS EVENTS block"
        assert "#### RIGHT" in block, "'#### RIGHT' not found in DUAL-LENS EVENTS block"


# ---------------------------------------------------------------------------
# 5. ``once`` stdout: ``spin_pct:`` annotation present
# ---------------------------------------------------------------------------


class TestOnceSpinPct:
    """``once`` stdout must contain ``spin_pct:`` annotation on article bullets."""

    def test_spin_pct_annotation_present(self, once_stdout: str) -> None:
        assert "spin_pct:" in once_stdout, (
            "'once' stdout must contain 'spin_pct:' annotation.\n"
            "This is emitted by _print_dual_lens per article bullet:\n"
            "  '- <title> | spin_pct: N.N%'\n"
            f"stdout sample:\n{once_stdout[:2000]}"
        )

    def test_spin_pct_has_decimal_format(self, once_stdout: str) -> None:
        """spin_pct must be formatted as ``N.N%`` (decimal point required)."""
        matches = re.findall(r"spin_pct:\s*(\d+\.\d+)%", once_stdout)
        assert matches, (
            "No 'spin_pct: N.N%' pattern found in 'once' stdout.\n"
            "Expected format: 'spin_pct: 50.0%' (must include decimal point).\n"
            f"stdout sample:\n{once_stdout[:2000]}"
        )

    def test_spin_pct_values_are_parseable_floats(self, once_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", once_stdout)
        assert matches, "No spin_pct values found in 'once' stdout"
        for raw in matches:
            try:
                float(raw)
            except ValueError:
                pytest.fail(f"spin_pct value {raw!r} is not parseable as a float")

    def test_spin_pct_values_in_valid_range(self, once_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", once_stdout)
        assert matches, "No spin_pct values found"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range"
            )

    def test_spin_pct_appears_on_bullet_lines(self, once_stdout: str) -> None:
        """``spin_pct:`` must appear on ``- ...`` bullet lines, not standalone."""
        spin_bullets = [
            l for l in once_stdout.splitlines()
            if l.startswith("- ") and "spin_pct:" in l
        ]
        assert spin_bullets, (
            "No '- ...' article bullet containing 'spin_pct:' found in 'once' stdout.\n"
            "Expected format: '- <title> | spin_pct: N.N%'"
        )

    def test_spin_pct_present_in_left_column(self, once_stdout: str) -> None:
        """At least one spin_pct bullet must appear under the LEFT heading."""
        lines = once_stdout.splitlines()
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
        pytest.fail(
            "No spin_pct annotation found in LEFT column of 'once' stdout"
        )

    def test_spin_pct_present_in_right_column(self, once_stdout: str) -> None:
        """At least one spin_pct bullet must appear under the RIGHT heading."""
        lines = once_stdout.splitlines()
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
        pytest.fail(
            "No spin_pct annotation found in RIGHT column of 'once' stdout"
        )

    def test_spin_delta_also_present(self, once_stdout: str) -> None:
        """``spin_delta:`` event annotation must co-occur with spin_pct."""
        matches = re.findall(r"spin_delta:\s*([\d.]+)", once_stdout)
        assert matches, (
            "'once' stdout must also contain 'spin_delta: N.N' event-level annotations"
        )
        for raw in matches:
            assert float(raw) >= 0.0, f"spin_delta must be non-negative; got {raw!r}"


# ---------------------------------------------------------------------------
# 6. Structural isolation: the two subprocess calls are truly independent
# ---------------------------------------------------------------------------


class TestSubprocessIsolation:
    """Confirm the two commands were invoked as separate, isolated subprocesses.

    These tests verify structural properties of the test design itself so that
    a reviewer can see that once-failure cannot bleed into digest-dry-run's
    returncode.
    """

    def test_once_and_digest_are_separate_fixtures(
        self,
        once_result: subprocess.CompletedProcess,
        digest_dry_run_result: subprocess.CompletedProcess,
    ) -> None:
        """The two CompletedProcess objects must be distinct — different subprocess runs."""
        assert once_result is not digest_dry_run_result, (
            "once_result and digest_dry_run_result must be different subprocess objects"
        )

    def test_once_uses_sys_executable(
        self, once_result: subprocess.CompletedProcess
    ) -> None:
        """The 'once' command must have been invoked via sys.executable, not a shell string."""
        # The args list on the completed process starts with sys.executable
        args = once_result.args
        assert isinstance(args, list), (
            "'once' must be launched as an args list (subprocess.run([...]))"
            f", got args type: {type(args)}"
        )
        assert args[0] == sys.executable, (
            f"'once' args[0] must be sys.executable ({sys.executable!r}); "
            f"got {args[0]!r}"
        )

    def test_digest_dry_run_uses_sys_executable(
        self, digest_dry_run_result: subprocess.CompletedProcess
    ) -> None:
        args = digest_dry_run_result.args
        assert isinstance(args, list), (
            "'digest-dry-run' must be launched as an args list"
        )
        assert args[0] == sys.executable, (
            f"'digest-dry-run' args[0] must be sys.executable ({sys.executable!r}); "
            f"got {args[0]!r}"
        )

    def test_once_args_contain_once_subcommand(
        self, once_result: subprocess.CompletedProcess
    ) -> None:
        assert "once" in once_result.args, (
            f"'once' subprocess args must contain 'once' subcommand; got {once_result.args!r}"
        )

    def test_digest_dry_run_args_contain_digest_subcommand(
        self, digest_dry_run_result: subprocess.CompletedProcess
    ) -> None:
        assert "digest-dry-run" in digest_dry_run_result.args, (
            f"'digest-dry-run' subprocess args must contain 'digest-dry-run'; "
            f"got {digest_dry_run_result.args!r}"
        )

    def test_once_returncode_independent_of_digest(
        self,
        once_result: subprocess.CompletedProcess,
        digest_dry_run_result: subprocess.CompletedProcess,
    ) -> None:
        """Both returncodes are accessible independently — no last-wins masking."""
        # Both must be inspectable individually; this assertion simply exercises the
        # property that neither result shadows the other.
        assert isinstance(once_result.returncode, int), (
            "once_result.returncode must be an integer"
        )
        assert isinstance(digest_dry_run_result.returncode, int), (
            "digest_dry_run_result.returncode must be an integer"
        )
        # If once failed, this test would expose it regardless of digest-dry-run's status.
        assert once_result.returncode == 0, (
            f"once returncode={once_result.returncode} (digest-dry-run="
            f"{digest_dry_run_result.returncode}): once failure is independently visible"
        )
        assert digest_dry_run_result.returncode == 0, (
            f"digest-dry-run returncode={digest_dry_run_result.returncode} "
            f"(once={once_result.returncode}): digest failure is independently visible"
        )

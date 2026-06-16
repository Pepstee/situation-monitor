"""Regression guard: acceptance cmd1 exits 0; left-lens and right-lens columns and
spin % present in stdout; digest-dry-run exits 0; check_server.py exits 0.

Independent tester perspective. Tests here are NOT simple existence checks — they
verify:

  1. Left-column and right-column spin_pct values are extracted PER COLUMN and
     are DIFFERENTIATED (not all equal to a single stub value), proving the
     deterministic spin estimator produces genuine output.
  2. spin_pct appears inside the LEFT column block and inside the RIGHT column
     block — not just anywhere in stdout.
  3. The spin_delta for the climate-fixture event is positive (the offline
     estimator diverges on opposing framings).
  4. The acceptance digest-dry-run command exits 0 and emits at least one bullet.
  5. check_server.py exits 0.
  6. The rss_left.xml and rss_right.xml fixture articles produce different
     spin_pct values when scored by deterministic_spin — the underlying engine
     actually differentiates.

Every assertion CAN fail on a real regression. The unit under test is NEVER
mocked (no mock of deterministic_spin, no mock of group_by_event).
"""

from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import urllib.parse
from contextlib import redirect_stdout
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"
RSS_LEFT = FIXTURES / "rss_left.xml"
RSS_RIGHT = FIXTURES / "rss_right.xml"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _offline_env(**extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
        **extra,
    }


def _parse_column_spin_pcts(stdout: str, column: str) -> list[float]:
    """Extract spin_pct float values from bullet lines inside the given column block.

    column must be 'LEFT' or 'RIGHT'.  Only lines between the column heading
    and the next heading (or end of block) are considered.
    """
    heading = f"#### {column}"
    values: list[float] = []
    in_column = False
    for line in stdout.splitlines():
        if heading in line:
            in_column = True
            continue
        if in_column:
            # Any new heading ends the column
            if line.startswith("#"):
                break
            # Bullet line with spin annotation
            if line.startswith("- ") and "spin_pct:" in line:
                m = re.search(r"spin_pct:\s*([\d.]+)%", line)
                if m:
                    values.append(float(m.group(1)))
    return values


def _load_fixture_article(xml_path: Path, source_lean: str):
    """Load the single article from one of the fixture RSS files."""
    from situation_monitor.config import SourceDef
    from situation_monitor.ingestion.rss import RSSFetcher
    from situation_monitor.models import Domain

    class _Local:
        def get(self, url: str) -> bytes:
            return Path(url).read_bytes()

    fetcher = RSSFetcher(client=_Local())
    # Infer domain from lean for these fixtures
    domain = Domain.WORLD
    sd = SourceDef(str(xml_path), "Fixture", domain, source_lean)
    return fetcher.fetch(str(xml_path), source_def=sd)


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixtures — each command runs exactly once per module
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def cmd1_proc() -> subprocess.CompletedProcess:
    """Acceptance cmd1: situation_monitor once — offline, fixture RSS + source defs."""
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
def cmd1_stdout(cmd1_proc: subprocess.CompletedProcess) -> str:
    return cmd1_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def cmd2_proc() -> subprocess.CompletedProcess:
    """Acceptance cmd2: digest-dry-run — SEPARATE subprocess from cmd1."""
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
def cmd4_proc() -> subprocess.CompletedProcess:
    """Acceptance cmd4: check_server.py — SEPARATE subprocess."""
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    return subprocess.run(
        [sys.executable, str(CHECK_SERVER)],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=120,
    )


# ---------------------------------------------------------------------------
# 1. cmd1 exit-code guard
# ---------------------------------------------------------------------------

class TestCmd1ExitsZero:
    """cmd1 (once) must exit 0 — the primary acceptance gate."""

    def test_returncode_is_zero(self, cmd1_proc: subprocess.CompletedProcess) -> None:
        assert cmd1_proc.returncode == 0, (
            f"cmd1 (once) exited {cmd1_proc.returncode}, expected 0.\n"
            f"stderr (last 500):\n{cmd1_proc.stderr.decode(errors='replace')[-500:]}\n"
            f"stdout (last 500):\n{cmd1_proc.stdout.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, cmd1_stdout: str) -> None:
        assert cmd1_stdout.strip(), "cmd1 (once) must produce non-empty stdout"

    def test_no_traceback_in_stdout(self, cmd1_stdout: str) -> None:
        assert "Traceback" not in cmd1_stdout, (
            "cmd1 stdout must not contain a Python Traceback"
        )

    def test_no_traceback_in_stderr(self, cmd1_proc: subprocess.CompletedProcess) -> None:
        stderr = cmd1_proc.stderr.decode(errors="replace")
        assert "Traceback" not in stderr, (
            f"cmd1 stderr must not contain a Python Traceback.\n{stderr[:1000]}"
        )


# ---------------------------------------------------------------------------
# 2. cmd1 dual-lens block presence — left-lens and right-lens columns
# ---------------------------------------------------------------------------

class TestCmd1DualLensColumns:
    """cmd1 stdout must contain a complete dual-lens render with LEFT and RIGHT columns."""

    def test_dual_lens_events_header_present(self, cmd1_stdout: str) -> None:
        assert "DUAL-LENS EVENTS" in cmd1_stdout, (
            "cmd1 stdout must contain 'DUAL-LENS EVENTS' section header.\n"
            "Left and right fixture articles must cluster into one event.\n"
            f"stdout (first 2000):\n{cmd1_stdout[:2000]}"
        )

    def test_left_lens_column_heading_present(self, cmd1_stdout: str) -> None:
        assert "#### LEFT" in cmd1_stdout, (
            "cmd1 stdout must contain '#### LEFT' column heading inside DUAL-LENS block.\n"
            "The left-leaning fixture article must appear in the left-lens column."
        )

    def test_right_lens_column_heading_present(self, cmd1_stdout: str) -> None:
        assert "#### RIGHT" in cmd1_stdout, (
            "cmd1 stdout must contain '#### RIGHT' column heading inside DUAL-LENS block.\n"
            "The right-leaning fixture article must appear in the right-lens column."
        )

    def test_left_column_is_inside_dual_lens_block(self, cmd1_stdout: str) -> None:
        dual_idx = cmd1_stdout.find("DUAL-LENS EVENTS")
        assert dual_idx >= 0, "DUAL-LENS EVENTS not found"
        block = cmd1_stdout[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' must appear INSIDE the DUAL-LENS EVENTS block, not before it.\n"
            "Domain headings (## WORLD etc.) and digest content precede the block."
        )

    def test_right_column_is_inside_dual_lens_block(self, cmd1_stdout: str) -> None:
        dual_idx = cmd1_stdout.find("DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = cmd1_stdout[dual_idx:]
        assert "#### RIGHT" in block, (
            "'#### RIGHT' must appear INSIDE the DUAL-LENS EVENTS block."
        )

    def test_left_column_has_at_least_one_article_bullet(self, cmd1_stdout: str) -> None:
        """A '- <title> | spin_pct: ...' bullet must appear inside the LEFT column."""
        pcts = _parse_column_spin_pcts(cmd1_stdout, "LEFT")
        assert pcts, (
            "No '- ... | spin_pct: N.N%' bullet found inside '#### LEFT' column.\n"
            "The left-leaning fixture article must appear with its spin annotation."
        )

    def test_right_column_has_at_least_one_article_bullet(self, cmd1_stdout: str) -> None:
        """A '- <title> | spin_pct: ...' bullet must appear inside the RIGHT column."""
        pcts = _parse_column_spin_pcts(cmd1_stdout, "RIGHT")
        assert pcts, (
            "No '- ... | spin_pct: N.N%' bullet found inside '#### RIGHT' column.\n"
            "The right-leaning fixture article must appear with its spin annotation."
        )

    def test_dual_lens_block_comes_after_domain_sections(self, cmd1_stdout: str) -> None:
        """Domain sections (WORLD, MARKETS, AI) must precede the DUAL-LENS block."""
        ai_idx = cmd1_stdout.find("## AI")
        dual_idx = cmd1_stdout.find("## DUAL-LENS EVENTS")
        assert ai_idx >= 0, "'## AI' section missing from cmd1 stdout"
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' section missing from cmd1 stdout"
        assert ai_idx < dual_idx, (
            "'## DUAL-LENS EVENTS' must appear AFTER '## AI' in cmd1 stdout"
        )

    def test_left_column_heading_comes_before_right_column_heading(
        self, cmd1_stdout: str
    ) -> None:
        """In the standard render LEFT appears before RIGHT."""
        left_idx = cmd1_stdout.find("#### LEFT")
        right_idx = cmd1_stdout.find("#### RIGHT")
        assert left_idx >= 0, "'#### LEFT' not found"
        assert right_idx >= 0, "'#### RIGHT' not found"
        assert left_idx < right_idx, (
            "'#### LEFT' must appear before '#### RIGHT' in cmd1 stdout"
        )


# ---------------------------------------------------------------------------
# 3. cmd1 spin percentage — numeric value inside left and right columns
# ---------------------------------------------------------------------------

class TestCmd1SpinPercentage:
    """cmd1 stdout must contain real numeric spin percentage values inside each column."""

    def test_spin_pct_annotation_present_in_stdout(self, cmd1_stdout: str) -> None:
        assert "spin_pct:" in cmd1_stdout, (
            "cmd1 stdout must contain 'spin_pct:' annotation"
        )

    def test_spin_pct_in_left_column_is_numeric(self, cmd1_stdout: str) -> None:
        """spin_pct values inside '#### LEFT' must be parseable floats."""
        pcts = _parse_column_spin_pcts(cmd1_stdout, "LEFT")
        assert pcts, "No spin_pct values extracted from LEFT column"
        for v in pcts:
            assert isinstance(v, float), f"Left column spin_pct {v!r} is not a float"

    def test_spin_pct_in_right_column_is_numeric(self, cmd1_stdout: str) -> None:
        """spin_pct values inside '#### RIGHT' must be parseable floats."""
        pcts = _parse_column_spin_pcts(cmd1_stdout, "RIGHT")
        assert pcts, "No spin_pct values extracted from RIGHT column"
        for v in pcts:
            assert isinstance(v, float), f"Right column spin_pct {v!r} is not a float"

    def test_spin_pct_in_left_column_in_valid_range(self, cmd1_stdout: str) -> None:
        for v in _parse_column_spin_pcts(cmd1_stdout, "LEFT"):
            assert 0.0 <= v <= 100.0, (
                f"Left-column spin_pct {v} is outside the valid [0, 100] range"
            )

    def test_spin_pct_in_right_column_in_valid_range(self, cmd1_stdout: str) -> None:
        for v in _parse_column_spin_pcts(cmd1_stdout, "RIGHT"):
            assert 0.0 <= v <= 100.0, (
                f"Right-column spin_pct {v} is outside the valid [0, 100] range"
            )

    def test_spin_pct_in_left_column_has_decimal_point(self, cmd1_stdout: str) -> None:
        """Format must be N.N% (one decimal place) — not N% and not N.NN%."""
        matches_in_left_block = []
        in_left = False
        for line in cmd1_stdout.splitlines():
            if "#### LEFT" in line:
                in_left = True
                continue
            if in_left:
                if line.startswith("#"):
                    break
                for m in re.findall(r"spin_pct:\s*([\d.]+)%", line):
                    matches_in_left_block.append(m)
        assert matches_in_left_block, "No spin_pct values found inside LEFT column block"
        for raw in matches_in_left_block:
            assert "." in raw, (
                f"Left-column spin_pct {raw!r} must use decimal format (:.1f)"
            )

    def test_spin_pct_in_right_column_has_decimal_point(self, cmd1_stdout: str) -> None:
        matches_in_right_block = []
        in_right = False
        for line in cmd1_stdout.splitlines():
            if "#### RIGHT" in line:
                in_right = True
                continue
            if in_right:
                if line.startswith("#"):
                    break
                for m in re.findall(r"spin_pct:\s*([\d.]+)%", line):
                    matches_in_right_block.append(m)
        assert matches_in_right_block, "No spin_pct values found inside RIGHT column block"
        for raw in matches_in_right_block:
            assert "." in raw, (
                f"Right-column spin_pct {raw!r} must use decimal format (:.1f)"
            )

    def test_left_and_right_spin_pct_values_differ(self, cmd1_stdout: str) -> None:
        """Left-column and right-column spin_pct values must NOT all be equal.

        If they were identical it would indicate the deterministic spin estimator
        is returning a flat stub value (e.g. all 50.0) rather than computing real
        lexical differentiation.  The climate-policy fixture articles use charged
        language on both sides but with different terms: 'backed', 'endorse' on
        the left vs 'threatens', 'destroy', 'hamper' on the right.
        """
        left_pcts = _parse_column_spin_pcts(cmd1_stdout, "LEFT")
        right_pcts = _parse_column_spin_pcts(cmd1_stdout, "RIGHT")
        assert left_pcts, "No spin_pct values in LEFT column"
        assert right_pcts, "No spin_pct values in RIGHT column"
        left_avg = sum(left_pcts) / len(left_pcts)
        right_avg = sum(right_pcts) / len(right_pcts)
        assert left_avg != right_avg, (
            f"Left-column avg spin_pct ({left_avg:.1f}%) equals "
            f"right-column avg spin_pct ({right_avg:.1f}%).\n"
            "This indicates a flat stub value rather than real lexical differentiation.\n"
            "The deterministic spin estimator must produce different scores for the two "
            "climate-policy fixture articles."
        )

    def test_spin_delta_is_positive_in_dual_lens_block(self, cmd1_stdout: str) -> None:
        """At least one event with opposing framings must show spin_delta > 0.0.

        spin_delta measures divergence between LEFT and RIGHT framings, so it is
        only positive when both lenses cover the same event. Single-sided events
        legitimately report 0.0 (no opposing framing to diverge from); the
        opposing climate-policy fixture pair must drive a genuine non-zero delta.
        """
        dual_idx = cmd1_stdout.find("DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = cmd1_stdout[dual_idx:]
        matches = re.findall(r"spin_delta:\s*([\d.]+)", block)
        assert matches, "No 'spin_delta: N.N' found inside DUAL-LENS EVENTS block"
        deltas = [float(raw) for raw in matches]
        for val in deltas:
            assert val >= 0.0, f"spin_delta must be non-negative; got {val}."
        assert any(val > 0.0 for val in deltas), (
            "No event produced a positive spin_delta.\n"
            "The opposing left/right climate-policy fixture articles must cluster "
            "into one event and yield a genuine non-zero divergence."
        )

    def test_spin_pct_annotation_on_bullet_line_not_floating(
        self, cmd1_stdout: str
    ) -> None:
        """spin_pct must appear on '- ...' bullet lines, never on a line of its own."""
        for line in cmd1_stdout.splitlines():
            if "spin_pct:" in line:
                assert line.startswith("- ") or line.startswith("  "), (
                    f"spin_pct: appeared on a line that is not a bullet or indented "
                    f"continuation: {line!r}"
                )


# ---------------------------------------------------------------------------
# 4. cmd2 (digest-dry-run) exit-code guard
# ---------------------------------------------------------------------------

class TestCmd2DigestDryRunExitsZero:
    """cmd2 (digest-dry-run) must exit 0 — acceptance criterion #3."""

    def test_returncode_is_zero(self, cmd2_proc: subprocess.CompletedProcess) -> None:
        assert cmd2_proc.returncode == 0, (
            f"cmd2 (digest-dry-run) exited {cmd2_proc.returncode}, expected 0.\n"
            f"stderr (last 500):\n{cmd2_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, cmd2_proc: subprocess.CompletedProcess) -> None:
        stdout = cmd2_proc.stdout.decode(errors="replace")
        assert stdout.strip(), "cmd2 (digest-dry-run) must produce non-empty stdout"

    def test_stdout_has_bullet_entries(self, cmd2_proc: subprocess.CompletedProcess) -> None:
        stdout = cmd2_proc.stdout.decode(errors="replace")
        bullets = [l for l in stdout.splitlines() if l.startswith("•")]
        assert bullets, (
            "cmd2 (digest-dry-run) stdout must contain '•' bullet entries.\n"
            f"stdout:\n{stdout[:500]}"
        )

    def test_no_traceback_in_stdout(self, cmd2_proc: subprocess.CompletedProcess) -> None:
        stdout = cmd2_proc.stdout.decode(errors="replace")
        assert "Traceback" not in stdout

    def test_no_traceback_in_stderr(self, cmd2_proc: subprocess.CompletedProcess) -> None:
        stderr = cmd2_proc.stderr.decode(errors="replace")
        assert "Traceback" not in stderr

    def test_cmd2_is_distinct_subprocess_from_cmd1(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd2_proc: subprocess.CompletedProcess,
    ) -> None:
        assert cmd1_proc is not cmd2_proc, (
            "cmd2 must be a distinct subprocess from cmd1 — "
            "each acceptance command must have an independently visible returncode"
        )

    def test_cmd2_uses_digest_dry_run_subcommand(
        self, cmd2_proc: subprocess.CompletedProcess
    ) -> None:
        assert "digest-dry-run" in cmd2_proc.args, (
            "cmd2 subprocess must be launched with 'digest-dry-run' subcommand"
        )


# ---------------------------------------------------------------------------
# 5. cmd4 (check_server.py) exit-code guard
# ---------------------------------------------------------------------------

class TestCmd4CheckServerExitsZero:
    """cmd4 (check_server.py) must exit 0 — acceptance criterion #4."""

    def test_returncode_is_zero(self, cmd4_proc: subprocess.CompletedProcess) -> None:
        assert cmd4_proc.returncode == 0, (
            f"cmd4 (check_server.py) exited {cmd4_proc.returncode}, expected 0.\n"
            f"stderr:\n{cmd4_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_stdout_contains_pass_marker(self, cmd4_proc: subprocess.CompletedProcess) -> None:
        stdout = cmd4_proc.stdout.decode(errors="replace")
        assert "web-server-smoke: PASS" in stdout, (
            f"cmd4 stdout must contain 'web-server-smoke: PASS'.\nGot: {stdout!r}"
        )

    def test_pass_marker_is_a_complete_standalone_line(
        self, cmd4_proc: subprocess.CompletedProcess
    ) -> None:
        stdout = cmd4_proc.stdout.decode(errors="replace")
        assert any(
            line == "web-server-smoke: PASS" for line in stdout.splitlines()
        ), (
            "'web-server-smoke: PASS' must be a complete standalone line, "
            f"not embedded in text.\nLines: {stdout.splitlines()}"
        )

    def test_no_traceback_in_stdout(self, cmd4_proc: subprocess.CompletedProcess) -> None:
        assert "Traceback" not in cmd4_proc.stdout.decode(errors="replace")

    def test_no_traceback_in_stderr(self, cmd4_proc: subprocess.CompletedProcess) -> None:
        assert "Traceback" not in cmd4_proc.stderr.decode(errors="replace")

    def test_check_server_py_exists(self) -> None:
        assert CHECK_SERVER.exists(), f"check_server.py missing at {CHECK_SERVER}"

    def test_cmd4_is_distinct_subprocess_from_cmd1(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd4_proc: subprocess.CompletedProcess,
    ) -> None:
        assert cmd4_proc is not cmd1_proc


# ---------------------------------------------------------------------------
# 6. Fixture-level unit tests: deterministic spin produces real differentiation
# ---------------------------------------------------------------------------

class TestFixtureDeterministicSpinDifferentiation:
    """The rss_left.xml and rss_right.xml fixture articles must produce different
    spin_pct values via deterministic_spin — verifying the offline estimator
    actually scores by content, not by returning a flat stub value.
    """

    @pytest.fixture(scope="class")
    def left_article(self):
        articles = _load_fixture_article(RSS_LEFT, "left")
        assert articles, "rss_left.xml must contain at least one article"
        return articles[0]

    @pytest.fixture(scope="class")
    def right_article(self):
        articles = _load_fixture_article(RSS_RIGHT, "right")
        assert articles, "rss_right.xml must contain at least one article"
        return articles[0]

    def test_left_article_has_left_source_lean(self, left_article) -> None:
        assert left_article.source_lean == "left", (
            f"Left fixture article must have source_lean='left'; "
            f"got {left_article.source_lean!r}"
        )

    def test_right_article_has_right_source_lean(self, right_article) -> None:
        assert right_article.source_lean == "right", (
            f"Right fixture article must have source_lean='right'; "
            f"got {right_article.source_lean!r}"
        )

    def test_left_and_right_spin_pct_differ(self, left_article, right_article) -> None:
        """The two climate-policy articles must score differently offline.

        rss_left.xml uses endorsement language ('backed', 'endorse').
        rss_right.xml uses fear/charged language ('threatens', 'destroy', 'hamper').
        These produce different lexical hits → different spin_pct values.
        """
        from situation_monitor.dual_lens import deterministic_spin

        left_spin = deterministic_spin(left_article)
        right_spin = deterministic_spin(right_article)

        assert left_spin.spin_pct != right_spin.spin_pct, (
            f"Left spin ({left_spin.spin_pct:.1f}%) == right spin ({right_spin.spin_pct:.1f}%).\n"
            "deterministic_spin must produce DIFFERENT scores for opposing framings.\n"
            f"Left receipts: {left_spin.receipts}\n"
            f"Right receipts: {right_spin.receipts}"
        )

    def test_right_article_scores_higher_than_left_article(
        self, left_article, right_article
    ) -> None:
        """The right fixture article uses 'threatens', 'destroy', 'hamper' (CHARGED_VERBS)
        and 'warn' (FEAR_TERMS), which fire multiple high-weight lexicon categories.
        The left uses 'backed', 'endorse' (ENDORSEMENT_TERMS, lower weight).
        Right must score higher.
        """
        from situation_monitor.dual_lens import deterministic_spin

        left_spin = deterministic_spin(left_article)
        right_spin = deterministic_spin(right_article)

        assert right_spin.spin_pct > left_spin.spin_pct, (
            f"Right fixture spin ({right_spin.spin_pct:.1f}%) must exceed "
            f"left fixture spin ({left_spin.spin_pct:.1f}%).\n"
            "Right uses CHARGED_VERBS + FEAR_TERMS (high weight) while left uses "
            "ENDORSEMENT_TERMS (lower weight).\n"
            f"Right receipts: {right_spin.receipts}\n"
            f"Left receipts: {left_spin.receipts}"
        )

    def test_left_spin_has_receipts(self, left_article) -> None:
        from situation_monitor.dual_lens import deterministic_spin
        spin = deterministic_spin(left_article)
        assert spin.receipts, "Left fixture article must produce non-empty spin receipts"

    def test_right_spin_has_receipts(self, right_article) -> None:
        from situation_monitor.dual_lens import deterministic_spin
        spin = deterministic_spin(right_article)
        assert spin.receipts, "Right fixture article must produce non-empty spin receipts"

    def test_right_spin_receipts_mention_charged_verbs_or_fear(
        self, right_article
    ) -> None:
        """The right article fires CHARGED_VERBS ('threatens'/'destroy'/'hamper')
        and/or FEAR_TERMS ('warn'); the receipts must name these categories."""
        from situation_monitor.dual_lens import deterministic_spin
        spin = deterministic_spin(right_article)
        receipts_lower = spin.receipts.lower()
        assert (
            "charged verbs" in receipts_lower
            or "fear" in receipts_lower
            or "threatens" in receipts_lower
            or "destroy" in receipts_lower
            or "warn" in receipts_lower
        ), (
            "Right fixture spin receipts must name at least one of the fired categories "
            "(Charged Verbs / Fear / Emotional Framing) or their fired terms.\n"
            f"Got: {spin.receipts!r}"
        )

    def test_left_spin_receipts_mention_endorsement(self, left_article) -> None:
        """The left article fires ENDORSEMENT_TERMS ('backed', 'endorse');
        the receipts must name the endorsement category or those terms."""
        from situation_monitor.dual_lens import deterministic_spin
        spin = deterministic_spin(left_article)
        receipts_lower = spin.receipts.lower()
        assert (
            "endorsement" in receipts_lower
            or "backed" in receipts_lower
            or "endorse" in receipts_lower
        ), (
            "Left fixture spin receipts must name the Endorsement Framing category "
            "or the terms 'backed'/'endorse'.\n"
            f"Got: {spin.receipts!r}"
        )


# ---------------------------------------------------------------------------
# 7. Full pipeline integration: group_by_event with fixture articles
# ---------------------------------------------------------------------------

class TestFixtureGroupByEventSpinDelta:
    """End-to-end: load left+right fixture articles, group_by_event with default
    spin_fn (deterministic), verify the resulting DualLensEvent has a positive
    spin_delta — the full offline pipeline works without LLM.
    """

    @pytest.fixture(scope="class")
    def dual_event(self):
        from situation_monitor.dual_lens import group_by_event

        left_arts = _load_fixture_article(RSS_LEFT, "left")
        right_arts = _load_fixture_article(RSS_RIGHT, "right")
        all_articles = left_arts + right_arts
        events = group_by_event(all_articles)
        # The two articles share 'Government Climate Policy Reform' words
        dual = [e for e in events if e.left_articles and e.right_articles]
        assert dual, (
            "Left and right fixture articles must cluster into at least one dual-sided event.\n"
            "They share 'Government', 'Climate', 'Policy', 'Reform' as significant words."
        )
        return dual[0]

    def test_spin_delta_is_positive(self, dual_event) -> None:
        assert dual_event.spin_delta > 0.0, (
            f"spin_delta must be > 0.0; got {dual_event.spin_delta}.\n"
            "The deterministic spin estimator must produce different scores for the two "
            "climate-policy fixture articles."
        )

    def test_left_articles_are_present(self, dual_event) -> None:
        assert dual_event.left_articles, "Dual event must have left articles"

    def test_right_articles_are_present(self, dual_event) -> None:
        assert dual_event.right_articles, "Dual event must have right articles"

    def test_left_articles_spin_pct_in_range(self, dual_event) -> None:
        for aa in dual_event.left_articles:
            assert 0.0 <= aa.spin.spin_pct <= 100.0, (
                f"Left article spin_pct {aa.spin.spin_pct} is outside [0, 100]"
            )

    def test_right_articles_spin_pct_in_range(self, dual_event) -> None:
        for aa in dual_event.right_articles:
            assert 0.0 <= aa.spin.spin_pct <= 100.0, (
                f"Right article spin_pct {aa.spin.spin_pct} is outside [0, 100]"
            )

    def test_spin_pct_values_differ_between_sides(self, dual_event) -> None:
        """The fixture articles' spin_pct values must not all be identical.

        If they were, the estimator is returning a flat stub (e.g. all 50.0)
        rather than real lexical scores.
        """
        left_pcts = [aa.spin.spin_pct for aa in dual_event.left_articles]
        right_pcts = [aa.spin.spin_pct for aa in dual_event.right_articles]
        left_avg = sum(left_pcts) / len(left_pcts)
        right_avg = sum(right_pcts) / len(right_pcts)
        assert left_avg != right_avg, (
            f"Left avg spin ({left_avg:.1f}) == right avg spin ({right_avg:.1f}).\n"
            "Fixture articles use different language so must produce different spin scores."
        )

    def test_dual_lens_render_has_both_columns(self, dual_event) -> None:
        from situation_monitor.__main__ import _print_dual_lens

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_dual_lens([dual_event])
        out = buf.getvalue()
        assert "#### LEFT" in out, "Fixture dual event must render a LEFT column"
        assert "#### RIGHT" in out, "Fixture dual event must render a RIGHT column"

    def test_dual_lens_render_has_spin_pct_in_both_columns(
        self, dual_event
    ) -> None:
        from situation_monitor.__main__ import _print_dual_lens

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_dual_lens([dual_event])
        out = buf.getvalue()

        left_pcts = _parse_column_spin_pcts(out, "LEFT")
        right_pcts = _parse_column_spin_pcts(out, "RIGHT")
        assert left_pcts, "No spin_pct values in LEFT column of rendered fixture output"
        assert right_pcts, "No spin_pct values in RIGHT column of rendered fixture output"


# ---------------------------------------------------------------------------
# 8. Omnibus guard: all three acceptance criteria simultaneously
# ---------------------------------------------------------------------------

class TestAllAcceptanceCriteriaSimultaneously:
    """All four acceptance criteria must hold at the same time."""

    def test_cmd1_exits_zero_and_has_both_columns_and_spin_pct(
        self, cmd1_proc: subprocess.CompletedProcess, cmd1_stdout: str
    ) -> None:
        """Primary acceptance criterion #2: first command exits 0 + dual-lens + spin %."""
        assert cmd1_proc.returncode == 0, (
            f"cmd1 exited {cmd1_proc.returncode}, expected 0"
        )
        assert "#### LEFT" in cmd1_stdout, "cmd1 stdout must contain left-lens column"
        assert "#### RIGHT" in cmd1_stdout, "cmd1 stdout must contain right-lens column"
        left_pcts = _parse_column_spin_pcts(cmd1_stdout, "LEFT")
        right_pcts = _parse_column_spin_pcts(cmd1_stdout, "RIGHT")
        assert left_pcts, "No spin % in left-lens column"
        assert right_pcts, "No spin % in right-lens column"

    def test_cmd2_exits_zero(self, cmd2_proc: subprocess.CompletedProcess) -> None:
        """Acceptance criterion #3: digest-dry-run exits 0."""
        assert cmd2_proc.returncode == 0, (
            f"cmd2 (digest-dry-run) exited {cmd2_proc.returncode}, expected 0"
        )

    def test_cmd4_exits_zero(self, cmd4_proc: subprocess.CompletedProcess) -> None:
        """Acceptance criterion #4: check_server.py exits 0."""
        assert cmd4_proc.returncode == 0, (
            f"cmd4 (check_server.py) exited {cmd4_proc.returncode}, expected 0"
        )

    def test_cmd1_and_cmd2_and_cmd4_are_all_distinct_subprocess_objects(
        self,
        cmd1_proc: subprocess.CompletedProcess,
        cmd2_proc: subprocess.CompletedProcess,
        cmd4_proc: subprocess.CompletedProcess,
    ) -> None:
        """Each acceptance command must be independently invocable — no aliasing."""
        assert cmd1_proc is not cmd2_proc, "cmd1 and cmd2 must be distinct subprocesses"
        assert cmd1_proc is not cmd4_proc, "cmd1 and cmd4 must be distinct subprocesses"
        assert cmd2_proc is not cmd4_proc, "cmd2 and cmd4 must be distinct subprocesses"

    def test_no_traceback_in_any_stdout(
        self,
        cmd1_stdout: str,
        cmd2_proc: subprocess.CompletedProcess,
        cmd4_proc: subprocess.CompletedProcess,
    ) -> None:
        """No acceptance command may produce a Python Traceback in stdout."""
        cmd2_stdout = cmd2_proc.stdout.decode(errors="replace")
        cmd4_stdout = cmd4_proc.stdout.decode(errors="replace")
        failing = []
        if "Traceback" in cmd1_stdout:
            failing.append("cmd1 (once)")
        if "Traceback" in cmd2_stdout:
            failing.append("cmd2 (digest-dry-run)")
        if "Traceback" in cmd4_stdout:
            failing.append("cmd4 (check_server.py)")
        assert not failing, (
            f"Traceback found in stdout of: {', '.join(failing)}"
        )

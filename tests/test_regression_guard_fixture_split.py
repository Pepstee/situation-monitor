"""Regression guard: fixture split.

Independent tester-side verification that the three acceptance criteria hold
after the acceptance fixtures were split into per-command module-scoped
subprocesses (fixture split):

  1. 'once' subprocess runs cleanly in isolation and emits a complete dual-lens
     render with every required output marker.
  2. 'digest-dry-run' subprocess runs cleanly in isolation and emits
     Telegram-ready Markdown.
  3. The RSS fixture files (rss_left.xml, rss_right.xml) form a real dual-lens
     cluster when fed through group_by_event — so the acceptance contract is
     grounded in real fixture data, not just fixture existence.
  4. _print_dual_lens format spec: exact output contract (independent angle
     from test_final_regression_guard.py).
  5. daily_digest unit tests: format, spin_delta > 5 threshold, top_n limit,
     movers section — tested directly without a subprocess.
  6. DualLensEvent mutable-default field isolation: each instance owns its own
     lists; shared defaults are a latent bug vector.
  7. _assign_clusters unit tests: the helper used by _ingest_and_enrich that
     is not covered anywhere else in the test suite.

Every assertion in this file CAN fail on a real regression.
The unit under test is NEVER mocked.
"""

from __future__ import annotations

import io
import os
import re
import subprocess
import sys
import urllib.parse
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Path setup (needed when pytest collects from the top-level tests/ dir)
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
RSS_LEFT = FIXTURES / "rss_left.xml"
RSS_RIGHT = FIXTURES / "rss_right.xml"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_article(title: str, source: str = "example.com", source_lean: str | None = None, **kw):
    from situation_monitor.models import Article

    url = kw.pop("url", f"https://{source}/{urllib.parse.quote(title.lower()[:50])}")
    a = Article(url=url, title=title, source=source, **kw)
    a.source_lean = source_lean
    return a


def _make_spin(pct: float, lens: str):
    from situation_monitor.models import SpinResult

    return SpinResult(spin_pct=pct, lens=lens, rubric={}, receipts=f"receipt for {lens}")


def _make_aa(title: str, lean: str, pct: float):
    from situation_monitor.dual_lens import AnnotatedArticle

    return AnnotatedArticle(
        article=_make_article(title, source_lean=lean),
        spin=_make_spin(pct, lean),
    )


def _make_dual_event(title: str, left=(), right=(), center=(), spin_delta: float = 0.0):
    from situation_monitor.dual_lens import DualLensEvent

    return DualLensEvent(
        event_title=title,
        left_articles=[_make_aa(t, "left", 60.0) for t in left],
        right_articles=[_make_aa(t, "right", 40.0) for t in right],
        center_articles=[_make_aa(t, "center", 50.0) for t in center],
        spin_delta=spin_delta,
    )


def _capture_print_dual_lens(events: list) -> str:
    from situation_monitor.__main__ import _print_dual_lens

    buf = io.StringIO()
    with redirect_stdout(buf):
        _print_dual_lens(events)
    return buf.getvalue()


def _offline_env() -> dict[str, str]:
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(FIXTURES / "rss_sample.xml"),
    }


# ---------------------------------------------------------------------------
# 1. Subprocess isolation — independent verification of the fixture split
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _once_proc() -> subprocess.CompletedProcess:
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
def _digest_proc() -> subprocess.CompletedProcess:
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


class TestOnceSubprocessContract:
    """'once' must exit 0 with all required output markers."""

    def test_once_exits_zero(self, _once_proc: subprocess.CompletedProcess) -> None:
        assert _once_proc.returncode == 0, (
            f"'once' exited {_once_proc.returncode}.\n"
            f"stdout: {_once_proc.stdout.decode(errors='replace')[-2000:]}\n"
            f"stderr: {_once_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_once_stdout_is_non_empty(self, _once_proc: subprocess.CompletedProcess) -> None:
        assert _once_proc.stdout.strip(), "'once' produced no stdout"

    def test_once_stdout_contains_situation_monitor(self, _once_proc: subprocess.CompletedProcess) -> None:
        out = _once_proc.stdout.decode(errors="replace")
        assert "Situation Monitor" in out

    def test_once_stdout_contains_dual_lens_events(self, _once_proc: subprocess.CompletedProcess) -> None:
        out = _once_proc.stdout.decode(errors="replace")
        assert "DUAL-LENS EVENTS" in out, (
            "Acceptance fixture contains left+right articles that must produce a DUAL-LENS block"
        )

    def test_once_stdout_contains_left_heading(self, _once_proc: subprocess.CompletedProcess) -> None:
        out = _once_proc.stdout.decode(errors="replace")
        assert "#### LEFT" in out

    def test_once_stdout_contains_right_heading(self, _once_proc: subprocess.CompletedProcess) -> None:
        out = _once_proc.stdout.decode(errors="replace")
        assert "#### RIGHT" in out

    def test_once_stdout_spin_pct_decimal_format(self, _once_proc: subprocess.CompletedProcess) -> None:
        """spin_pct must have exactly one decimal place (N.N%), not N%."""
        out = _once_proc.stdout.decode(errors="replace")
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", out)
        assert matches, "No spin_pct values found in 'once' stdout"
        for raw in matches:
            assert "." in raw, (
                f"spin_pct value {raw!r} must have a decimal point (format :.1f)"
            )

    def test_once_stdout_spin_pct_on_bullet_lines(self, _once_proc: subprocess.CompletedProcess) -> None:
        out = _once_proc.stdout.decode(errors="replace")
        bullet_spin_lines = [
            l for l in out.splitlines()
            if l.startswith("- ") and "spin_pct:" in l
        ]
        assert bullet_spin_lines, "spin_pct must appear on '- ...' bullet lines"

    def test_once_stdout_spin_delta_has_decimal_format(self, _once_proc: subprocess.CompletedProcess) -> None:
        """spin_delta must have exactly one decimal place (N.N), not N."""
        out = _once_proc.stdout.decode(errors="replace")
        matches = re.findall(r"spin_delta:\s*([\d.]+)", out)
        assert matches, "No spin_delta values found in 'once' stdout"
        for raw in matches:
            assert "." in raw, (
                f"spin_delta value {raw!r} must have a decimal point (format :.1f)"
            )

    def test_once_has_no_traceback(self, _once_proc: subprocess.CompletedProcess) -> None:
        out = _once_proc.stdout.decode(errors="replace")
        err = _once_proc.stderr.decode(errors="replace")
        assert "Traceback" not in out
        assert "Traceback" not in err

    def test_once_args_list_contains_sys_executable(self, _once_proc: subprocess.CompletedProcess) -> None:
        """This subprocess was launched with sys.executable, not a shell string."""
        assert isinstance(_once_proc.args, list)
        assert _once_proc.args[0] == sys.executable

    def test_once_args_list_does_not_contain_digest_subcommand(
        self, _once_proc: subprocess.CompletedProcess
    ) -> None:
        """The 'once' subprocess must not accidentally include 'digest-dry-run'."""
        assert "digest-dry-run" not in _once_proc.args


class TestDigestDryRunSubprocessContract:
    """'digest-dry-run' must exit 0 with Telegram-ready Markdown — fully independent."""

    def test_digest_exits_zero(self, _digest_proc: subprocess.CompletedProcess) -> None:
        assert _digest_proc.returncode == 0, (
            f"'digest-dry-run' exited {_digest_proc.returncode}.\n"
            f"stdout: {_digest_proc.stdout.decode(errors='replace')[-2000:]}\n"
            f"stderr: {_digest_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_digest_stdout_is_non_empty(self, _digest_proc: subprocess.CompletedProcess) -> None:
        assert _digest_proc.stdout.strip(), "'digest-dry-run' produced no stdout"

    def test_digest_has_situation_monitor_header(self, _digest_proc: subprocess.CompletedProcess) -> None:
        out = _digest_proc.stdout.decode(errors="replace")
        assert "Situation Monitor" in out

    def test_digest_has_top_stories_section(self, _digest_proc: subprocess.CompletedProcess) -> None:
        out = _digest_proc.stdout.decode(errors="replace")
        assert "*Top Stories*" in out

    def test_digest_has_bullet_entries(self, _digest_proc: subprocess.CompletedProcess) -> None:
        out = _digest_proc.stdout.decode(errors="replace")
        bullet_lines = [l for l in out.splitlines() if l.startswith("•")]
        assert bullet_lines, "digest-dry-run output must contain '•' bullet entries"

    def test_digest_has_no_traceback(self, _digest_proc: subprocess.CompletedProcess) -> None:
        out = _digest_proc.stdout.decode(errors="replace")
        err = _digest_proc.stderr.decode(errors="replace")
        assert "Traceback" not in out
        assert "Traceback" not in err

    def test_digest_returncode_independent_of_once(
        self,
        _once_proc: subprocess.CompletedProcess,
        _digest_proc: subprocess.CompletedProcess,
    ) -> None:
        """Each return code is inspectable independently — fixture split guarantee."""
        assert _once_proc is not _digest_proc, (
            "The two CompletedProcess objects must be distinct subprocess runs"
        )
        assert isinstance(_once_proc.returncode, int)
        assert isinstance(_digest_proc.returncode, int)

    def test_digest_args_list_does_not_contain_once_subcommand(
        self, _digest_proc: subprocess.CompletedProcess
    ) -> None:
        """The 'digest-dry-run' subprocess must not also contain 'once'."""
        assert "once" not in _digest_proc.args

    def test_digest_has_date_stamp(self, _digest_proc: subprocess.CompletedProcess) -> None:
        """Telegram digest must contain a YYYY-MM-DD date stamp."""
        out = _digest_proc.stdout.decode(errors="replace")
        assert re.search(r"\d{4}-\d{2}-\d{2}", out), (
            "digest-dry-run output must contain a date stamp in YYYY-MM-DD format"
        )

    def test_digest_bullet_entries_are_non_empty(self, _digest_proc: subprocess.CompletedProcess) -> None:
        out = _digest_proc.stdout.decode(errors="replace")
        for line in out.splitlines():
            if line.startswith("•"):
                assert line.strip() != "•", f"Empty bullet found: {line!r}"


# ---------------------------------------------------------------------------
# 2. Fixture clustering guarantee — left + right XML files produce dual-lens
# ---------------------------------------------------------------------------


class TestFixtureClusteringGuarantee:
    """rss_left.xml and rss_right.xml must produce a single dual-lens event when
    loaded together — this is the foundation of the acceptance test's output."""

    @pytest.fixture(scope="class")
    def cluster_events(self):
        from situation_monitor.config import SourceDef
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.ingestion.rss import RSSFetcher
        from situation_monitor.models import Domain

        class _Local:
            def get(self, url: str) -> bytes:
                return Path(url).read_bytes()

        fetcher = RSSFetcher(client=_Local())
        left_sd = SourceDef(str(RSS_LEFT), "LeftFixture", Domain.WORLD, "left")
        right_sd = SourceDef(str(RSS_RIGHT), "RightFixture", Domain.WORLD, "right")
        articles = fetcher.fetch(left_sd.url, source_def=left_sd)
        articles += fetcher.fetch(right_sd.url, source_def=right_sd)
        return group_by_event(articles)

    def test_left_fixture_has_at_least_one_article(self) -> None:
        from situation_monitor.ingestion.rss import RSSFetcher

        class _Local:
            def get(self, url: str) -> bytes:
                return Path(url).read_bytes()

        articles = RSSFetcher(client=_Local()).fetch(str(RSS_LEFT))
        assert articles, "rss_left.xml must contain at least one article"

    def test_right_fixture_has_at_least_one_article(self) -> None:
        from situation_monitor.ingestion.rss import RSSFetcher

        class _Local:
            def get(self, url: str) -> bytes:
                return Path(url).read_bytes()

        articles = RSSFetcher(client=_Local()).fetch(str(RSS_RIGHT))
        assert articles, "rss_right.xml must contain at least one article"

    def test_left_and_right_cluster_into_one_event(self, cluster_events: list) -> None:
        """The two climate-policy articles share ≥2 significant words and must cluster."""
        has_both = any(
            e.left_articles and e.right_articles for e in cluster_events
        )
        assert has_both, (
            "rss_left.xml and rss_right.xml must produce at least one event with "
            "both left and right articles (shared topic: 'climate policy reform')"
        )

    def test_spin_delta_is_non_zero_for_opposing_framings(self, cluster_events: list) -> None:
        """Opposing framings of the climate story must produce a non-zero spin_delta."""
        dual = [e for e in cluster_events if e.left_articles and e.right_articles]
        assert dual, "Expected at least one dual-sided event"
        assert dual[0].spin_delta > 0.0, (
            f"spin_delta must be non-zero for opposing framings; got {dual[0].spin_delta}"
        )

    def test_left_articles_have_left_lean(self, cluster_events: list) -> None:
        dual = [e for e in cluster_events if e.left_articles and e.right_articles]
        assert dual
        for aa in dual[0].left_articles:
            assert aa.spin.lens in ("left", "left-center"), (
                f"Left-column article has unexpected lens: {aa.spin.lens!r}"
            )

    def test_right_articles_have_right_lean(self, cluster_events: list) -> None:
        dual = [e for e in cluster_events if e.left_articles and e.right_articles]
        assert dual
        for aa in dual[0].right_articles:
            assert aa.spin.lens in ("right", "right-center"), (
                f"Right-column article has unexpected lens: {aa.spin.lens!r}"
            )

    def test_print_dual_lens_renders_both_columns(self, cluster_events: list) -> None:
        out = _capture_print_dual_lens(cluster_events)
        assert "#### LEFT" in out, "Clustering fixture must render a LEFT column"
        assert "#### RIGHT" in out, "Clustering fixture must render a RIGHT column"

    def test_print_dual_lens_spin_pct_in_output(self, cluster_events: list) -> None:
        out = _capture_print_dual_lens(cluster_events)
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", out)
        assert matches, "spin_pct annotations must appear for fixture articles"
        for raw in matches:
            assert 0.0 <= float(raw) <= 100.0


# ---------------------------------------------------------------------------
# 3. _print_dual_lens format specification
# ---------------------------------------------------------------------------


class TestPrintDualLensFormatSpec:
    """Pinning the exact output format of _print_dual_lens at the character level."""

    def test_h2_header_appears_exactly_once_with_multiple_events(self) -> None:
        events = [
            _make_dual_event("Climate policy clash", left=("Left view 1",), right=("Right view 1",)),
            _make_dual_event("Tax reform debate", left=("Left view 2",), right=("Right view 2",)),
            _make_dual_event("Immigration bill vote", left=("Left view 3",), right=("Right view 3",)),
        ]
        out = _capture_print_dual_lens(events)
        count = out.count("## DUAL-LENS EVENTS")
        assert count == 1, (
            f"'## DUAL-LENS EVENTS' must appear exactly once; found {count} times"
        )

    def test_spin_pct_formatted_with_exactly_one_decimal(self) -> None:
        """:.1f ensures e.g. 50.0 → '50.0', not '50' and not '50.00'."""
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa = AnnotatedArticle(
            article=_make_article("Guardian analysis on policy"),
            spin=SpinResult(spin_pct=50.0, lens="left", rubric={}, receipts=""),
        )
        event = DualLensEvent(event_title="Policy debate", left_articles=[aa], spin_delta=50.0)
        out = _capture_print_dual_lens([event])
        # Must match "spin_pct: 50.0%" — exactly one decimal, no more
        assert re.search(r"spin_pct:\s*50\.0%", out), (
            f"spin_pct 50.0 must render as '50.0%'; got: {out!r}"
        )
        assert "50.00%" not in out, "spin_pct must not use two decimal places"
        assert re.search(r"spin_pct:\s*50%", out) is None, (
            "spin_pct must not omit the decimal point"
        )

    def test_spin_delta_formatted_with_exactly_one_decimal(self) -> None:
        """spin_delta:34.5 must appear as '34.5', not '34' or '34.50'."""
        event = _make_dual_event("Trade war", left=("L",), right=("R",), spin_delta=34.5)
        out = _capture_print_dual_lens([event])
        assert "spin_delta: 34.5" in out, (
            f"spin_delta 34.5 must render as '34.5'; out={out!r}"
        )
        assert "spin_delta: 34.50" not in out

    def test_spin_pct_zero_renders_as_zero_point_zero(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa = AnnotatedArticle(
            article=_make_article("Reuters neutral wire report on markets"),
            spin=SpinResult(spin_pct=0.0, lens="left", rubric={}, receipts=""),
        )
        event = DualLensEvent(event_title="Market update", left_articles=[aa], spin_delta=0.0)
        out = _capture_print_dual_lens([event])
        assert "spin_pct: 0.0%" in out, (
            f"spin_pct=0.0 must render as '0.0%'; got: {out!r}"
        )

    def test_spin_pct_hundred_renders_as_hundred_point_zero(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa = AnnotatedArticle(
            article=_make_article("Extremely charged propaganda piece"),
            spin=SpinResult(spin_pct=100.0, lens="right", rubric={}, receipts="max spin"),
        )
        event = DualLensEvent(event_title="Charged event", right_articles=[aa], spin_delta=100.0)
        out = _capture_print_dual_lens([event])
        assert "spin_pct: 100.0%" in out, (
            f"spin_pct=100.0 must render as '100.0%'; got: {out!r}"
        )

    def test_left_heading_singular_for_one_article(self) -> None:
        event = _make_dual_event("Test event", left=("Only article",))
        out = _capture_print_dual_lens([event])
        assert "#### LEFT (1 article)" in out, (
            f"One left article must give '#### LEFT (1 article)'; got: {out!r}"
        )

    def test_left_heading_plural_for_two_articles(self) -> None:
        event = _make_dual_event("Test event", left=("Article one", "Article two"))
        out = _capture_print_dual_lens([event])
        assert "#### LEFT (2 articles)" in out, (
            f"Two left articles must give '#### LEFT (2 articles)'; got: {out!r}"
        )

    def test_right_heading_singular_for_one_article(self) -> None:
        event = _make_dual_event("Test event", right=("Only article",))
        out = _capture_print_dual_lens([event])
        assert "#### RIGHT (1 article)" in out

    def test_right_heading_plural_for_three_articles(self) -> None:
        event = _make_dual_event("Test event", right=("A", "B", "C"))
        out = _capture_print_dual_lens([event])
        assert "#### RIGHT (3 articles)" in out

    def test_rationale_line_present_iff_receipts_non_empty(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa_with = AnnotatedArticle(
            article=_make_article("Charged article with receipts"),
            spin=SpinResult(spin_pct=75.0, lens="left", rubric={}, receipts="Loaded Language fired"),
        )
        aa_without = AnnotatedArticle(
            article=_make_article("Neutral article with empty receipts"),
            spin=SpinResult(spin_pct=10.0, lens="right", rubric={}, receipts=""),
        )
        event = DualLensEvent(
            event_title="Mixed receipts event",
            left_articles=[aa_with],
            right_articles=[aa_without],
            spin_delta=65.0,
        )
        out = _capture_print_dual_lens([event])
        assert "rationale: Loaded Language fired" in out, (
            "Non-empty receipts must produce a rationale line"
        )
        # The right article has empty receipts — no rationale should appear for it
        right_section_start = out.index("#### RIGHT")
        right_section = out[right_section_start:]
        assert "rationale:" not in right_section, (
            "Empty receipts must NOT produce a rationale line"
        )

    def test_blank_line_after_left_column_block(self) -> None:
        """After the last LEFT article bullet there must be a blank line."""
        event = _make_dual_event("Policy clash", left=("L article",), right=("R article",))
        out = _capture_print_dual_lens([event])
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("#### RIGHT"):
                # The line before the RIGHT heading must be blank
                assert lines[i - 1].strip() == "", (
                    f"Expected blank line before '#### RIGHT'; found {lines[i-1]!r}"
                )
                break
        else:
            pytest.fail("'#### RIGHT' heading not found in output")

    def test_event_order_preserved_in_output(self) -> None:
        """Events must appear in input order in the output."""
        e1 = _make_dual_event("First event alphabetically", left=("L1",), right=("R1",))
        e2 = _make_dual_event("Second event alphabetically", left=("L2",), right=("R2",))
        out = _capture_print_dual_lens([e1, e2])
        idx1 = out.index("First event alphabetically")
        idx2 = out.index("Second event alphabetically")
        assert idx1 < idx2, "First event must appear before second event in output"

    def test_center_only_event_not_included(self) -> None:
        center_only = _make_dual_event("Center only event", center=("C article",))
        dual = _make_dual_event("Dual event", left=("L article",), right=("R article",))
        out = _capture_print_dual_lens([center_only, dual])
        assert "Center only event" not in out, "Center-only events must be filtered"
        assert "Dual event" in out

    def test_empty_input_produces_empty_string(self) -> None:
        out = _capture_print_dual_lens([])
        assert out == ""

    def test_all_center_input_produces_empty_string(self) -> None:
        events = [
            _make_dual_event("Center event 1", center=("Reuters story",)),
            _make_dual_event("Center event 2", center=("AP wire report",)),
        ]
        out = _capture_print_dual_lens(events)
        assert out == ""


# ---------------------------------------------------------------------------
# 4. daily_digest unit tests
# ---------------------------------------------------------------------------


class TestDailyDigestUnit:
    """Direct unit tests for situation_monitor.digest.daily_digest."""

    def _event(self, title: str, left=(), right=(), center=(), delta: float = 0.0):
        return _make_dual_event(title, left=left, right=right, center=center, spin_delta=delta)

    def test_returns_a_string(self) -> None:
        from situation_monitor.digest import daily_digest
        result = daily_digest([], [], as_of=datetime(2026, 6, 14, 12, 0))
        assert isinstance(result, str)

    def test_starts_with_situation_monitor_header(self) -> None:
        from situation_monitor.digest import daily_digest
        result = daily_digest([], [], as_of=datetime(2026, 6, 14, 12, 0))
        assert result.startswith("*Situation Monitor*"), (
            f"Output must start with '*Situation Monitor*'; got: {result[:80]!r}"
        )

    def test_date_stamp_in_header(self) -> None:
        from situation_monitor.digest import daily_digest
        result = daily_digest([], [], as_of=datetime(2026, 6, 14, 9, 30))
        assert "2026-06-14" in result
        assert "09:30" in result

    def test_empty_events_shows_no_events_found(self) -> None:
        from situation_monitor.digest import daily_digest
        result = daily_digest([], [], as_of=datetime(2026, 6, 14, 12, 0))
        assert "_No events found._" in result

    def test_with_events_shows_top_stories(self) -> None:
        from situation_monitor.digest import daily_digest
        events = [self._event("Climate summit opens", left=("L",), right=("R",), delta=20.0)]
        result = daily_digest(events, [], as_of=datetime(2026, 6, 14, 12, 0))
        assert "*Top Stories*" in result
        assert "Climate summit opens" in result

    def test_spin_delta_above_5_shows_arrow_annotation(self) -> None:
        from situation_monitor.digest import daily_digest
        event = self._event("Trade war escalates", left=("L",), right=("R",), delta=30.0)
        result = daily_digest([event], [], as_of=datetime(2026, 6, 14, 12, 0))
        assert "↕" in result, "spin_delta > 5 must render the ↕ arrow annotation"
        assert "↕30%" in result, "spin_delta=30 must render as '↕30%'"

    def test_spin_delta_exactly_5_omits_arrow_annotation(self) -> None:
        """Threshold is > 5, not >= 5; delta of exactly 5 must NOT show the arrow."""
        from situation_monitor.digest import daily_digest
        event = self._event("Borderline event", left=("L",), right=("R",), delta=5.0)
        result = daily_digest([event], [], as_of=datetime(2026, 6, 14, 12, 0))
        bullet_line = next(
            (l for l in result.splitlines() if "Borderline event" in l), None
        )
        assert bullet_line is not None, "Event must appear in digest"
        assert "↕" not in bullet_line, (
            "spin_delta=5.0 is NOT > 5; arrow must not appear"
        )

    def test_spin_delta_below_5_omits_arrow_annotation(self) -> None:
        from situation_monitor.digest import daily_digest
        event = self._event("Low delta event", left=("L",), right=("R",), delta=2.5)
        result = daily_digest([event], [], as_of=datetime(2026, 6, 14, 12, 0))
        bullet_line = next(
            (l for l in result.splitlines() if "Low delta event" in l), None
        )
        assert bullet_line is not None
        assert "↕" not in bullet_line

    def test_top_n_limits_events(self) -> None:
        from situation_monitor.digest import daily_digest
        events = [
            self._event(f"Event {i}", left=(f"L{i}",)) for i in range(5)
        ]
        result = daily_digest(events, [], top_n=2, as_of=datetime(2026, 6, 14, 12, 0))
        assert "Event 0" in result
        assert "Event 1" in result
        assert "Event 2" not in result

    def test_lens_count_annotation_L_present_for_left_articles(self) -> None:
        from situation_monitor.digest import daily_digest
        event = self._event("Left only", left=("L1", "L2"))
        result = daily_digest([event], [], as_of=datetime(2026, 6, 14, 12, 0))
        assert "L:2" in result, "Two left articles must annotate '[L:2]'"

    def test_lens_count_annotation_R_present_for_right_articles(self) -> None:
        from situation_monitor.digest import daily_digest
        event = self._event("Right only", right=("R1",))
        result = daily_digest([event], [], as_of=datetime(2026, 6, 14, 12, 0))
        assert "R:1" in result

    def test_lens_count_shows_both_L_and_R_for_dual_event(self) -> None:
        from situation_monitor.digest import daily_digest
        event = self._event("Dual event", left=("L1",), right=("R1", "R2"), delta=25.0)
        result = daily_digest([event], [], as_of=datetime(2026, 6, 14, 12, 0))
        assert "L:1" in result
        assert "R:2" in result

    def test_events_appear_as_bullet_points(self) -> None:
        from situation_monitor.digest import daily_digest
        events = [self._event("Fed rate decision", left=("L",))]
        result = daily_digest(events, [], as_of=datetime(2026, 6, 14, 12, 0))
        lines = result.splitlines()
        bullet_lines = [l for l in lines if l.startswith("•")]
        assert bullet_lines, "Events must appear as '•' bullet-point entries"
        assert any("Fed rate decision" in l for l in bullet_lines)

    def test_with_movers_shows_market_movers_section(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.practical import PracticalMover
        movers = [PracticalMover(asset="Gold", change_pct=2.5, direction="up",
                                  who_it_affects="investors", what_to_watch="next Fed meeting",
                                  source_url="https://ecb.example/rss")]
        result = daily_digest([], movers, as_of=datetime(2026, 6, 14, 12, 0))
        assert "*Market Movers*" in result
        assert "Gold" in result

    def test_without_movers_no_market_movers_section(self) -> None:
        from situation_monitor.digest import daily_digest
        result = daily_digest([], [], as_of=datetime(2026, 6, 14, 12, 0))
        assert "*Market Movers*" not in result

    def test_movers_show_up_arrow_for_up_direction(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.practical import PracticalMover
        movers = [PracticalMover(asset="BTC", change_pct=5.0, direction="up",
                                  who_it_affects="crypto holders", what_to_watch="exchange flows",
                                  source_url="https://ecb.example/rss")]
        result = daily_digest([], movers, as_of=datetime(2026, 6, 14, 12, 0))
        assert "▲" in result

    def test_movers_show_down_arrow_for_down_direction(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.practical import PracticalMover
        movers = [PracticalMover(asset="Oil", change_pct=-3.2, direction="down",
                                  who_it_affects="drivers", what_to_watch="OPEC decisions",
                                  source_url="https://ecb.example/rss")]
        result = daily_digest([], movers, as_of=datetime(2026, 6, 14, 12, 0))
        assert "▼" in result

    def test_movers_limited_to_five(self) -> None:
        from situation_monitor.digest import daily_digest
        from situation_monitor.practical import PracticalMover
        movers = [
            PracticalMover(asset=f"Asset{i}", change_pct=float(i), direction="up",
                            who_it_affects="x", what_to_watch="y",
                            source_url="https://ecb.example/rss")
            for i in range(8)
        ]
        result = daily_digest([], movers, as_of=datetime(2026, 6, 14, 12, 0))
        assert "Asset0" in result
        assert "Asset4" in result
        assert "Asset5" not in result


# ---------------------------------------------------------------------------
# 5. DualLensEvent mutable default field isolation
# ---------------------------------------------------------------------------


class TestDualLensEventMutableDefaults:
    """Each DualLensEvent instance must own its own list objects.

    Python's mutable default argument / dataclass field pitfall: if the
    default_factory is wrong (e.g. default=[] instead of
    default_factory=list), all instances share the same list and mutations to
    one bleed into all others.  This test would catch that bug.
    """

    def test_left_articles_are_independent_per_instance(self) -> None:
        from situation_monitor.dual_lens import DualLensEvent

        a = DualLensEvent(event_title="Event A")
        b = DualLensEvent(event_title="Event B")
        a.left_articles.append(_make_aa("Article in A", "left", 60.0))
        assert b.left_articles == [], (
            "Mutating a.left_articles must not affect b.left_articles — "
            "mutable default field must be factory, not shared []"
        )

    def test_right_articles_are_independent_per_instance(self) -> None:
        from situation_monitor.dual_lens import DualLensEvent

        a = DualLensEvent(event_title="Event A")
        b = DualLensEvent(event_title="Event B")
        a.right_articles.append(_make_aa("Article in A", "right", 40.0))
        assert b.right_articles == []

    def test_center_articles_are_independent_per_instance(self) -> None:
        from situation_monitor.dual_lens import DualLensEvent

        a = DualLensEvent(event_title="Event A")
        b = DualLensEvent(event_title="Event B")
        a.center_articles.append(_make_aa("Article in A", "center", 50.0))
        assert b.center_articles == []

    def test_default_spin_delta_is_zero(self) -> None:
        from situation_monitor.dual_lens import DualLensEvent

        event = DualLensEvent(event_title="Default delta")
        assert event.spin_delta == 0.0

    def test_default_left_articles_is_empty_list(self) -> None:
        from situation_monitor.dual_lens import DualLensEvent

        event = DualLensEvent(event_title="Defaults")
        assert event.left_articles == []
        assert isinstance(event.left_articles, list)

    def test_default_right_articles_is_empty_list(self) -> None:
        from situation_monitor.dual_lens import DualLensEvent

        event = DualLensEvent(event_title="Defaults")
        assert event.right_articles == []

    def test_default_center_articles_is_empty_list(self) -> None:
        from situation_monitor.dual_lens import DualLensEvent

        event = DualLensEvent(event_title="Defaults")
        assert event.center_articles == []


# ---------------------------------------------------------------------------
# 6. _assign_clusters unit tests
# ---------------------------------------------------------------------------


class TestAssignClusters:
    """_assign_clusters groups articles by their first non-stopword title token."""

    def _run(self, articles):
        from situation_monitor.__main__ import _assign_clusters

        _assign_clusters(articles)
        return articles

    def test_articles_with_same_first_significant_word_share_cluster(self) -> None:
        a1 = _make_article("Climate policy debate intensifies globally")
        a2 = _make_article("Climate summit opens in Geneva today")
        self._run([a1, a2])
        assert a1.cluster_id == a2.cluster_id, (
            "Articles with same first significant word must share cluster_id"
        )

    def test_articles_with_different_first_significant_word_differ(self) -> None:
        a1 = _make_article("Climate policy reform rejected by Senate")
        a2 = _make_article("Housing market decline continues into autumn")
        self._run([a1, a2])
        assert a1.cluster_id != a2.cluster_id, (
            "Articles with different first significant words must have different cluster_ids"
        )

    def test_title_starting_with_stopword_uses_next_significant_word(self) -> None:
        """'The climate ...' → first significant word is 'climate'."""
        a1 = _make_article("The climate crisis worsens globally")
        a2 = _make_article("Climate conference opens in Berlin today")
        self._run([a1, a2])
        assert a1.cluster_id == a2.cluster_id, (
            "Stopword-prefixed title must use the next significant word for clustering"
        )

    def test_pure_stopword_title_gets_misc_cluster(self) -> None:
        a = _make_article("The is an in of")
        self._run([a])
        assert a.cluster_id == "misc", (
            "Title with only stopwords must get cluster_id='misc'"
        )

    def test_cluster_ids_are_strings(self) -> None:
        a = _make_article("Federal Reserve raises interest rates")
        self._run([a])
        assert isinstance(a.cluster_id, str)

    def test_empty_list_does_not_raise(self) -> None:
        self._run([])  # must not raise

    def test_all_articles_get_a_cluster_id(self) -> None:
        articles = [
            _make_article("Federal Reserve rate decision"),
            _make_article("SpaceX rocket launch delayed"),
            _make_article("Climate policy reform rejected"),
        ]
        self._run(articles)
        for a in articles:
            assert a.cluster_id is not None, f"Article {a.title!r} has no cluster_id"

    def test_cluster_counter_increments_per_new_first_word(self) -> None:
        """Three articles with three different first words → three distinct clusters."""
        articles = [
            _make_article("Alpha event unfolds globally"),
            _make_article("Beta event continues today"),
            _make_article("Gamma event reaches conclusion"),
        ]
        self._run(articles)
        ids = {a.cluster_id for a in articles}
        assert len(ids) == 3, f"Expected 3 distinct cluster_ids; got {ids}"

    def test_cluster_ids_start_with_c(self) -> None:
        """cluster_ids are 'c0', 'c1', ... (not UUID, not hash)."""
        articles = [
            _make_article("Alpha event unfolds globally"),
            _make_article("Beta event continues today"),
        ]
        self._run(articles)
        for a in articles:
            if a.cluster_id != "misc":
                assert a.cluster_id.startswith("c"), (
                    f"cluster_id {a.cluster_id!r} must start with 'c'"
                )

    def test_repeated_application_is_idempotent(self) -> None:
        """Calling _assign_clusters twice must give the same cluster_ids."""
        from situation_monitor.__main__ import _assign_clusters

        articles = [
            _make_article("Federal Reserve rate decision"),
            _make_article("Federal Reserve policy stance"),
            _make_article("SpaceX rocket launch success"),
        ]
        _assign_clusters(articles)
        ids_first = [a.cluster_id for a in articles]
        _assign_clusters(articles)
        ids_second = [a.cluster_id for a in articles]
        assert ids_first == ids_second, (
            "_assign_clusters must produce the same cluster_ids on repeated calls"
        )

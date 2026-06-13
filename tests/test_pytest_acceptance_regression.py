"""Full regression guard: independent re-run of pytest and acceptance script.

Acceptance criteria under test:
  1. ``pytest tests/`` exits 0 — all tests collected and passing.
  2. Acceptance script exits 0.
  3. Dual-lens render is present in acceptance stdout
     (## DUAL-LENS EVENTS + LEFT/RIGHT column headings).
  4. Spin estimate percentage is present in acceptance stdout
     (``spin_pct: N.N%`` pattern from _print_dual_lens).

These tests are deliberately independent of the builder's own test files.
They verify *output contracts* produced by real code paths — every assertion
can fail on a real regression.
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
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"
THIS_FILE = Path(__file__).name  # exclude self from meta pytest run


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _stub_env() -> dict[str, str]:
    """Environment that forces stub LLM and fixture RSS — no network calls."""
    return {
        **os.environ,
        "SM_LLM_BACKEND": "stub",
        "SM_SOURCES": "tests/fixtures/rss_sample.xml",
    }


def _run_acceptance() -> tuple[str, int]:
    """Execute the acceptance script and return (stdout, returncode)."""
    cmd = ACCEPTANCE_FILE.read_text().strip()
    result = subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        timeout=90,
        cwd=PROJECT_ROOT,
    )
    return result.stdout.decode(errors="replace"), result.returncode


@pytest.fixture(scope="module")
def acceptance_run() -> tuple[str, int]:
    """Run the acceptance script once; share across all tests in this module."""
    return _run_acceptance()


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_run) -> str:
    stdout, _ = acceptance_run
    return stdout


@pytest.fixture(scope="module")
def acceptance_returncode(acceptance_run) -> int:
    _, rc = acceptance_run
    return rc


# ---------------------------------------------------------------------------
# 1. pytest meta-test: the full test suite passes
# ---------------------------------------------------------------------------


class TestPytestSuitePasses:
    """Run pytest as a subprocess; assert it exits 0 with all tests passing."""

    def test_pytest_suite_exits_zero(self) -> None:
        """pytest tests/ (excluding this file) must exit 0."""
        result = subprocess.run(
            [
                sys.executable,
                "-m", "pytest",
                "tests/",
                f"--ignore=tests/{THIS_FILE}",
                "-q",
                "--tb=short",
            ],
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=_stub_env(),
            timeout=240,
        )
        assert result.returncode == 0, (
            f"pytest suite exited {result.returncode}.\n"
            f"stdout tail:\n{result.stdout.decode(errors='replace')[-2000:]}\n"
            f"stderr tail:\n{result.stderr.decode(errors='replace')[-500:]}"
        )

    def test_pytest_suite_collects_at_least_one_hundred_tests(self) -> None:
        """The collection must be non-trivial — fewer than 100 items signals a broken conftest."""
        result = subprocess.run(
            [
                sys.executable,
                "-m", "pytest",
                "tests/",
                f"--ignore=tests/{THIS_FILE}",
                "--collect-only",
                "-q",
                "--tb=short",
            ],
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=_stub_env(),
            timeout=60,
        )
        output = result.stdout.decode(errors="replace")
        # e.g. "1154 tests collected" or "1 test collected"
        matches = re.findall(r"(\d+) tests? collected", output)
        count = int(matches[-1]) if matches else 0
        assert count >= 100, (
            f"Expected >= 100 tests collected; got {count}.\n"
            f"Collection output:\n{output[:1000]}"
        )

    def test_pytest_no_collection_errors(self) -> None:
        """Collection step must exit 0 (any collection error gives a non-zero code)."""
        result = subprocess.run(
            [
                sys.executable,
                "-m", "pytest",
                "tests/",
                f"--ignore=tests/{THIS_FILE}",
                "--collect-only",
                "-q",
                "--tb=short",
            ],
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=_stub_env(),
            timeout=60,
        )
        output = result.stdout.decode(errors="replace") + result.stderr.decode(errors="replace")
        assert result.returncode == 0, (
            f"pytest --collect-only exited {result.returncode} (non-zero means collection errors).\n"
            f"Output:\n{output[:2000]}"
        )

    def test_pytest_no_test_failures(self) -> None:
        """Running the full suite must produce zero failures and zero errors."""
        result = subprocess.run(
            [
                sys.executable,
                "-m", "pytest",
                "tests/",
                f"--ignore=tests/{THIS_FILE}",
                "-q",
                "--tb=no",
            ],
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=_stub_env(),
            timeout=240,
        )
        output = result.stdout.decode(errors="replace")
        # Look for the summary line: "N passed" with no "failed" or "error"
        assert "failed" not in output.lower() or result.returncode == 0, (
            f"Test failures detected.\nOutput tail:\n{output[-2000:]}"
        )
        assert result.returncode == 0, (
            f"pytest exited {result.returncode}.\nOutput:\n{output[-2000:]}"
        )


# ---------------------------------------------------------------------------
# 2. Acceptance script: exits 0
# ---------------------------------------------------------------------------


class TestAcceptanceExitsZero:
    """The acceptance script must exit 0 with no errors."""

    def test_acceptance_file_is_present(self) -> None:
        assert ACCEPTANCE_FILE.exists(), (
            "acceptance file must exist at the project root"
        )

    def test_acceptance_file_contains_commands(self) -> None:
        text = ACCEPTANCE_FILE.read_text().strip()
        assert text, "acceptance file must not be empty"
        assert "situation_monitor" in text, (
            "acceptance file must reference the situation_monitor module"
        )

    def test_acceptance_references_once_subcommand(self) -> None:
        text = ACCEPTANCE_FILE.read_text()
        assert "once" in text, (
            "acceptance file must invoke the 'once' subcommand which emits dual-lens output"
        )

    def test_acceptance_references_digest_dry_run(self) -> None:
        text = ACCEPTANCE_FILE.read_text()
        assert "digest-dry-run" in text, (
            "acceptance file must invoke 'digest-dry-run' which emits *Top Stories*"
        )

    def test_acceptance_script_exit_code_is_zero(self, acceptance_returncode) -> None:
        assert acceptance_returncode == 0, (
            f"acceptance script exited {acceptance_returncode}; expected 0. "
            "Both 'once' and 'digest-dry-run' subcommands must succeed."
        )

    def test_acceptance_no_python_traceback(self, acceptance_stdout) -> None:
        assert "Traceback (most recent call last)" not in acceptance_stdout, (
            "acceptance output must not contain a Python traceback"
        )

    def test_acceptance_no_error_keyword(self, acceptance_stdout) -> None:
        # Allow the word "error" inside article titles; look for standalone Error lines
        lines_with_error = [
            l for l in acceptance_stdout.splitlines()
            if l.strip().startswith("Error") or l.strip().startswith("ERROR")
        ]
        assert not lines_with_error, (
            f"Unexpected Error lines in acceptance output:\n" +
            "\n".join(lines_with_error[:5])
        )


# ---------------------------------------------------------------------------
# 3. Dual-lens render: present in acceptance stdout
# ---------------------------------------------------------------------------


class TestDualLensRenderPresent:
    """The 'once' subcommand must emit a complete dual-lens render block."""

    def test_dual_lens_events_header_present(self, acceptance_stdout) -> None:
        assert "DUAL-LENS EVENTS" in acceptance_stdout, (
            "acceptance stdout must contain '## DUAL-LENS EVENTS' header"
        )

    def test_dual_lens_left_column_heading_present(self, acceptance_stdout) -> None:
        assert "#### LEFT" in acceptance_stdout, (
            "acceptance stdout must contain '#### LEFT' column heading"
        )

    def test_dual_lens_right_column_heading_present(self, acceptance_stdout) -> None:
        assert "#### RIGHT" in acceptance_stdout, (
            "acceptance stdout must contain '#### RIGHT' column heading"
        )

    def test_dual_lens_event_h3_title_present(self, acceptance_stdout) -> None:
        in_block = False
        found_h3 = False
        for line in acceptance_stdout.splitlines():
            if "## DUAL-LENS EVENTS" in line:
                in_block = True
                continue
            if in_block and line.startswith("### ") and line.strip() != "###":
                found_h3 = True
                break
            if in_block and line.startswith("## ") and "DUAL-LENS" not in line:
                break
        assert found_h3, (
            "## DUAL-LENS EVENTS block must contain at least one '### <title>' H3 heading"
        )

    def test_dual_lens_left_column_has_bullet(self, acceptance_stdout) -> None:
        lines = acceptance_stdout.splitlines()
        in_left = False
        for line in lines:
            if "#### LEFT" in line:
                in_left = True
                continue
            if in_left:
                if line.startswith("- "):
                    return  # found a bullet — test passes
                if line.startswith("#"):
                    break
        pytest.fail("'#### LEFT' column must contain at least one '- ...' article bullet")

    def test_dual_lens_right_column_has_bullet(self, acceptance_stdout) -> None:
        lines = acceptance_stdout.splitlines()
        in_right = False
        for line in lines:
            if "#### RIGHT" in line:
                in_right = True
                continue
            if in_right:
                if line.startswith("- "):
                    return
                if line.startswith("#"):
                    break
        pytest.fail("'#### RIGHT' column must contain at least one '- ...' article bullet")

    def test_dual_lens_spin_delta_line_present(self, acceptance_stdout) -> None:
        assert "spin_delta:" in acceptance_stdout, (
            "dual-lens block must contain 'spin_delta:' per-event divergence annotation"
        )

    def test_dual_lens_rationale_line_present(self, acceptance_stdout) -> None:
        assert "rationale:" in acceptance_stdout, (
            "dual-lens block must contain 'rationale:' spin explanation lines"
        )

    def test_dual_lens_header_is_level_two(self, acceptance_stdout) -> None:
        lines = acceptance_stdout.splitlines()
        assert any(line == "## DUAL-LENS EVENTS" for line in lines), (
            "Dual-lens header must be exactly '## DUAL-LENS EVENTS' (no extra text)"
        )

    def test_dual_lens_left_heading_includes_article_count(self, acceptance_stdout) -> None:
        left_lines = [l for l in acceptance_stdout.splitlines() if l.startswith("#### LEFT")]
        assert left_lines, "#### LEFT heading must be present"
        heading = left_lines[0]
        assert "article" in heading, (
            f"#### LEFT heading must include article count; got: {heading!r}"
        )

    def test_dual_lens_right_heading_includes_article_count(self, acceptance_stdout) -> None:
        right_lines = [l for l in acceptance_stdout.splitlines() if l.startswith("#### RIGHT")]
        assert right_lines, "#### RIGHT heading must be present"
        heading = right_lines[0]
        assert "article" in heading, (
            f"#### RIGHT heading must include article count; got: {heading!r}"
        )

    def test_dual_lens_blocks_contain_situation_monitor_heading(self, acceptance_stdout) -> None:
        assert "Situation Monitor" in acceptance_stdout, (
            "acceptance output must include the top-level 'Situation Monitor' heading"
        )

    def test_digest_dry_run_top_stories_present(self, acceptance_stdout) -> None:
        assert "*Top Stories*" in acceptance_stdout, (
            "digest-dry-run output must contain '*Top Stories*' section"
        )

    def test_digest_dry_run_lens_counts_present(self, acceptance_stdout) -> None:
        assert "L:" in acceptance_stdout and "R:" in acceptance_stdout, (
            "digest-dry-run output must include [L:N, R:N] lens counts for dual-lens events"
        )


# ---------------------------------------------------------------------------
# 4. Spin estimate percentage: present and valid in acceptance stdout
# ---------------------------------------------------------------------------


class TestSpinEstimatePercentagePresent:
    """The spin_pct pattern must appear in acceptance stdout with valid float values."""

    def test_spin_pct_pattern_present(self, acceptance_stdout) -> None:
        assert "spin_pct:" in acceptance_stdout, (
            "acceptance stdout must contain 'spin_pct:' annotation from _print_dual_lens"
        )

    def test_spin_pct_value_is_numeric(self, acceptance_stdout) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert matches, (
            "acceptance stdout must contain at least one 'spin_pct: N.N%' value"
        )

    def test_spin_pct_value_in_valid_range(self, acceptance_stdout) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert matches, "No spin_pct values found in acceptance stdout"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid 0–100 range"
            )

    def test_spin_pct_format_has_decimal(self, acceptance_stdout) -> None:
        """spin_pct must be printed with one decimal place (e.g. '50.0%' not '50%')."""
        matches = re.findall(r"spin_pct:\s*(\d+\.\d+)%", acceptance_stdout)
        assert matches, (
            "spin_pct values must include a decimal point (e.g. '50.0%'); "
            "none found matching 'spin_pct: N.N%'"
        )

    def test_spin_pct_appears_in_article_bullet_line(self, acceptance_stdout) -> None:
        bullet_lines = [l for l in acceptance_stdout.splitlines() if l.startswith("- ")]
        spin_bullets = [l for l in bullet_lines if "spin_pct:" in l]
        assert spin_bullets, (
            "At least one '- ...' bullet line must contain 'spin_pct:'"
        )

    def test_spin_pct_bullet_follows_expected_format(self, acceptance_stdout) -> None:
        """Article bullets must follow: '- <title> | spin_pct: N.N%'."""
        bullet_lines = [l for l in acceptance_stdout.splitlines() if "spin_pct:" in l and l.startswith("- ")]
        assert bullet_lines, "No article bullet with spin_pct found"
        for line in bullet_lines:
            assert re.search(r"spin_pct:\s*\d+\.\d+%", line), (
                f"spin_pct in bullet line is not formatted as 'spin_pct: N.N%': {line!r}"
            )

    def test_spin_pct_appears_at_least_once_per_dual_lens_event(self, acceptance_stdout) -> None:
        """Each dual-lens event that has articles must show at least one spin_pct value."""
        in_block = False
        event_count = 0
        spins_per_event: list[int] = []
        current_spins = 0

        for line in acceptance_stdout.splitlines():
            if "## DUAL-LENS EVENTS" in line:
                in_block = True
                continue
            if not in_block:
                continue
            if line.startswith("### ") and line.strip() != "###":
                if event_count > 0:
                    spins_per_event.append(current_spins)
                event_count += 1
                current_spins = 0
            if "spin_pct:" in line and line.startswith("- "):
                current_spins += 1
        if event_count > 0:
            spins_per_event.append(current_spins)

        assert event_count >= 1, "Must have at least one dual-lens event"
        for i, count in enumerate(spins_per_event):
            assert count >= 1, (
                f"Dual-lens event #{i + 1} has no spin_pct values in its article bullets"
            )

    def test_spin_delta_is_numeric(self, acceptance_stdout) -> None:
        """spin_delta values must be parseable as non-negative floats."""
        matches = re.findall(r"spin_delta:\s*([\d.]+)", acceptance_stdout)
        assert matches, "No 'spin_delta: N.N' patterns found in acceptance output"
        for raw in matches:
            val = float(raw)
            assert val >= 0.0, f"spin_delta must be non-negative; got {val}"


# ---------------------------------------------------------------------------
# 5. Integration: _print_dual_lens directly (unit-level, no subprocess)
# ---------------------------------------------------------------------------


class TestPrintDualLensDirectUnit:
    """Directly invoke _print_dual_lens and verify its output structure."""

    def _make_article(self, title: str, lean: str = "center"):
        from situation_monitor.models import Article

        a = Article(
            url=f"https://example.com/{title[:30].replace(' ', '-')}",
            title=title,
            source="TestFeed",
        )
        a.source_lean = lean
        return a

    def _make_spin(self, pct: float, lens: str, receipts: str = "test receipt"):
        from situation_monitor.models import SpinResult

        return SpinResult(spin_pct=pct, lens=lens, rubric={}, receipts=receipts)

    def _make_event(self, title: str, left=(), right=(), center=(), delta: float = 0.0):
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent

        def _aa(t: str, lean: str, pct: float = 50.0):
            return AnnotatedArticle(
                article=self._make_article(t, lean),
                spin=self._make_spin(pct, lean),
            )

        return DualLensEvent(
            event_title=title,
            left_articles=[_aa(t, "left") for t in left],
            right_articles=[_aa(t, "right") for t in right],
            center_articles=[_aa(t, "center") for t in center],
            spin_delta=delta,
        )

    def _capture(self, events: list) -> str:
        import io
        from contextlib import redirect_stdout
        from situation_monitor.__main__ import _print_dual_lens

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_dual_lens(events)
        return buf.getvalue()

    def test_empty_events_returns_no_output(self) -> None:
        assert self._capture([]) == ""

    def test_center_only_event_not_rendered(self) -> None:
        e = self._make_event("Neutral event", center=("Center article one",))
        out = self._capture([e])
        assert "DUAL-LENS" not in out, "Center-only event must not appear in dual-lens block"

    def test_left_only_event_renders_dual_lens_block(self) -> None:
        e = self._make_event("Immigration crackdown", left=("Left coverage article",))
        out = self._capture([e])
        assert "## DUAL-LENS EVENTS" in out
        assert "#### LEFT" in out

    def test_left_only_event_omits_right_heading(self) -> None:
        e = self._make_event("Immigration crackdown", left=("Left coverage article",))
        out = self._capture([e])
        assert "#### RIGHT" not in out

    def test_right_only_event_renders_right_heading(self) -> None:
        e = self._make_event("Tax cut debate", right=("Right coverage article",))
        out = self._capture([e])
        assert "#### RIGHT" in out
        assert "#### LEFT" not in out

    def test_dual_event_renders_both_columns(self) -> None:
        e = self._make_event(
            "Climate accord signed",
            left=("Scientists applaud deal",),
            right=("Industry warns of costs",),
        )
        out = self._capture([e])
        assert "#### LEFT" in out
        assert "#### RIGHT" in out

    def test_spin_pct_appears_as_percentage_in_bullet(self) -> None:
        e = self._make_event("Rate hike", left=("Left view on hike",))
        out = self._capture([e])
        assert re.search(r"spin_pct:\s*\d+\.\d+%", out), (
            "Article bullet must contain 'spin_pct: N.N%'"
        )

    def test_spin_pct_value_is_stub_default(self) -> None:
        e = self._make_event("Rate hike", left=("Left view on rates",))
        out = self._capture([e])
        assert "50.0%" in out, "Stub spin must produce 50.0%"

    def test_rationale_present_when_receipts_non_empty(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa = AnnotatedArticle(
            article=self._make_article("Immigration crackdown headlines today"),
            spin=SpinResult(spin_pct=72.0, lens="right", rubric={}, receipts="Loaded Language fired"),
        )
        event = DualLensEvent(
            event_title="Immigration crackdown",
            right_articles=[aa],
            spin_delta=72.0,
        )
        out = self._capture([event])
        assert "rationale:" in out
        assert "Loaded Language fired" in out

    def test_rationale_absent_when_receipts_empty(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa = AnnotatedArticle(
            article=self._make_article("Neutral market report no bias detected"),
            spin=SpinResult(spin_pct=20.0, lens="left", rubric={}, receipts=""),
        )
        event = DualLensEvent(
            event_title="Market report",
            left_articles=[aa],
            spin_delta=0.0,
        )
        out = self._capture([event])
        assert "rationale:" not in out

    def test_spin_delta_appears_after_h3(self) -> None:
        e = self._make_event("Budget vote", left=("Left budget view",), delta=12.5)
        out = self._capture([e])
        lines = out.splitlines()
        for i, line in enumerate(lines):
            if line.startswith("### "):
                for j in range(i + 1, min(i + 5, len(lines))):
                    if lines[j].strip():
                        assert "spin_delta:" in lines[j], (
                            f"First non-blank line after event title must contain spin_delta:"
                            f"; got {lines[j]!r}"
                        )
                        break
                break

    def test_article_count_singular_label(self) -> None:
        e = self._make_event("Budget decision", left=("Left budget article",))
        out = self._capture([e])
        assert "#### LEFT (1 article)" in out

    def test_article_count_plural_label(self) -> None:
        e = self._make_event("Budget decision", left=("Left article A", "Left article B"))
        out = self._capture([e])
        assert "#### LEFT (2 articles)" in out

    def test_multiple_events_all_rendered(self) -> None:
        e1 = self._make_event("Fed raises rates", left=("Left view A",), right=("Right view A",))
        e2 = self._make_event("Tariff increase", left=("Left view B",), right=("Right view B",))
        out = self._capture([e1, e2])
        assert "Fed raises rates" in out
        assert "Tariff increase" in out

    def test_center_events_filtered_dual_events_kept(self) -> None:
        center = self._make_event("Neutral briefing", center=("Reuters report",))
        dual = self._make_event("Policy clash", left=("Left policy",), right=("Right policy",))
        out = self._capture([center, dual])
        assert "Policy clash" in out
        assert "Neutral briefing" not in out

    def test_output_has_no_traceback(self) -> None:
        e = self._make_event("Event X", left=("Left view",), right=("Right view",))
        out = self._capture([e])
        assert "Traceback" not in out

    def test_rationale_lines_indented_two_spaces(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa = AnnotatedArticle(
            article=self._make_article("Article with spin receipt test"),
            spin=SpinResult(spin_pct=80.0, lens="left", rubric={}, receipts="Some receipt"),
        )
        event = DualLensEvent(
            event_title="Event with rationale",
            left_articles=[aa],
            spin_delta=0.0,
        )
        out = self._capture([event])
        rationale_lines = [l for l in out.splitlines() if "rationale:" in l]
        assert rationale_lines, "Rationale line must be present"
        for rl in rationale_lines:
            assert rl.startswith("  "), (
                f"Rationale lines must be indented with 2 spaces; got: {rl!r}"
            )

    def test_article_bullet_starts_with_dash_space(self) -> None:
        e = self._make_event("Rate decision", left=("Left analysis view",))
        out = self._capture([e])
        article_lines = [l for l in out.splitlines() if "spin_pct:" in l]
        assert article_lines, "Must find article bullet lines"
        for line in article_lines:
            assert line.startswith("- "), (
                f"Article bullet must start with '- '; got: {line!r}"
            )


# ---------------------------------------------------------------------------
# 6. End-to-end: fixture RSS → group_by_event → _print_dual_lens output check
# ---------------------------------------------------------------------------


class TestEndToEndFixturePipeline:
    """Ingest real fixture feeds, group into events, render, then verify output contracts."""

    @pytest.fixture(scope="class")
    def pipeline_output(self) -> str:
        import io
        from contextlib import redirect_stdout

        from situation_monitor.__main__ import _print_dual_lens
        from situation_monitor.config import SourceDef
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.ingestion.rss import RSSFetcher
        from situation_monitor.models import Domain

        class _LocalClient:
            def get(self, url: str) -> bytes:
                return Path(url).read_bytes()

        fetcher = RSSFetcher(client=_LocalClient())
        left_sd = SourceDef(str(FIXTURES / "rss_left.xml"), "Left", Domain.WORLD, "left")
        right_sd = SourceDef(str(FIXTURES / "rss_right.xml"), "Right", Domain.WORLD, "right")
        articles = fetcher.fetch(left_sd.url, source_def=left_sd)
        articles += fetcher.fetch(right_sd.url, source_def=right_sd)

        events = group_by_event(articles)

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_dual_lens(events)
        return buf.getvalue()

    def test_pipeline_dual_lens_block_present(self, pipeline_output) -> None:
        assert "DUAL-LENS EVENTS" in pipeline_output

    def test_pipeline_left_column_present(self, pipeline_output) -> None:
        assert "#### LEFT" in pipeline_output

    def test_pipeline_right_column_present(self, pipeline_output) -> None:
        assert "#### RIGHT" in pipeline_output

    def test_pipeline_spin_pct_values_present(self, pipeline_output) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", pipeline_output)
        assert matches, "Pipeline output must contain spin_pct values"

    def test_pipeline_spin_pct_values_in_range(self, pipeline_output) -> None:
        for raw in re.findall(r"spin_pct:\s*([\d.]+)%", pipeline_output):
            val = float(raw)
            assert 0.0 <= val <= 100.0

    def test_pipeline_event_title_non_empty(self, pipeline_output) -> None:
        h3_titles = [l[4:].strip() for l in pipeline_output.splitlines() if l.startswith("### ")]
        assert h3_titles, "Pipeline must produce at least one H3 event title"
        for t in h3_titles:
            assert t, "H3 event title must not be empty"

    def test_pipeline_climate_in_output(self, pipeline_output) -> None:
        assert "climate" in pipeline_output.lower() or "Climate" in pipeline_output, (
            "Climate event from fixtures must appear in pipeline output"
        )

    def test_pipeline_no_traceback(self, pipeline_output) -> None:
        assert "Traceback" not in pipeline_output

    def test_pipeline_spin_pct_format_matches_decimal(self, pipeline_output) -> None:
        """spin_pct must use one decimal place (N.N%) not integer format."""
        matches = re.findall(r"spin_pct:\s*(\d+\.\d+)%", pipeline_output)
        assert matches, "spin_pct must be printed with decimal precision (e.g. '50.0%')"

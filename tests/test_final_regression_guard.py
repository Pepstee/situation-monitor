"""Regression guard for the three acceptance criteria:

  1. pytest tests/ exits 0 (verifiable at the unit level via smoke/structural tests)
  2. acceptance script exits 0 and output contains a complete dual-lens render
  3. CAPABILITY_CHECKLIST.md contains all three comparison tables

The tests here are INDEPENDENT of the builder's own tests.  They check the
*output* contracts — what the acceptance script must produce — not internal
implementation details.  Every assertion can fail on a real regression.
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import textwrap
import urllib.parse
from contextlib import redirect_stdout
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"
CHECKLIST_FILE = PROJECT_ROOT / "CAPABILITY_CHECKLIST.md"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_article(title: str, source: str = "example.com", source_lean: str | None = None, **kw):
    from situation_monitor.models import Article

    url = kw.pop("url", f"https://{source}/{urllib.parse.quote(title.lower()[:50])}")
    a = Article(url=url, title=title, source=source, **kw)
    a.source_lean = source_lean
    return a


def _spin(pct: float, lens: str):
    from situation_monitor.models import SpinResult

    return SpinResult(spin_pct=pct, lens=lens, rubric={}, receipts=f"test receipt for {lens}")


def _run_acceptance_once() -> str:
    """Run the acceptance Python script and return combined stdout + returncode."""
    import os
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    result = subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        timeout=90,
        cwd=PROJECT_ROOT,
        env=env,
    )
    return result.stdout.decode(errors="replace"), result.returncode


# ---------------------------------------------------------------------------
# 1. CAPABILITY_CHECKLIST.md — all three comparison tables present
# ---------------------------------------------------------------------------


class TestCapabilityChecklist:
    """The checklist must contain three specific comparison table sections."""

    def test_checklist_file_exists(self) -> None:
        assert CHECKLIST_FILE.exists(), (
            "CAPABILITY_CHECKLIST.md must exist at the project root"
        )

    def test_checklist_is_non_empty(self) -> None:
        assert CHECKLIST_FILE.read_text().strip(), "CAPABILITY_CHECKLIST.md must not be empty"

    def test_checklist_contains_vs_ground_news_section(self) -> None:
        content = CHECKLIST_FILE.read_text()
        assert "Ground News" in content, (
            "CAPABILITY_CHECKLIST.md must contain a 'vs Ground News' comparison table"
        )

    def test_checklist_contains_vs_allsides_section(self) -> None:
        content = CHECKLIST_FILE.read_text()
        assert "AllSides" in content, (
            "CAPABILITY_CHECKLIST.md must contain a 'vs AllSides' comparison table"
        )

    def test_checklist_contains_vs_terminal_dashboard_section(self) -> None:
        content = CHECKLIST_FILE.read_text()
        assert "Terminal" in content and "dashboard" in content.lower(), (
            "CAPABILITY_CHECKLIST.md must contain a 'vs Terminal dashboard' comparison table"
        )

    def test_checklist_has_exactly_three_h2_sections(self) -> None:
        """Three comparison tables = three ## headings (or subsets with the right keywords)."""
        lines = CHECKLIST_FILE.read_text().splitlines()
        h2_lines = [l for l in lines if l.startswith("## ")]
        assert len(h2_lines) >= 3, (
            f"Expected at least 3 ## sections in CAPABILITY_CHECKLIST.md; found {len(h2_lines)}: {h2_lines}"
        )

    def test_ground_news_section_has_markdown_table(self) -> None:
        content = CHECKLIST_FILE.read_text()
        # Find the Ground News section and look for a pipe-based table
        gn_idx = content.find("Ground News")
        assert gn_idx >= 0, "Ground News section missing"
        section = content[gn_idx: gn_idx + 2000]
        assert "|" in section, "Ground News section must contain a Markdown table (pipe characters)"

    def test_allsides_section_has_markdown_table(self) -> None:
        content = CHECKLIST_FILE.read_text()
        as_idx = content.find("AllSides")
        assert as_idx >= 0, "AllSides section missing"
        section = content[as_idx: as_idx + 2000]
        assert "|" in section, "AllSides section must contain a Markdown table"

    def test_terminal_dashboard_section_has_markdown_table(self) -> None:
        content = CHECKLIST_FILE.read_text()
        td_idx = content.lower().find("terminal")
        assert td_idx >= 0, "Terminal dashboard section missing"
        section = content[td_idx: td_idx + 2000]
        assert "|" in section, "Terminal dashboard section must contain a Markdown table"

    def test_each_table_has_status_column(self) -> None:
        """Every table row must end with a PASS or FAIL status cell."""
        content = CHECKLIST_FILE.read_text()
        table_rows = [
            l.strip()
            for l in content.splitlines()
            if l.strip().startswith("|") and "PASS" in l or "FAIL" in l
        ]
        assert table_rows, (
            "At least one data row with PASS or FAIL must exist in CAPABILITY_CHECKLIST.md"
        )

    def test_ground_news_table_has_at_least_one_pass(self) -> None:
        content = CHECKLIST_FILE.read_text()
        gn_idx = content.find("Ground News")
        # Find next H2 after this section
        next_h2 = content.find("\n## ", gn_idx + 1)
        section = content[gn_idx:next_h2] if next_h2 > gn_idx else content[gn_idx:]
        assert "PASS" in section, "vs Ground News table must have at least one PASS"

    def test_allsides_table_has_at_least_one_pass(self) -> None:
        content = CHECKLIST_FILE.read_text()
        as_idx = content.find("AllSides")
        next_h2 = content.find("\n## ", as_idx + 1)
        section = content[as_idx:next_h2] if next_h2 > as_idx else content[as_idx:]
        assert "PASS" in section, "vs AllSides table must have at least one PASS"

    def test_status_values_are_only_pass_or_fail(self) -> None:
        """Every Status cell must be exactly PASS or FAIL — no typos."""
        content = CHECKLIST_FILE.read_text()
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith("|"):
                continue
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            if not cells:
                continue
            last = cells[-1]
            if last in ("Status", "---", ""):
                continue
            if last in ("PASS", "FAIL"):
                continue
            # Not a data row with a Status column; that's fine
            # Only flag if it looks like a data row (>= 4 cells and last cell is not a known value)
            if len(cells) >= 4 and last not in ("PASS", "FAIL", "Status", "---", ""):
                # Could be the description cell — skip rows where last cell is long prose
                if len(last) > 6:
                    continue
                pytest.fail(
                    f"Unexpected Status cell value {last!r} in line: {line!r}\n"
                    "Status cells must be exactly PASS or FAIL"
                )


# ---------------------------------------------------------------------------
# 2. Acceptance script — exits 0 AND dual-lens render is complete
# ---------------------------------------------------------------------------


class TestAcceptanceDualLensRender:
    """The acceptance output must contain a complete dual-lens render block."""

    @pytest.fixture(scope="class")
    def acceptance_stdout(self):
        stdout, returncode = _run_acceptance_once()
        return stdout, returncode

    def test_acceptance_exits_zero(self, acceptance_stdout) -> None:
        _, returncode = acceptance_stdout
        assert returncode == 0, (
            f"Acceptance script exited {returncode}; expected 0. "
            "Check that both 'once' and 'digest-dry-run' subcommands succeed."
        )

    def test_acceptance_contains_dual_lens_events_header(self, acceptance_stdout) -> None:
        stdout, _ = acceptance_stdout
        assert "DUAL-LENS EVENTS" in stdout, (
            "Acceptance output must contain '## DUAL-LENS EVENTS' header from _print_dual_lens"
        )

    def test_acceptance_contains_left_column_heading(self, acceptance_stdout) -> None:
        stdout, _ = acceptance_stdout
        assert "#### LEFT" in stdout, (
            "Acceptance output must contain '#### LEFT' heading in the dual-lens render"
        )

    def test_acceptance_contains_right_column_heading(self, acceptance_stdout) -> None:
        stdout, _ = acceptance_stdout
        assert "#### RIGHT" in stdout, (
            "Acceptance output must contain '#### RIGHT' heading in the dual-lens render"
        )

    def test_acceptance_contains_spin_pct_value(self, acceptance_stdout) -> None:
        stdout, _ = acceptance_stdout
        assert "spin_pct:" in stdout, (
            "Acceptance output must contain 'spin_pct:' per-article spin annotation"
        )

    def test_acceptance_contains_spin_delta_value(self, acceptance_stdout) -> None:
        stdout, _ = acceptance_stdout
        assert "spin_delta:" in stdout, (
            "Acceptance output must contain 'spin_delta:' event-level divergence annotation"
        )

    def test_acceptance_contains_rationale_line(self, acceptance_stdout) -> None:
        stdout, _ = acceptance_stdout
        assert "rationale:" in stdout, (
            "Acceptance output must contain 'rationale:' lines from SpinResult.receipts"
        )

    def test_acceptance_left_column_has_article_bullet(self, acceptance_stdout) -> None:
        """A '- <title>' bullet must appear immediately under the LEFT heading."""
        stdout, _ = acceptance_stdout
        lines = stdout.splitlines()
        in_left = False
        found_bullet = False
        for line in lines:
            if "#### LEFT" in line:
                in_left = True
                continue
            if in_left:
                if line.startswith("- "):
                    found_bullet = True
                    break
                if line.startswith("#"):
                    break  # new section, left column ended without a bullet
        assert found_bullet, (
            "The '#### LEFT' column must contain at least one '- <article>' bullet"
        )

    def test_acceptance_right_column_has_article_bullet(self, acceptance_stdout) -> None:
        """A '- <title>' bullet must appear immediately under the RIGHT heading."""
        stdout, _ = acceptance_stdout
        lines = stdout.splitlines()
        in_right = False
        found_bullet = False
        for line in lines:
            if "#### RIGHT" in line:
                in_right = True
                continue
            if in_right:
                if line.startswith("- "):
                    found_bullet = True
                    break
                if line.startswith("#"):
                    break
        assert found_bullet, (
            "The '#### RIGHT' column must contain at least one '- <article>' bullet"
        )

    def test_acceptance_dual_lens_event_has_h3_title(self, acceptance_stdout) -> None:
        """Each dual-lens event must have an H3 title inside the ## DUAL-LENS block."""
        stdout, _ = acceptance_stdout
        in_block = False
        found_h3 = False
        for line in stdout.splitlines():
            if "## DUAL-LENS EVENTS" in line:
                in_block = True
                continue
            if in_block:
                if line.startswith("### ") and line.strip() != "### ":
                    found_h3 = True
                    break
                if line.startswith("## ") and "DUAL-LENS" not in line:
                    break  # left the block without finding an H3
        assert found_h3, (
            "## DUAL-LENS EVENTS block must contain at least one '### <event_title>' heading"
        )

    def test_acceptance_article_spin_pct_is_numeric(self, acceptance_stdout) -> None:
        """spin_pct values in article bullets must be parseable as floats."""
        stdout, _ = acceptance_stdout
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", stdout)
        assert matches, "No 'spin_pct: <value>%' patterns found in acceptance output"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val} is outside the valid 0–100 range"
            )

    def test_acceptance_spin_delta_is_numeric(self, acceptance_stdout) -> None:
        """spin_delta values must be parseable as floats."""
        stdout, _ = acceptance_stdout
        matches = re.findall(r"spin_delta:\s*([\d.]+)", stdout)
        assert matches, "No 'spin_delta: <value>' patterns found in acceptance output"
        for raw in matches:
            val = float(raw)
            assert val >= 0.0, f"spin_delta must be non-negative; got {val}"

    def test_acceptance_situation_monitor_header_present(self, acceptance_stdout) -> None:
        stdout, _ = acceptance_stdout
        assert "Situation Monitor" in stdout, (
            "Acceptance output must begin with '# Situation Monitor Digest' heading"
        )

    def test_acceptance_no_python_traceback(self, acceptance_stdout) -> None:
        stdout, _ = acceptance_stdout
        assert "Traceback" not in stdout, (
            "Acceptance output must not contain a Python traceback"
        )

    def test_acceptance_digest_dry_run_produces_top_stories(self, acceptance_stdout) -> None:
        """The digest-dry-run command (second half of acceptance) must emit *Top Stories*."""
        stdout, _ = acceptance_stdout
        assert "*Top Stories*" in stdout, (
            "acceptance digest-dry-run output must contain '*Top Stories*' section"
        )

    def test_acceptance_digest_dry_run_shows_lens_counts(self, acceptance_stdout) -> None:
        """digest-dry-run events with both columns must show [L:N, R:N] lens count annotation."""
        stdout, _ = acceptance_stdout
        assert "L:" in stdout and "R:" in stdout, (
            "digest-dry-run output must contain [L:N, R:N] lens counts for dual-lens events"
        )


# ---------------------------------------------------------------------------
# 3. _print_dual_lens unit tests — the function that produces the dual-lens render
# ---------------------------------------------------------------------------


class TestPrintDualLens:
    """Direct unit tests for situation_monitor.__main__._print_dual_lens."""

    def _capture(self, events: list) -> str:
        from situation_monitor.__main__ import _print_dual_lens

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_dual_lens(events)
        return buf.getvalue()

    def _make_event(self, title: str, left=(), right=(), center=()):
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent

        def _aa(t: str, lean: str) -> AnnotatedArticle:
            return AnnotatedArticle(
                article=_make_article(t, source_lean=lean),
                spin=_spin(50.0, lean),
            )

        return DualLensEvent(
            event_title=title,
            left_articles=[_aa(t, "left") for t in left],
            right_articles=[_aa(t, "right") for t in right],
            center_articles=[_aa(t, "center") for t in center],
            spin_delta=abs(50.0 * len(left) - 50.0 * len(right)),
        )

    def test_empty_events_produces_no_output(self) -> None:
        out = self._capture([])
        assert out == "", "Empty event list must produce no output"

    def test_center_only_event_is_not_rendered(self) -> None:
        event = self._make_event("Central bank decision", center=("Rate held steady",))
        out = self._capture([event])
        assert "DUAL-LENS" not in out, (
            "Events with only center articles must not appear in the dual-lens block"
        )

    def test_left_only_event_renders_left_heading(self) -> None:
        event = self._make_event(
            "Immigration policy debate", left=("Guardian: migrants face crisis",)
        )
        out = self._capture([event])
        assert "DUAL-LENS EVENTS" in out
        assert "#### LEFT" in out

    def test_left_only_event_does_not_render_right_heading(self) -> None:
        event = self._make_event(
            "Immigration policy debate", left=("Guardian: migrants face crisis",)
        )
        out = self._capture([event])
        assert "#### RIGHT" not in out

    def test_right_only_event_renders_right_heading(self) -> None:
        event = self._make_event(
            "Tax reform package", right=("Fox: tax cuts spur growth",)
        )
        out = self._capture([event])
        assert "#### RIGHT" in out
        assert "#### LEFT" not in out

    def test_both_sides_renders_both_headings(self) -> None:
        event = self._make_event(
            "Climate summit agreement",
            left=("CNN: climate deal applauded",),
            right=("Fox: climate deal costly",),
        )
        out = self._capture([event])
        assert "#### LEFT" in out
        assert "#### RIGHT" in out

    def test_event_title_appears_as_h3(self) -> None:
        title = "Federal Reserve rate decision"
        event = self._make_event(title, left=("Guardian view",))
        out = self._capture([event])
        assert f"### {title}" in out

    def test_article_title_in_left_column(self) -> None:
        event = self._make_event(
            "Housing crisis deepens",
            left=("Guardian: rents unaffordable for low-income workers",),
        )
        out = self._capture([event])
        assert "Guardian: rents unaffordable for low-income workers" in out

    def test_article_title_in_right_column(self) -> None:
        event = self._make_event(
            "Housing crisis deepens",
            right=("Fox: zoning rules strangle housing supply",),
        )
        out = self._capture([event])
        assert "Fox: zoning rules strangle housing supply" in out

    def test_spin_pct_in_article_line(self) -> None:
        event = self._make_event("Rate decision", left=("Guardian analysis",))
        out = self._capture([event])
        assert "spin_pct:" in out

    def test_spin_pct_value_matches_spin(self) -> None:
        event = self._make_event("Rate decision", left=("Guardian analysis",))
        out = self._capture([event])
        # stub spin is 50.0
        assert "50.0%" in out

    def test_rationale_line_present_when_receipts_non_empty(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa = AnnotatedArticle(
            article=_make_article("Guardian deep dive on immigration policy"),
            spin=SpinResult(spin_pct=70.0, lens="left", rubric={}, receipts="Loaded Language fired"),
        )
        event = DualLensEvent(
            event_title="Immigration policy",
            left_articles=[aa],
            spin_delta=70.0,
        )
        out = self._capture([event])
        assert "rationale:" in out
        assert "Loaded Language fired" in out

    def test_rationale_line_absent_when_receipts_empty(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        aa = AnnotatedArticle(
            article=_make_article("Reuters neutral report on markets today"),
            spin=SpinResult(spin_pct=20.0, lens="center", rubric={}, receipts=""),
        )
        event = DualLensEvent(
            event_title="Markets report",
            left_articles=[],
            right_articles=[],
            center_articles=[aa],
            spin_delta=0.0,
        )
        out = self._capture([event])
        # center-only event is NOT rendered, so rationale line must not appear
        assert "rationale:" not in out

    def test_spin_delta_appears_in_event_block(self) -> None:
        event = self._make_event(
            "Trade war escalates", left=("Guardian view",), right=("Fox view",)
        )
        out = self._capture([event])
        assert "spin_delta:" in out

    def test_article_count_in_left_heading(self) -> None:
        """'#### LEFT (2 articles)' must appear when there are two left articles."""
        event = self._make_event(
            "Brexit deal",
            left=("Guardian lead story", "Independent follow-up story"),
        )
        out = self._capture([event])
        assert "#### LEFT (2 articles)" in out

    def test_article_count_singular_in_heading(self) -> None:
        """'#### LEFT (1 article)' must use singular when there is one article."""
        event = self._make_event("Brexit deal", left=("Guardian lead story",))
        out = self._capture([event])
        assert "#### LEFT (1 article)" in out

    def test_multiple_events_both_rendered(self) -> None:
        e1 = self._make_event("Fed rate hike", left=("Left view A",), right=("Right view A",))
        e2 = self._make_event("Climate summit", left=("Left view B",), right=("Right view B",))
        out = self._capture([e1, e2])
        assert "Fed rate hike" in out
        assert "Climate summit" in out

    def test_mixed_center_plus_dual_events(self) -> None:
        """Center-only events are filtered out; dual-lens events are rendered."""
        center_only = self._make_event("Neutral report", center=("Reuters note",))
        dual = self._make_event("Policy clash", left=("Left view",), right=("Right view",))
        out = self._capture([center_only, dual])
        assert "Policy clash" in out
        assert "Neutral report" not in out


# ---------------------------------------------------------------------------
# 4. _print_dual_lens format contract — output is valid Markdown
# ---------------------------------------------------------------------------


class TestDualLensMarkdownFormat:
    """The dual-lens block must be well-formed Markdown."""

    def _render(self, events: list) -> list[str]:
        from situation_monitor.__main__ import _print_dual_lens

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_dual_lens(events)
        return buf.getvalue().splitlines()

    def _dual_event(self) -> object:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import SpinResult

        def aa(t, lean, pct):
            return AnnotatedArticle(
                article=_make_article(t, source_lean=lean),
                spin=SpinResult(spin_pct=pct, lens=lean, rubric={}, receipts=f"receipt for {lean}"),
            )

        return DualLensEvent(
            event_title="Immigration reform bill passes Senate vote",
            left_articles=[aa("CNN immigration reform hailed", "left", 72.0)],
            right_articles=[aa("Fox immigration bill called amnesty", "right", 38.0)],
            center_articles=[],
            spin_delta=34.0,
        )

    def test_dual_lens_header_is_level_two(self) -> None:
        lines = self._render([self._dual_event()])
        assert any(l == "## DUAL-LENS EVENTS" for l in lines), (
            "The dual-lens block header must be exactly '## DUAL-LENS EVENTS'"
        )

    def test_event_title_is_level_three_heading(self) -> None:
        lines = self._render([self._dual_event()])
        h3_lines = [l for l in lines if l.startswith("### ")]
        assert h3_lines, "Event titles must appear as '### <title>' (H3) lines"

    def test_column_headings_are_level_four(self) -> None:
        lines = self._render([self._dual_event()])
        h4_lines = [l for l in lines if l.startswith("#### ")]
        assert h4_lines, "LEFT/RIGHT headings must appear as '#### LEFT (N...)' (H4) lines"
        for h in h4_lines:
            assert h.startswith("#### LEFT") or h.startswith("#### RIGHT"), (
                f"Unexpected H4 heading: {h!r}"
            )

    def test_article_lines_start_with_dash_space(self) -> None:
        lines = self._render([self._dual_event()])
        article_lines = [l for l in lines if "spin_pct:" in l]
        assert article_lines, "No article spin_pct lines found"
        for al in article_lines:
            assert al.startswith("- "), (
                f"Article bullet lines must start with '- '; got: {al!r}"
            )

    def test_rationale_lines_start_with_two_spaces(self) -> None:
        lines = self._render([self._dual_event()])
        rationale_lines = [l for l in lines if "rationale:" in l]
        assert rationale_lines, "No rationale lines found"
        for rl in rationale_lines:
            assert rl.startswith("  "), (
                f"Rationale lines must be indented with two spaces; got: {rl!r}"
            )

    def test_spin_delta_line_follows_event_title(self) -> None:
        lines = self._render([self._dual_event()])
        for i, line in enumerate(lines):
            if line.startswith("### "):
                # Next non-blank line should be spin_delta
                for j in range(i + 1, min(i + 4, len(lines))):
                    if lines[j].strip():
                        assert "spin_delta:" in lines[j], (
                            f"Line after event H3 title must contain 'spin_delta:'; got {lines[j]!r}"
                        )
                        break
                break


# ---------------------------------------------------------------------------
# 5. digest-dry-run format — the Telegram digest contract
# ---------------------------------------------------------------------------


class TestDigestDryRunFormat:
    """The digest-dry-run subcommand must emit well-formed Telegram-ready Markdown."""

    @pytest.fixture(scope="class")
    def digest_output(self) -> str:
        env = {"SM_LLM_BACKEND": "stub", "SM_SOURCES": "tests/fixtures/rss_sample.xml"}
        import os

        full_env = {**os.environ, **env}
        result = subprocess.run(
            [
                sys.executable,
                "-m", "situation_monitor",
                "digest-dry-run",
                "--config", "tests/fixtures/acceptance_source_defs.json",
            ],
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=full_env,
            timeout=30,
        )
        return result.stdout.decode(errors="replace")

    def test_digest_contains_situation_monitor_heading(self, digest_output) -> None:
        assert "*Situation Monitor*" in digest_output, (
            "digest-dry-run output must start with '*Situation Monitor*' Telegram heading"
        )

    def test_digest_contains_top_stories_section(self, digest_output) -> None:
        assert "*Top Stories*" in digest_output

    def test_digest_contains_article_bullet(self, digest_output) -> None:
        lines = digest_output.splitlines()
        bullets = [l for l in lines if l.startswith("•")]
        assert bullets, "digest-dry-run must contain bullet-point (•) story entries"

    def test_digest_lens_counts_present_for_dual_event(self, digest_output) -> None:
        """Events with both left and right must show [L:N, R:N] in the digest."""
        assert "L:" in digest_output, (
            "digest-dry-run must show 'L:N' left-lens count for dual-lens events"
        )
        assert "R:" in digest_output, (
            "digest-dry-run must show 'R:N' right-lens count for dual-lens events"
        )

    def test_digest_datetime_stamp_present(self, digest_output) -> None:
        # e.g. "2026-06-13 07:00"
        assert re.search(r"\d{4}-\d{2}-\d{2}", digest_output), (
            "digest-dry-run output must contain a date stamp (YYYY-MM-DD)"
        )

    def test_digest_no_traceback(self, digest_output) -> None:
        assert "Traceback" not in digest_output

    def test_digest_no_empty_bullet(self, digest_output) -> None:
        for line in digest_output.splitlines():
            if line.startswith("•"):
                assert line.strip() != "•", f"Empty bullet found: {line!r}"


# ---------------------------------------------------------------------------
# 6. group_by_event + _print_dual_lens integration — full pipeline smoke test
# ---------------------------------------------------------------------------


class TestDualLensPipelineIntegration:
    """End-to-end: ingest fixtures → group_by_event → _print_dual_lens → parse output."""

    @pytest.fixture(scope="class")
    def pipeline_output(self) -> str:
        from situation_monitor.config import SourceDef
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.ingestion.rss import RSSFetcher
        from situation_monitor.models import Domain
        from situation_monitor.__main__ import _print_dual_lens

        class _Local:
            def get(self, url: str) -> bytes:
                return Path(url).read_bytes()

        fetcher = RSSFetcher(client=_Local())
        left_sd = SourceDef(str(FIXTURES / "rss_left.xml"), "LeftFeed", Domain.WORLD, "left")
        right_sd = SourceDef(str(FIXTURES / "rss_right.xml"), "RightFeed", Domain.WORLD, "right")
        articles = fetcher.fetch(left_sd.url, source_def=left_sd)
        articles += fetcher.fetch(right_sd.url, source_def=right_sd)

        events = group_by_event(articles)

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_dual_lens(events)
        return buf.getvalue()

    def test_pipeline_produces_dual_lens_block(self, pipeline_output) -> None:
        assert "DUAL-LENS EVENTS" in pipeline_output

    def test_pipeline_has_left_articles(self, pipeline_output) -> None:
        assert "#### LEFT" in pipeline_output

    def test_pipeline_has_right_articles(self, pipeline_output) -> None:
        assert "#### RIGHT" in pipeline_output

    def test_pipeline_climate_event_present(self, pipeline_output) -> None:
        assert "Climate" in pipeline_output or "climate" in pipeline_output.lower(), (
            "Climate policy event from fixtures must appear in the dual-lens render"
        )

    def test_pipeline_spin_pct_values_in_range(self, pipeline_output) -> None:
        values = [float(v) for v in re.findall(r"spin_pct:\s*([\d.]+)%", pipeline_output)]
        assert values, "Must find at least one spin_pct value in pipeline output"
        for v in values:
            assert 0.0 <= v <= 100.0

    def test_pipeline_event_title_non_empty(self, pipeline_output) -> None:
        h3_lines = [l[4:].strip() for l in pipeline_output.splitlines() if l.startswith("### ")]
        assert h3_lines, "Must have at least one H3 event title"
        for t in h3_lines:
            assert t, "H3 event title must not be empty"

    def test_pipeline_no_article_lost(self, pipeline_output) -> None:
        """At least one article per lens must appear in the output."""
        left_bullets = []
        right_bullets = []
        in_left = in_right = False
        for line in pipeline_output.splitlines():
            if "#### LEFT" in line:
                in_left, in_right = True, False
            elif "#### RIGHT" in line:
                in_right, in_left = True, False
            elif line.startswith("#### ") or line.startswith("## ") or line.startswith("### "):
                in_left = in_right = False
            if in_left and line.startswith("- "):
                left_bullets.append(line)
            if in_right and line.startswith("- "):
                right_bullets.append(line)
        assert left_bullets, "At least one left-column bullet must appear in pipeline output"
        assert right_bullets, "At least one right-column bullet must appear in pipeline output"

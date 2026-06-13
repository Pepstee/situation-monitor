"""Programmatic guard for JUDGE_RUBRIC.md structure.

Parses every row of the rubric without inference, asserts:
  - all four sections are present
  - every comparison section (Ground-News, AllSides, Terminal-Market) has ≥ 3 PASS rows
  - Core-Flow has ≥ 6 step rows
  - every cited file path exists on disk relative to the project root
  - every row conforms to the required "- PASS/FAIL <desc> — <file>:<fn>" format
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
RUBRIC_FILE = PROJECT_ROOT / "JUDGE_RUBRIC.md"

EXPECTED_SECTIONS = {"Ground-News", "AllSides", "Terminal-Market", "Core-Flow"}
COMPARISON_SECTIONS = {"Ground-News", "AllSides", "Terminal-Market"}
MIN_PASS_PER_COMPARISON = 3
MIN_CORE_FLOW_STEPS = 6

# Pattern for a valid rubric row:
# "- PASS some description — path/to/file.py:function_name"
ROW_RE = re.compile(
    r"^-\s+"
    r"(PASS|FAIL)"
    r"\s+"
    r"(.+?)"
    r"\s+—\s+"
    r"([\w/._-]+\.py)"
    r":"
    r"(\w+)"
    r"\s*$"
)


class RubricRow(NamedTuple):
    status: str
    description: str
    file_path: str
    function: str


def _parse_rubric() -> dict[str, list[RubricRow]]:
    """Parse JUDGE_RUBRIC.md → {section_name: [RubricRow, ...]}."""
    text = RUBRIC_FILE.read_text()
    sections: dict[str, list[RubricRow]] = {}
    current: str | None = None

    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections[current] = []
        elif current is not None and line.startswith("- "):
            m = ROW_RE.match(line)
            if m:
                sections[current].append(
                    RubricRow(
                        status=m.group(1),
                        description=m.group(2).strip(),
                        file_path=m.group(3).strip(),
                        function=m.group(4).strip(),
                    )
                )

    return sections


# ---------------------------------------------------------------------------
# Cached parse result — shared across all tests, zero network calls
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def rubric_sections() -> dict[str, list[RubricRow]]:
    return _parse_rubric()


@pytest.fixture(scope="module")
def all_rows(rubric_sections) -> list[RubricRow]:
    return [row for rows in rubric_sections.values() for row in rows]


# ---------------------------------------------------------------------------
# 1. File existence and basic well-formedness
# ---------------------------------------------------------------------------


class TestRubricFileExists:
    def test_rubric_file_is_present(self) -> None:
        assert RUBRIC_FILE.exists(), (
            f"JUDGE_RUBRIC.md must exist at {RUBRIC_FILE}"
        )

    def test_rubric_file_is_non_empty(self) -> None:
        assert RUBRIC_FILE.read_text().strip(), "JUDGE_RUBRIC.md must not be empty"

    def test_rubric_has_h1_title(self) -> None:
        first_content_line = next(
            (l for l in RUBRIC_FILE.read_text().splitlines() if l.strip()),
            "",
        )
        assert first_content_line.startswith("# "), (
            f"JUDGE_RUBRIC.md must start with an H1 heading; got {first_content_line!r}"
        )

    def test_rubric_contains_em_dash_separator(self) -> None:
        """Rows cite files with ' — ' (em dash); the file must contain at least one."""
        assert " — " in RUBRIC_FILE.read_text(), (
            "JUDGE_RUBRIC.md must contain ' — ' separating descriptions from file citations"
        )


# ---------------------------------------------------------------------------
# 2. Section presence
# ---------------------------------------------------------------------------


class TestRubricSections:
    def test_all_four_sections_present(self, rubric_sections) -> None:
        missing = EXPECTED_SECTIONS - rubric_sections.keys()
        assert not missing, (
            f"JUDGE_RUBRIC.md is missing required sections: {sorted(missing)}"
        )

    @pytest.mark.parametrize("section", sorted(EXPECTED_SECTIONS))
    def test_section_has_at_least_one_row(self, rubric_sections, section) -> None:
        assert rubric_sections.get(section), (
            f"Section '{section}' exists but has no parseable rows"
        )

    def test_sections_appear_in_expected_order(self) -> None:
        """Ground-News must appear before AllSides which must appear before Core-Flow."""
        text = RUBRIC_FILE.read_text()
        positions = {name: text.find(f"## {name}") for name in EXPECTED_SECTIONS}
        for name, pos in positions.items():
            assert pos >= 0, f"Section '{name}' not found as an H2 heading"
        assert positions["Ground-News"] < positions["AllSides"], (
            "Ground-News must precede AllSides in the rubric"
        )
        assert positions["AllSides"] < positions["Terminal-Market"], (
            "AllSides must precede Terminal-Market in the rubric"
        )
        assert positions["Terminal-Market"] < positions["Core-Flow"], (
            "Terminal-Market must precede Core-Flow in the rubric"
        )


# ---------------------------------------------------------------------------
# 3. Row format integrity
# ---------------------------------------------------------------------------


class TestRowFormat:
    def test_every_bullet_row_matches_pattern(self) -> None:
        """No row starting with '- PASS' or '- FAIL' is allowed to be malformed."""
        text = RUBRIC_FILE.read_text()
        malformed = []
        for line in text.splitlines():
            if not (line.startswith("- PASS") or line.startswith("- FAIL")):
                continue
            if not ROW_RE.match(line):
                malformed.append(line)
        assert not malformed, (
            f"The following rows do not match '- PASS/FAIL <desc> — <file.py>:<fn>':\n"
            + "\n".join(f"  {l}" for l in malformed)
        )

    def test_status_is_only_pass_or_fail(self, all_rows) -> None:
        bad = [r for r in all_rows if r.status not in ("PASS", "FAIL")]
        assert not bad, (
            f"Rows with invalid status (must be PASS or FAIL): {bad}"
        )

    def test_descriptions_are_non_empty(self, all_rows) -> None:
        empty = [r for r in all_rows if not r.description]
        assert not empty, f"Rows with empty descriptions: {empty}"

    def test_function_names_are_non_empty(self, all_rows) -> None:
        empty = [r for r in all_rows if not r.function]
        assert not empty, f"Rows with empty function names: {empty}"

    def test_function_names_are_valid_python_identifiers(self, all_rows) -> None:
        bad = [r for r in all_rows if not r.function.replace("_", "a").isalnum()]
        assert not bad, (
            f"Function names must be valid Python identifiers; bad rows: {bad}"
        )

    def test_file_paths_end_in_py(self, all_rows) -> None:
        non_py = [r for r in all_rows if not r.file_path.endswith(".py")]
        assert not non_py, (
            f"Cited paths must end in '.py'; non-conforming rows: {non_py}"
        )

    def test_total_row_count_is_positive(self, all_rows) -> None:
        assert len(all_rows) > 0, "JUDGE_RUBRIC.md must contain at least one parsed row"


# ---------------------------------------------------------------------------
# 4. PASS-count thresholds per comparison section
# ---------------------------------------------------------------------------


class TestComparisonSectionPassCounts:
    @pytest.mark.parametrize("section", sorted(COMPARISON_SECTIONS))
    def test_comparison_section_has_at_least_3_pass_rows(self, rubric_sections, section) -> None:
        rows = rubric_sections.get(section, [])
        pass_count = sum(1 for r in rows if r.status == "PASS")
        assert pass_count >= MIN_PASS_PER_COMPARISON, (
            f"Section '{section}' has only {pass_count} PASS rows; "
            f"required ≥ {MIN_PASS_PER_COMPARISON}"
        )

    @pytest.mark.parametrize("section", sorted(COMPARISON_SECTIONS))
    def test_comparison_section_has_no_unparsed_pass_lines(self, section) -> None:
        """Every line starting with '- PASS' in a comparison section must be parseable."""
        text = RUBRIC_FILE.read_text()
        in_section = False
        unparsed = []
        for line in text.splitlines():
            if line == f"## {section}":
                in_section = True
                continue
            if in_section and line.startswith("## "):
                break
            if in_section and (line.startswith("- PASS") or line.startswith("- FAIL")):
                if not ROW_RE.match(line):
                    unparsed.append(line)
        assert not unparsed, (
            f"Section '{section}' has unparseable bullet rows:\n"
            + "\n".join(f"  {l}" for l in unparsed)
        )


# ---------------------------------------------------------------------------
# 5. Core-Flow step count
# ---------------------------------------------------------------------------


class TestCoreFlowSteps:
    def test_core_flow_has_at_least_6_steps(self, rubric_sections) -> None:
        rows = rubric_sections.get("Core-Flow", [])
        assert len(rows) >= MIN_CORE_FLOW_STEPS, (
            f"Core-Flow section has {len(rows)} step(s); required ≥ {MIN_CORE_FLOW_STEPS}. "
            "Add more PASS rows covering the full ingest→cluster→score→delta→alert→user pipeline."
        )

    def test_core_flow_all_rows_are_pass(self, rubric_sections) -> None:
        rows = rubric_sections.get("Core-Flow", [])
        fails = [r for r in rows if r.status != "PASS"]
        assert not fails, (
            f"Core-Flow section must contain only PASS rows; found FAIL rows: {fails}"
        )

    def test_core_flow_covers_ingestion(self, rubric_sections) -> None:
        rows = rubric_sections.get("Core-Flow", [])
        descriptions = " ".join(r.description.lower() for r in rows)
        assert "rss" in descriptions or "ingest" in descriptions or "fetch" in descriptions, (
            "Core-Flow section must cover the ingestion step (RSS/fetch/ingest)"
        )

    def test_core_flow_covers_dual_lens_grouping(self, rubric_sections) -> None:
        rows = rubric_sections.get("Core-Flow", [])
        descriptions = " ".join(r.description.lower() for r in rows)
        assert "dual" in descriptions or "group" in descriptions or "event" in descriptions, (
            "Core-Flow section must cover the dual-lens grouping step"
        )

    def test_core_flow_covers_digest(self, rubric_sections) -> None:
        rows = rubric_sections.get("Core-Flow", [])
        descriptions = " ".join(r.description.lower() for r in rows)
        assert "digest" in descriptions or "telegram" in descriptions or "notification" in descriptions, (
            "Core-Flow section must cover the digest/notification step"
        )


# ---------------------------------------------------------------------------
# 6. Cited files exist on disk
# ---------------------------------------------------------------------------


class TestCitedFilesExist:
    def _unique_file_paths(self, all_rows) -> list[str]:
        return list({r.file_path for r in all_rows})

    def test_every_cited_file_exists_on_disk(self, all_rows) -> None:
        missing = []
        for row in all_rows:
            full = PROJECT_ROOT / row.file_path
            if not full.exists():
                missing.append(f"{row.file_path}  (cited as {row.function})")
        assert not missing, (
            "The following files cited in JUDGE_RUBRIC.md do not exist on disk:\n"
            + "\n".join(f"  {p}" for p in missing)
        )

    def test_cited_files_are_regular_files_not_directories(self, all_rows) -> None:
        dirs = []
        for row in all_rows:
            full = PROJECT_ROOT / row.file_path
            if full.exists() and full.is_dir():
                dirs.append(row.file_path)
        assert not dirs, (
            f"Cited paths must be files, not directories: {dirs}"
        )

    def test_bias_py_is_cited(self, all_rows) -> None:
        cited = {r.file_path for r in all_rows}
        assert "situation_monitor/bias.py" in cited, (
            "bias.py must be cited at least once (Ground-News and AllSides depend on it)"
        )

    def test_dual_lens_py_is_cited(self, all_rows) -> None:
        cited = {r.file_path for r in all_rows}
        assert "situation_monitor/dual_lens.py" in cited, (
            "dual_lens.py must be cited in Core-Flow"
        )

    def test_digest_py_is_cited(self, all_rows) -> None:
        cited = {r.file_path for r in all_rows}
        assert "situation_monitor/digest.py" in cited, (
            "digest.py must be cited in Core-Flow"
        )

    @pytest.mark.parametrize("path", [
        "situation_monitor/bias.py",
        "situation_monitor/polymarket.py",
        "situation_monitor/__main__.py",
        "situation_monitor/dual_lens.py",
        "situation_monitor/digest.py",
        "situation_monitor/dashboard.py",
        "situation_monitor/ingestion/rss.py",
    ])
    def test_expected_cited_file_exists(self, path) -> None:
        """Every file expected to appear in the rubric must exist on disk."""
        full = PROJECT_ROOT / path
        assert full.exists(), (
            f"Expected cited file {path!r} does not exist at {full}"
        )


# ---------------------------------------------------------------------------
# 7. Function reference integrity — functions named in rubric are importable
# ---------------------------------------------------------------------------


class TestFunctionReferences:
    """Cited functions must actually exist in the named module (no stubs, no dead refs)."""

    def _module_text(self, file_path: str) -> str:
        return (PROJECT_ROOT / file_path).read_text()

    def test_all_cited_functions_appear_in_source(self, all_rows) -> None:
        """Each 'file.py:function' citation must have 'def function' or 'class function' in source."""
        missing = []
        for row in all_rows:
            full = PROJECT_ROOT / row.file_path
            if not full.exists():
                continue  # covered by TestCitedFilesExist
            src = full.read_text()
            fn = row.function
            if f"def {fn}" not in src and f"class {fn}" not in src:
                missing.append(f"{row.file_path}:{fn}")
        assert not missing, (
            "The following cited functions/classes are NOT defined in their cited file:\n"
            + "\n".join(f"  {ref}" for ref in missing)
        )

    def test_get_source_lean_defined_in_bias_py(self) -> None:
        src = (PROJECT_ROOT / "situation_monitor/bias.py").read_text()
        assert "def get_source_lean" in src, (
            "get_source_lean must be defined in situation_monitor/bias.py"
        )

    def test_get_source_reliability_defined_in_bias_py(self) -> None:
        src = (PROJECT_ROOT / "situation_monitor/bias.py").read_text()
        assert "def get_source_reliability" in src, (
            "get_source_reliability must be defined in situation_monitor/bias.py"
        )

    def test_group_by_event_defined_in_dual_lens_py(self) -> None:
        src = (PROJECT_ROOT / "situation_monitor/dual_lens.py").read_text()
        assert "def group_by_event" in src, (
            "group_by_event must be defined in situation_monitor/dual_lens.py"
        )

    def test_daily_digest_defined_in_digest_py(self) -> None:
        src = (PROJECT_ROOT / "situation_monitor/digest.py").read_text()
        assert "def daily_digest" in src, (
            "daily_digest must be defined in situation_monitor/digest.py"
        )

    def test_make_app_defined_in_dashboard_py(self) -> None:
        src = (PROJECT_ROOT / "situation_monitor/dashboard.py").read_text()
        assert "def make_app" in src, (
            "make_app must be defined in situation_monitor/dashboard.py"
        )


# ---------------------------------------------------------------------------
# 8. Edge-case / adversarial: what the tests catch when rubric is wrong
# ---------------------------------------------------------------------------


class TestRubricGuardIsNotTrivial:
    """Sanity checks that the guard is real — if these pass, the guard is meaningful."""

    def test_pass_count_is_not_automatically_true(self, rubric_sections) -> None:
        """There are rows to count, so MIN_PASS_PER_COMPARISON is not vacuously satisfied."""
        for section in COMPARISON_SECTIONS:
            rows = rubric_sections.get(section, [])
            assert rows, (
                f"Section '{section}' is empty — PASS count check would be vacuously satisfied"
            )

    def test_cited_files_are_actually_checked(self, all_rows) -> None:
        """At least five distinct files are cited, making the on-disk check non-trivial."""
        unique_files = {r.file_path for r in all_rows}
        assert len(unique_files) >= 5, (
            f"Only {len(unique_files)} distinct file(s) cited; expected ≥ 5 to make "
            "the on-disk existence check meaningful"
        )

    def test_rubric_has_enough_total_rows(self, all_rows) -> None:
        """With four sections and at least 3 PASS rows each, we expect ≥ 12 rows."""
        assert len(all_rows) >= 12, (
            f"Expected ≥ 12 rows across all sections; found {len(all_rows)}"
        )

    def test_each_section_row_count_is_individually_tracked(self, rubric_sections) -> None:
        """Section boundaries are parsed correctly — row counts per section differ from total."""
        total = sum(len(rows) for rows in rubric_sections.values())
        for section, rows in rubric_sections.items():
            assert len(rows) < total, (
                f"Section '{section}' appears to absorb all rows; "
                "section boundary parsing may be broken"
            )

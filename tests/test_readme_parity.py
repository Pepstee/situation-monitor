"""
Programmatic check of README.md comparison tables and core-flow walkthrough.

Verifies:
  1. A 'Ground News' comparison table with header row and ≥ 4 data rows.
  2. An 'AllSides' or 'MBFC' comparison table with header row and ≥ 4 data rows.
  3. A terminal/market dashboard comparison table with header row and ≥ 3 data rows.
  4. The core-flow sequence 'one event' or 'one story' → 'lens' or 'dual' → 'spin'
     → 'practical' or 'takeaway' appears in the README in that order.

Uses only stdlib (re, pathlib) — no network, no LLM.
"""
from __future__ import annotations

import re
import pathlib

import pytest

README_PATH = pathlib.Path(__file__).parent.parent / "README.md"

_TABLE_ROW_RE = re.compile(r"^\|.+\|$")
_TABLE_SEP_RE = re.compile(r"^\|[\s\-:|]+\|$")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _parse_tables(text: str) -> list[tuple[str, list[str]]]:
    """Return (header_line, [data_row_lines]) for every markdown table in text."""
    lines = text.splitlines()
    tables: list[tuple[str, list[str]]] = []
    i = 0
    while i < len(lines):
        row = lines[i].strip()
        if _TABLE_ROW_RE.match(row):
            next_idx = i + 1
            if next_idx < len(lines) and _TABLE_SEP_RE.match(lines[next_idx].strip()):
                data: list[str] = []
                j = next_idx + 1
                while j < len(lines) and _TABLE_ROW_RE.match(lines[j].strip()):
                    data.append(lines[j].strip())
                    j += 1
                tables.append((row, data))
                i = j
                continue
        i += 1
    return tables


def _find_table(*keywords: str, tables: list[tuple[str, list[str]]]) -> tuple[str, list[str]] | tuple[None, None]:
    """Return first table whose header row contains any keyword (case-insensitive)."""
    for header, rows in tables:
        if any(kw.lower() in header.lower() for kw in keywords):
            return header, rows
    return None, None


def _first_pos(text: str, *phrases: str) -> int:
    """Lowest character offset of any phrase in text (case-insensitive), or -1."""
    ltext = text.lower()
    positions = [ltext.find(p.lower()) for p in phrases if ltext.find(p.lower()) != -1]
    return min(positions) if positions else -1


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def readme() -> str:
    assert README_PATH.exists(), f"README not found at {README_PATH}"
    return README_PATH.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def tables(readme: str) -> list[tuple[str, list[str]]]:
    return _parse_tables(readme)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Ground News comparison table
# ─────────────────────────────────────────────────────────────────────────────


class TestGroundNewsParity:
    """README must contain a Ground News comparison table with ≥ 4 data rows."""

    def test_table_exists(self, tables: list[tuple[str, list[str]]]) -> None:
        header, _ = _find_table("Ground News", tables=tables)
        assert header is not None, (
            "No markdown table with 'Ground News' in its header row found in README.md"
        )

    def test_header_row_is_non_trivial(self, tables: list[tuple[str, list[str]]]) -> None:
        header, _ = _find_table("Ground News", tables=tables)
        assert header is not None
        cols = [c.strip() for c in header.strip("|").split("|") if c.strip()]
        assert len(cols) >= 2, (
            f"Ground News table header must have ≥ 2 columns; got: {header}"
        )

    def test_at_least_four_data_rows(self, tables: list[tuple[str, list[str]]]) -> None:
        _, rows = _find_table("Ground News", tables=tables)
        assert rows is not None, "Ground News table not found"
        assert len(rows) >= 4, (
            f"Ground News comparison table must have ≥ 4 data rows; found {len(rows)}"
        )

    def test_data_rows_have_populated_columns(self, tables: list[tuple[str, list[str]]]) -> None:
        _, rows = _find_table("Ground News", tables=tables)
        assert rows is not None
        for i, row in enumerate(rows[:4]):
            cols = [c.strip() for c in row.strip("|").split("|") if c.strip()]
            assert len(cols) >= 2, (
                f"Ground News table row {i} must have ≥ 2 populated columns; got: {row}"
            )

    def test_all_four_required_rows_non_empty(self, tables: list[tuple[str, list[str]]]) -> None:
        _, rows = _find_table("Ground News", tables=tables)
        assert rows is not None
        non_empty = [r for r in rows if r.strip().strip("|").strip()]
        assert len(non_empty) >= 4, (
            f"Ground News table needs ≥ 4 non-empty data rows; found {len(non_empty)}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. AllSides / MBFC bias methodology table
# ─────────────────────────────────────────────────────────────────────────────


class TestAllSidesMBFCParity:
    """README must contain an AllSides or MBFC comparison table with ≥ 4 data rows."""

    def test_table_exists(self, tables: list[tuple[str, list[str]]]) -> None:
        header, _ = _find_table("AllSides", "MBFC", tables=tables)
        assert header is not None, (
            "No markdown table with 'AllSides' or 'MBFC' in its header row found in README.md"
        )

    def test_header_row_is_non_trivial(self, tables: list[tuple[str, list[str]]]) -> None:
        header, _ = _find_table("AllSides", "MBFC", tables=tables)
        assert header is not None
        cols = [c.strip() for c in header.strip("|").split("|") if c.strip()]
        assert len(cols) >= 2, (
            f"AllSides/MBFC table header must have ≥ 2 columns; got: {header}"
        )

    def test_at_least_four_data_rows(self, tables: list[tuple[str, list[str]]]) -> None:
        _, rows = _find_table("AllSides", "MBFC", tables=tables)
        assert rows is not None, "AllSides/MBFC table not found"
        assert len(rows) >= 4, (
            f"AllSides/MBFC comparison table must have ≥ 4 data rows; found {len(rows)}"
        )

    def test_data_rows_have_populated_columns(self, tables: list[tuple[str, list[str]]]) -> None:
        _, rows = _find_table("AllSides", "MBFC", tables=tables)
        assert rows is not None
        for i, row in enumerate(rows[:4]):
            cols = [c.strip() for c in row.strip("|").split("|") if c.strip()]
            assert len(cols) >= 2, (
                f"AllSides/MBFC table row {i} must have ≥ 2 populated columns; got: {row}"
            )

    def test_rubric_dimensions_present(self, tables: list[tuple[str, list[str]]]) -> None:
        """Each of the four MBFC rubric categories must appear in the table body."""
        _, rows = _find_table("AllSides", "MBFC", tables=tables)
        assert rows is not None
        body = " ".join(rows).lower()
        for term in ("loaded", "omission", "sourcing", "emotional"):
            assert term in body, (
                f"AllSides/MBFC table body must contain '{term}' rubric; body excerpt: {body[:200]}"
            )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Terminal / market dashboard comparison table
# ─────────────────────────────────────────────────────────────────────────────


class TestTerminalMarketParity:
    """README must contain a terminal/market dashboard comparison table with ≥ 3 data rows."""

    def test_table_exists(self, tables: list[tuple[str, list[str]]]) -> None:
        header, _ = _find_table("Bloomberg", "Terminal", tables=tables)
        assert header is not None, (
            "No markdown table with 'Bloomberg' or 'Terminal' in its header row found in README.md"
        )

    def test_header_row_is_non_trivial(self, tables: list[tuple[str, list[str]]]) -> None:
        header, _ = _find_table("Bloomberg", "Terminal", tables=tables)
        assert header is not None
        cols = [c.strip() for c in header.strip("|").split("|") if c.strip()]
        assert len(cols) >= 2, (
            f"Terminal/market table header must have ≥ 2 columns; got: {header}"
        )

    def test_at_least_three_data_rows(self, tables: list[tuple[str, list[str]]]) -> None:
        _, rows = _find_table("Bloomberg", "Terminal", tables=tables)
        assert rows is not None, "Terminal/market table not found"
        assert len(rows) >= 3, (
            f"Terminal/market comparison table must have ≥ 3 data rows; found {len(rows)}"
        )

    def test_data_rows_have_populated_columns(self, tables: list[tuple[str, list[str]]]) -> None:
        _, rows = _find_table("Bloomberg", "Terminal", tables=tables)
        assert rows is not None
        for i, row in enumerate(rows[:3]):
            cols = [c.strip() for c in row.strip("|").split("|") if c.strip()]
            assert len(cols) >= 2, (
                f"Terminal/market table row {i} must have ≥ 2 populated columns; got: {row}"
            )

    def test_parity_column_present_in_header(self, tables: list[tuple[str, list[str]]]) -> None:
        header, _ = _find_table("Bloomberg", "Terminal", tables=tables)
        assert header is not None
        assert "parity" in header.lower() or "situation monitor" in header.lower(), (
            f"Terminal table header should include 'Parity' or 'Situation Monitor'; got: {header}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Core-flow sequence
# ─────────────────────────────────────────────────────────────────────────────


class TestCoreFlowSequence:
    """
    The README must describe the core pipeline in order:
    'one event' / 'one story'  →  'lens' / 'dual'  →  'spin'  →  'practical' / 'takeaway'
    """

    def test_event_anchor_present(self, readme: str) -> None:
        pos = _first_pos(readme, "one event", "one story")
        assert pos != -1, (
            "README must contain 'one event' or 'one story' as the core-flow entry point"
        )

    def test_lens_or_dual_present(self, readme: str) -> None:
        pos = _first_pos(readme, "lens", "dual")
        assert pos != -1, (
            "README must mention 'lens' or 'dual' to describe the framing comparison step"
        )

    def test_spin_present(self, readme: str) -> None:
        pos = _first_pos(readme, "spin")
        assert pos != -1, "README must mention 'spin' in the pipeline description"

    def test_practical_or_takeaway_present(self, readme: str) -> None:
        pos = _first_pos(readme, "practical", "takeaway")
        assert pos != -1, (
            "README must mention 'practical' or 'takeaway' in the pipeline description"
        )

    def test_event_precedes_lens_or_dual(self, readme: str) -> None:
        event_pos = _first_pos(readme, "one event", "one story")
        assert event_pos != -1, "README must contain 'one event' or 'one story'"
        tail = readme[event_pos:]
        lens_pos = _first_pos(tail, "lens", "dual")
        assert lens_pos != -1, (
            "'lens' or 'dual' must appear after 'one event'/'one story' in the README"
        )

    def test_lens_or_dual_precedes_spin(self, readme: str) -> None:
        event_pos = _first_pos(readme, "one event", "one story")
        assert event_pos != -1
        tail_after_event = readme[event_pos:]
        lens_pos = _first_pos(tail_after_event, "lens", "dual")
        assert lens_pos != -1
        tail_after_lens = tail_after_event[lens_pos + 1:]
        spin_pos = _first_pos(tail_after_lens, "spin")
        assert spin_pos != -1, (
            "'spin' must appear after 'lens'/'dual' in the core-flow sequence"
        )

    def test_spin_precedes_practical_or_takeaway(self, readme: str) -> None:
        event_pos = _first_pos(readme, "one event", "one story")
        assert event_pos != -1
        tail_after_event = readme[event_pos:]
        lens_pos = _first_pos(tail_after_event, "lens", "dual")
        assert lens_pos != -1
        tail_after_lens = tail_after_event[lens_pos + 1:]
        spin_pos = _first_pos(tail_after_lens, "spin")
        assert spin_pos != -1
        tail_after_spin = tail_after_lens[spin_pos + 1:]
        practical_pos = _first_pos(tail_after_spin, "practical", "takeaway")
        assert practical_pos != -1, (
            "'practical' or 'takeaway' must appear after 'spin' in the core-flow sequence"
        )

    def test_full_sequence_absolute_ordering(self, readme: str) -> None:
        """All four anchors appear in strict document order."""
        event_pos = _first_pos(readme, "one event", "one story")
        assert event_pos != -1, "No 'one event'/'one story' found"

        tail1 = readme[event_pos:]
        rel_lens = _first_pos(tail1, "lens", "dual")
        assert rel_lens != -1, "'lens'/'dual' not found after event anchor"
        lens_abs = event_pos + rel_lens

        tail2 = readme[lens_abs + 1:]
        rel_spin = _first_pos(tail2, "spin")
        assert rel_spin != -1, "'spin' not found after lens/dual"
        spin_abs = lens_abs + 1 + rel_spin

        tail3 = readme[spin_abs + 1:]
        rel_practical = _first_pos(tail3, "practical", "takeaway")
        assert rel_practical != -1, "'practical'/'takeaway' not found after spin"
        practical_abs = spin_abs + 1 + rel_practical

        assert event_pos < lens_abs < spin_abs < practical_abs, (
            f"Core-flow anchors out of order: event@{event_pos}, lens@{lens_abs}, "
            f"spin@{spin_abs}, practical@{practical_abs}"
        )

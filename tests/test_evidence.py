"""Adversarial tests for evidence.py output format.

Runs evidence.py as a real subprocess and inspects the evidence.txt it writes.
Tests can fail: they verify the real pipeline output, not trivial stubs.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
EVIDENCE_SCRIPT = PROJECT_ROOT / "evidence.py"
EVIDENCE_FILE = PROJECT_ROOT / "evidence.txt"

EXPECTED_LABELS = ["DUAL_LENS:", "SPIN_PCT:", "MARKET:", "LIVE_SOURCES:", "LENS_BALANCE:"]


@pytest.fixture(scope="module")
def evidence_run():
    """Run evidence.py once and return the CompletedProcess result."""
    result = subprocess.run(
        [sys.executable, str(EVIDENCE_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=PROJECT_ROOT,
    )
    return result


@pytest.fixture(scope="module")
def evidence_text(evidence_run):
    """Return the content of evidence.txt after the run."""
    assert EVIDENCE_FILE.exists(), "evidence.txt was not created by evidence.py"
    return EVIDENCE_FILE.read_text()


@pytest.fixture(scope="module")
def evidence_lines(evidence_text):
    """Return non-empty lines from evidence.txt."""
    return [line for line in evidence_text.splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# Subprocess execution checks
# ---------------------------------------------------------------------------


def test_evidence_script_exists():
    assert EVIDENCE_SCRIPT.exists(), f"evidence.py not found at {EVIDENCE_SCRIPT}"


def test_evidence_returncode_zero(evidence_run):
    assert evidence_run.returncode == 0, (
        f"evidence.py exited with code {evidence_run.returncode}\n"
        f"stderr: {evidence_run.stderr}"
    )


def test_evidence_produces_output_file(evidence_run):
    assert EVIDENCE_FILE.exists(), "evidence.py did not write evidence.txt"


# ---------------------------------------------------------------------------
# evidence.txt field label presence
# ---------------------------------------------------------------------------


def test_dual_lens_label_present(evidence_text):
    assert "DUAL_LENS:" in evidence_text, "DUAL_LENS: label missing from evidence.txt"


def test_spin_pct_label_present(evidence_text):
    assert "SPIN_PCT:" in evidence_text, "SPIN_PCT: label missing from evidence.txt"


def test_market_label_present(evidence_text):
    assert "MARKET:" in evidence_text, "MARKET: label missing from evidence.txt"


def test_live_sources_label_present(evidence_text):
    assert "LIVE_SOURCES:" in evidence_text, "LIVE_SOURCES: label missing from evidence.txt"


def test_lens_balance_label_present(evidence_text):
    assert "LENS_BALANCE:" in evidence_text, "LENS_BALANCE: label missing from evidence.txt"


def test_all_five_labels_present(evidence_text):
    missing = [label for label in EXPECTED_LABELS if label not in evidence_text]
    assert not missing, f"Missing labels in evidence.txt: {missing}"


# ---------------------------------------------------------------------------
# Field value format checks
# ---------------------------------------------------------------------------


def _get_field_value(lines: list[str], label: str) -> str:
    for line in lines:
        if line.startswith(label):
            return line[len(label):].strip()
    pytest.fail(f"Label '{label}' not found in evidence.txt lines")


def test_spin_pct_contains_digit_then_percent(evidence_lines):
    value = _get_field_value(evidence_lines, "SPIN_PCT:")
    assert re.search(r"\d+%", value), (
        f"SPIN_PCT value '{value}' does not contain a digit followed by '%'"
    )


def test_spin_pct_value_is_integer_percentage(evidence_lines):
    value = _get_field_value(evidence_lines, "SPIN_PCT:")
    assert re.fullmatch(r"\d+%", value), (
        f"SPIN_PCT value '{value}' is not in the expected format '<integer>%'"
    )


def test_dual_lens_value_is_pass_or_fail(evidence_lines):
    value = _get_field_value(evidence_lines, "DUAL_LENS:")
    assert value in ("PASS", "FAIL"), (
        f"DUAL_LENS value '{value}' is not 'PASS' or 'FAIL'"
    )


def test_market_value_is_pass_or_fail(evidence_lines):
    value = _get_field_value(evidence_lines, "MARKET:")
    assert value in ("PASS", "FAIL"), (
        f"MARKET value '{value}' is not 'PASS' or 'FAIL'"
    )


def test_live_sources_value_is_non_negative_integer(evidence_lines):
    value = _get_field_value(evidence_lines, "LIVE_SOURCES:")
    assert re.fullmatch(r"\d+", value), (
        f"LIVE_SOURCES value '{value}' is not a non-negative integer"
    )


def test_lens_balance_has_left_centre_right(evidence_lines):
    value = _get_field_value(evidence_lines, "LENS_BALANCE:")
    assert re.search(r"left=\d+", value), f"LENS_BALANCE missing 'left=<n>': '{value}'"
    assert re.search(r"centre=\d+", value), f"LENS_BALANCE missing 'centre=<n>': '{value}'"
    assert re.search(r"right=\d+", value), f"LENS_BALANCE missing 'right=<n>': '{value}'"


# ---------------------------------------------------------------------------
# Output structure checks
# ---------------------------------------------------------------------------


def test_evidence_file_has_exactly_five_lines(evidence_lines):
    assert len(evidence_lines) == 5, (
        f"evidence.txt should have exactly 5 lines, got {len(evidence_lines)}: {evidence_lines}"
    )


def test_evidence_lines_are_in_expected_order(evidence_lines):
    for i, label in enumerate(EXPECTED_LABELS):
        assert evidence_lines[i].startswith(label), (
            f"Line {i} should start with '{label}', got: '{evidence_lines[i]}'"
        )


def test_evidence_file_ends_with_newline(evidence_text):
    assert evidence_text.endswith("\n"), "evidence.txt should end with a newline"


def test_evidence_stdout_mentions_wrote(evidence_run):
    assert "Wrote" in evidence_run.stdout, (
        f"evidence.py stdout did not mention 'Wrote': {evidence_run.stdout!r}"
    )


def test_evidence_stdout_echoes_all_labels(evidence_run):
    stdout = evidence_run.stdout
    for label in EXPECTED_LABELS:
        assert label in stdout, (
            f"evidence.py stdout does not echo '{label}': {stdout!r}"
        )


# ---------------------------------------------------------------------------
# Parsability of values
# ---------------------------------------------------------------------------


def test_spin_pct_value_parseable_as_int(evidence_lines):
    value = _get_field_value(evidence_lines, "SPIN_PCT:")
    assert value.endswith("%"), f"SPIN_PCT value '{value}' does not end with '%'"
    numeric_part = value.rstrip("%")
    try:
        parsed = int(numeric_part)
    except ValueError:
        pytest.fail(f"SPIN_PCT numeric part '{numeric_part}' is not parseable as int")
    assert 0 <= parsed <= 100, f"SPIN_PCT value {parsed}% is outside [0, 100]"


def test_live_sources_parseable_as_int(evidence_lines):
    value = _get_field_value(evidence_lines, "LIVE_SOURCES:")
    try:
        parsed = int(value)
    except ValueError:
        pytest.fail(f"LIVE_SOURCES value '{value}' is not parseable as int")
    assert parsed >= 0, f"LIVE_SOURCES value {parsed} is negative"


def test_lens_balance_counts_parseable(evidence_lines):
    value = _get_field_value(evidence_lines, "LENS_BALANCE:")
    for key in ("left", "centre", "right"):
        m = re.search(rf"{key}=(\d+)", value)
        assert m is not None, f"'{key}=<n>' not found in LENS_BALANCE: '{value}'"
        count = int(m.group(1))
        assert count >= 0, f"LENS_BALANCE {key} count {count} is negative"

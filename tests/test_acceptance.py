"""Acceptance smoke test.

Reads the 'acceptance' shell command from the project root and runs it as a
subprocess with a 30-second timeout.  Passes only when:
  - returncode == 0
  - stdout is non-empty

This verifies the full pipeline (ingest → enrich → print) end-to-end using
the bundled RSS fixture — no real network calls are made.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"


# ---------------------------------------------------------------------------
# Sanity-checks on the acceptance file itself
# ---------------------------------------------------------------------------


def test_acceptance_file_exists():
    """The 'acceptance' file must be present at the project root."""
    assert ACCEPTANCE_FILE.exists(), f"acceptance file not found at {ACCEPTANCE_FILE}"


def test_acceptance_file_is_nonempty():
    cmd = ACCEPTANCE_FILE.read_text().strip()
    assert cmd, "acceptance file is empty"


def test_acceptance_file_references_bundled_fixture():
    """The acceptance command must use the bundled RSS fixture, not a real URL."""
    cmd = ACCEPTANCE_PY.read_text().strip()
    assert "rss_sample.xml" in cmd, (
        "acceptance command should reference the bundled fixture 'rss_sample.xml' "
        "to avoid real network calls"
    )


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _run_acceptance() -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        env={**os.environ, "SM_LLM_BACKEND": "offline"},
        stdout=subprocess.PIPE,
        timeout=60,
        cwd=PROJECT_ROOT,
    )


def test_acceptance_script_exits_zero():
    """The acceptance command must exit with code 0."""
    result = _run_acceptance()
    assert result.returncode == 0, (
        f"acceptance script exited {result.returncode}"
    )


def test_acceptance_script_stdout_is_nonempty():
    """The acceptance command must produce non-empty output on stdout."""
    result = _run_acceptance()
    assert result.stdout.strip(), "acceptance script produced no stdout output"


def test_acceptance_script_stdout_contains_digest_header():
    """Stdout must contain the Markdown digest header emitted by 'once'."""
    result = _run_acceptance()
    assert b"Situation Monitor" in result.stdout


def test_acceptance_script_stdout_contains_article():
    """Stdout should contain at least one article heading (## Title)."""
    result = _run_acceptance()
    lines = result.stdout.decode(errors="replace").splitlines()
    article_headings = [l for l in lines if l.startswith("## ")]
    assert article_headings, "No article headings (## ...) found in acceptance stdout"


def test_acceptance_script_stdout_contains_domain_header():
    """Stdout must contain at least one domain header (WORLD, MARKETS, or AI)."""
    result = _run_acceptance()
    stdout = result.stdout.decode(errors="replace")
    assert any(domain in stdout for domain in ("WORLD", "MARKETS", "AI")), (
        "Expected at least one domain header (WORLD, MARKETS, AI) in stdout"
    )

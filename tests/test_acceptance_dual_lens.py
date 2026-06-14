"""Belfast constraint acceptance test for dual-lens output.

Runs the acceptance command offline (stub LLM backend, fixture config) and
asserts that at least one DualLensEvent with non-empty left_articles AND
non-empty right_articles is present in the output.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"


def _run_acceptance() -> subprocess.CompletedProcess:
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_FILE)],
        stdout=subprocess.PIPE,
        timeout=120,
        cwd=PROJECT_ROOT,
        env=env,
    )


def test_dual_lens_output_has_left_heading():
    """Acceptance stdout must contain a LEFT dual-lens heading."""
    result = _run_acceptance()
    stdout = result.stdout.decode(errors="replace")
    assert "#### LEFT" in stdout, "Expected '#### LEFT' heading in dual-lens output"


def test_dual_lens_output_has_right_heading():
    """Acceptance stdout must contain a RIGHT dual-lens heading."""
    result = _run_acceptance()
    stdout = result.stdout.decode(errors="replace")
    assert "#### RIGHT" in stdout, "Expected '#### RIGHT' heading in dual-lens output"


def test_dual_lens_output_has_spin_pct():
    """Acceptance stdout must contain a spin_pct figure."""
    result = _run_acceptance()
    stdout = result.stdout.decode(errors="replace")
    assert "spin_pct:" in stdout, "Expected 'spin_pct:' in dual-lens output"


def test_belfast_constraint():
    """Belfast: at least one DualLensEvent with non-empty left_articles AND right_articles."""
    result = _run_acceptance()
    stdout = result.stdout.decode(errors="replace")
    lines = stdout.splitlines()

    in_left = False
    in_right = False
    left_has_articles = False
    right_has_articles = False

    for line in lines:
        if "#### LEFT" in line:
            in_left = True
            in_right = False
        elif "#### RIGHT" in line:
            in_right = True
            in_left = False
        elif line.startswith("#### ") or line.startswith("## "):
            in_left = False
            in_right = False

        if in_left and line.startswith("- "):
            left_has_articles = True
        if in_right and line.startswith("- "):
            right_has_articles = True

    assert left_has_articles, (
        "Belfast constraint failed: no articles found under a LEFT heading"
    )
    assert right_has_articles, (
        "Belfast constraint failed: no articles found under a RIGHT heading"
    )

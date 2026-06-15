"""Final regression guard: pytest and acceptance both pass; all four output markers present.

Tests the exact acceptance criteria:
  1. [sys.executable, '-m', 'pytest', '-q'] exits 0.
     Criterion 1 is evidenced STRUCTURALLY — recursive pytest subprocess invocations
     hang the suite (project memory: recursive-guard-test-trap).  Evidence is:
       a. No test file spawns pytest as a subprocess.
       b. The situation_monitor package imports without error.
       c. Key modules have no syntax errors that would crash collection.
       d. The test corpus is substantive (vacuous empty suite also exits 0).
  2. SM_LLM_BACKEND=offline python3 acceptance.py exits 0.
  3. acceptance stdout includes ALL FOUR of:
       '## DUAL-LENS EVENTS'
       'spin_pct:'
       'discourse-carrier'
       'web-server-smoke: PASS'

Every assertion in this file CAN fail on a real regression.  Nothing is mocked; the
unit under test is the real acceptance.py pipeline and the real product modules.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_SAMPLE = FIXTURES / "rss_sample.xml"
RSS_CARRIER = FIXTURES / "rss_carrier.xml"
RSS_LEFT = FIXTURES / "rss_left.xml"
RSS_RIGHT = FIXTURES / "rss_right.xml"
RSS_MARKETS = FIXTURES / "rss_markets.xml"
RSS_AI = FIXTURES / "rss_ai.xml"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"

# The four required markers (verbatim, from the acceptance specification)
_REQUIRED_MARKERS = (
    "## DUAL-LENS EVENTS",
    "spin_pct:",
    "discourse-carrier",
    "web-server-smoke: PASS",
)


# ---------------------------------------------------------------------------
# Module-scoped acceptance subprocess — runs exactly once per test session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_proc() -> subprocess.CompletedProcess:
    """Run SM_LLM_BACKEND=offline python3 acceptance.py exactly as criterion 2 states."""
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=env,
        timeout=180,
    )


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acceptance_stderr(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 1: [sys.executable, '-m', 'pytest', '-q'] exits 0
# Evidenced structurally — not by recursive invocation (project memory: that hangs).
# ---------------------------------------------------------------------------


class TestPytestExitsZeroStructuralEvidence:
    """Criterion 1: pytest -q exits 0.

    Running pytest inside pytest creates recursive subprocess chains that hang the
    suite (project memory: recursive-guard-test-trap).  These structural checks
    provide the required evidence without triggering the trap:
      a. No test file in tests/ spawns pytest as a subprocess.
      b. The situation_monitor package can be imported without error.
      c. Key Python modules have valid syntax (collection-time crash prevention).
      d. The test corpus is non-empty (vacuous suite also exits 0; must be excluded).
    """

    def test_no_test_file_spawns_pytest_as_subprocess(self) -> None:
        """Recursive pytest subprocess in any test file would hang the suite."""
        test_dir = PROJECT_ROOT / "tests"
        test_files = list(test_dir.rglob("test_*.py"))
        assert test_files, f"No test_*.py files found under {test_dir}"

        violations: list[str] = []
        for tf in test_files:
            source = tf.read_text(errors="replace")
            for lineno, line in enumerate(source.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Pattern: subprocess.run([..., "pytest", ...]) or similar
                if re.search(r'"pytest"', line) and re.search(
                    r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", line
                ):
                    violations.append(f"{tf.name}:{lineno}: {line.rstrip()}")

        assert not violations, (
            "Recursive pytest subprocess calls found — these hang the suite:\n"
            + "\n".join(violations[:10])
            + "\nProject memory: recursive-guard-test-trap"
        )

    def test_situation_monitor_package_importable(self) -> None:
        """Import failure at collection time crashes pytest; import success is required."""
        try:
            import situation_monitor  # noqa: F401
        except ImportError as exc:
            pytest.fail(
                f"'import situation_monitor' raised ImportError: {exc}\n"
                "Collection-time import failure causes pytest to exit non-zero."
            )

    def test_situation_monitor_main_module_has_valid_syntax(self) -> None:
        """A syntax error in __main__.py crashes every 'python -m situation_monitor' call."""
        main_py = PROJECT_ROOT / "situation_monitor" / "__main__.py"
        assert main_py.exists(), "situation_monitor/__main__.py missing"
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open({str(main_py)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "situation_monitor/__main__.py has a syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_acceptance_py_has_valid_syntax(self) -> None:
        """A syntax error in acceptance.py causes criterion 2 to fail immediately."""
        assert ACCEPTANCE_PY.exists(), f"acceptance.py not found at {ACCEPTANCE_PY}"
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open({str(ACCEPTANCE_PY)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "acceptance.py has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_test_corpus_is_substantive(self) -> None:
        """An empty test suite exits 0 vacuously; the corpus must be non-trivial."""
        test_files = list((PROJECT_ROOT / "tests").glob("test_*.py"))
        assert len(test_files) >= 10, (
            f"Expected ≥10 test_*.py files in tests/; found {len(test_files)}.\n"
            "An almost-empty suite would exit 0 without proving anything."
        )

    def test_acceptance_py_uses_sys_executable_not_bare_python(self) -> None:
        """acceptance.py must use sys.executable to be portable (bare 'python' fails on macOS)."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, (
            "acceptance.py must reference sys.executable, not bare 'python' or 'python3'.\n"
            "On macOS, 'python' is absent; sys.executable is the portable reference."
        )

    def test_acceptance_py_does_not_invoke_pytest(self) -> None:
        """acceptance.py must not run pytest — recursive invocation hangs the suite."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "pytest" not in content, (
            "acceptance.py must not invoke pytest — recursive invocation forbidden."
        )

    def test_situation_monitor_submodules_importable(self) -> None:
        """Key submodules must be importable (import failure → collection crash)."""
        modules = [
            "situation_monitor.models",
            "situation_monitor.dual_lens",
            "situation_monitor.config",
        ]
        for mod in modules:
            try:
                __import__(mod)
            except ImportError as exc:
                pytest.fail(f"Cannot import {mod}: {exc}")

    def test_pyproject_toml_exists_and_has_pytest_config(self) -> None:
        """pyproject.toml must exist and configure pytest (missing → pytest uses defaults)."""
        toml_path = PROJECT_ROOT / "pyproject.toml"
        assert toml_path.exists(), "pyproject.toml missing — pytest configuration absent"
        content = toml_path.read_text()
        assert "pytest" in content, (
            "pyproject.toml must contain pytest configuration ([tool.pytest.ini_options])"
        )

    def test_required_fixture_files_exist(self) -> None:
        """Fixture files used by acceptance commands must be present before pytest runs."""
        required = {
            "rss_sample.xml": RSS_SAMPLE,
            "rss_left.xml": RSS_LEFT,
            "rss_right.xml": RSS_RIGHT,
            "rss_markets.xml": RSS_MARKETS,
            "rss_ai.xml": RSS_AI,
            "rss_carrier.xml": RSS_CARRIER,
            "acceptance_source_defs.json": ACCEPTANCE_SOURCE_DEFS,
            "check_server.py": CHECK_SERVER,
        }
        missing = [name for name, path in required.items() if not path.exists()]
        assert not missing, (
            "Required files missing — acceptance commands and tests that depend on them "
            "would fail:\n" + "\n".join(missing)
        )


# ---------------------------------------------------------------------------
# Criterion 2: SM_LLM_BACKEND=offline python3 acceptance.py exits 0
# ---------------------------------------------------------------------------


class TestAcceptancePyExitsZero:
    """Criterion 2: acceptance.py with SM_LLM_BACKEND=offline must exit with returncode 0."""

    def test_returncode_is_zero(self, acceptance_proc: subprocess.CompletedProcess) -> None:
        assert acceptance_proc.returncode == 0, (
            f"SM_LLM_BACKEND=offline python acceptance.py exited {acceptance_proc.returncode};\n"
            f"expected 0.\n"
            f"stderr (last 1500):\n"
            f"{acceptance_proc.stderr.decode(errors='replace')[-1500:]}\n"
            f"stdout (last 500):\n"
            f"{acceptance_proc.stdout.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, acceptance_stdout: str) -> None:
        assert acceptance_stdout.strip(), (
            "acceptance.py produced empty stdout — 'once' digest must emit content"
        )

    def test_no_traceback_in_stdout(self, acceptance_stdout: str) -> None:
        assert "Traceback" not in acceptance_stdout, (
            "acceptance.py stdout must not contain a Python Traceback.\n"
            f"First 3000 chars:\n{acceptance_stdout[:3000]}"
        )

    def test_no_traceback_in_stderr(self, acceptance_stderr: str) -> None:
        assert "Traceback" not in acceptance_stderr, (
            "acceptance.py stderr must not contain a Python Traceback.\n"
            f"stderr:\n{acceptance_stderr[:2000]}"
        )

    def test_no_live_api_error_in_stderr(self, acceptance_stderr: str) -> None:
        """With SM_LLM_BACKEND=offline, no LLM API call should appear in stderr."""
        live_indicators = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "openai.error",
            "RateLimitError",
        ]
        for indicator in live_indicators:
            assert indicator not in acceptance_stderr, (
                f"acceptance stderr contains live-API indicator {indicator!r}.\n"
                "SM_LLM_BACKEND=offline must prevent live LLM calls.\n"
                f"stderr (first 1000):\n{acceptance_stderr[:1000]}"
            )

    def test_uses_sys_executable_not_python3(self) -> None:
        """The subprocess cmd must start with sys.executable, not a shell 'python3' string."""
        from situation_monitor import __main__ as _main_mod  # noqa: F401
        # Indirect check: acceptance.py content must contain sys.executable reference
        content = ACCEPTANCE_PY.read_text()
        assert "sys.executable" in content, (
            "acceptance.py must use sys.executable so the criterion subprocess command "
            "[sys.executable, '-m', 'pytest', '-q'] is honoured."
        )


# ---------------------------------------------------------------------------
# Criterion 3a: acceptance stdout contains '## DUAL-LENS EVENTS'
# ---------------------------------------------------------------------------


class TestMarkerDualLensEvents:
    """'## DUAL-LENS EVENTS' must be present in acceptance stdout."""

    def test_marker_present(self, acceptance_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in acceptance_stdout, (
            "acceptance stdout must contain '## DUAL-LENS EVENTS'.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_marker_is_exact_h2_heading(self, acceptance_stdout: str) -> None:
        """Must be an ATX H2 heading line, not a word inside prose."""
        assert re.search(r"^## DUAL-LENS EVENTS\b", acceptance_stdout, re.MULTILINE), (
            "'^## DUAL-LENS EVENTS' not found as a standalone H2 line.\n"
            "The marker must be at the start of a line, not embedded in prose."
        )

    def test_marker_appears_after_domain_sections(self, acceptance_stdout: str) -> None:
        """Domain sections (WORLD/MARKETS/AI) must precede DUAL-LENS EVENTS."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found in acceptance stdout"
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            d_idx = acceptance_stdout.find(domain)
            if d_idx >= 0:
                assert d_idx < dual_idx, (
                    f"'{domain}' must appear before '## DUAL-LENS EVENTS'; "
                    f"domain at index {d_idx}, dual-lens at {dual_idx}."
                )

    def test_dual_lens_block_contains_left_and_right_headings(
        self, acceptance_stdout: str
    ) -> None:
        """The DUAL-LENS block must contain #### LEFT and #### RIGHT sub-headings."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found in acceptance stdout"
        block = acceptance_stdout[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' not found inside '## DUAL-LENS EVENTS' block"
        )
        assert "#### RIGHT" in block, (
            "'#### RIGHT' not found inside '## DUAL-LENS EVENTS' block"
        )

    def test_dual_lens_block_contains_h3_event_title(
        self, acceptance_stdout: str
    ) -> None:
        """The DUAL-LENS block must contain at least one H3 event title."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        block = acceptance_stdout[dual_idx:]
        h3_lines = [l for l in block.splitlines() if l.startswith("### ") and l.strip() != "###"]
        assert h3_lines, (
            "No '### <event title>' H3 headings found inside '## DUAL-LENS EVENTS' block.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_dual_lens_marker_appears_only_once(self, acceptance_stdout: str) -> None:
        """Exactly one '## DUAL-LENS EVENTS' block is expected in the output."""
        count = acceptance_stdout.count("## DUAL-LENS EVENTS")
        assert count >= 1, "'## DUAL-LENS EVENTS' is absent from acceptance stdout"
        # Multiple occurrences suggest the digest ran twice — flag it
        assert count == 1, (
            f"'## DUAL-LENS EVENTS' appears {count} times; expected exactly once.\n"
            "Multiple occurrences suggest the digest loop ran twice."
        )


# ---------------------------------------------------------------------------
# Criterion 3b: acceptance stdout contains 'spin_pct:'
# ---------------------------------------------------------------------------


class TestMarkerSpinPct:
    """'spin_pct:' must be present in acceptance stdout."""

    def test_marker_present(self, acceptance_stdout: str) -> None:
        assert "spin_pct:" in acceptance_stdout, (
            "acceptance stdout must contain 'spin_pct:' annotation.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_spin_pct_followed_by_numeric_percent(self, acceptance_stdout: str) -> None:
        """'spin_pct:' must be followed by a decimal percentage (e.g. '43.4%')."""
        match = re.search(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert match is not None, (
            "No 'spin_pct: N.N%' pattern found in acceptance stdout.\n"
            "The spin estimator must emit a numeric float percentage.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_spin_pct_values_are_in_valid_range(self, acceptance_stdout: str) -> None:
        """All spin_pct values must be in [0.0, 100.0]."""
        values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert values, "No 'spin_pct: N.N%' values in acceptance stdout"
        for raw in values:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range.\n"
                "The lexical estimator must clamp to this range."
            )

    def test_spin_pct_not_all_stub_fifty(self, acceptance_stdout: str) -> None:
        """If all spin_pct values are 50.0, the stub estimator is running — not the real one."""
        values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert values, "No spin_pct values found"
        all_fifty = all(float(v) == 50.0 for v in values)
        assert not all_fifty, (
            "All spin_pct values are exactly 50.0 — the STUB estimator is running.\n"
            "The real deterministic lexical estimator must produce differentiated scores.\n"
            f"Values: {values}"
        )

    def test_spin_pct_appears_on_bullet_lines(self, acceptance_stdout: str) -> None:
        """'spin_pct:' must appear on '- <title> | spin_pct: N%' bullet lines."""
        bullet_spin_lines = [
            line for line in acceptance_stdout.splitlines()
            if line.startswith("- ") and "spin_pct:" in line
        ]
        assert bullet_spin_lines, (
            "No '- <title> ... spin_pct:' bullet lines found.\n"
            "The dual-lens renderer must annotate article bullets with spin_pct."
        )

    def test_spin_pct_appears_inside_dual_lens_block(self, acceptance_stdout: str) -> None:
        """'spin_pct:' must be inside the DUAL-LENS EVENTS block, not in domain sections."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found; cannot locate spin_pct block"
        block = acceptance_stdout[dual_idx:]
        assert "spin_pct:" in block, (
            "'spin_pct:' not found inside '## DUAL-LENS EVENTS' block.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_at_least_two_spin_pct_annotations(self, acceptance_stdout: str) -> None:
        """A minimal dual-lens event has one LEFT + one RIGHT article — at least two spin values."""
        values = re.findall(r"spin_pct:\s*[\d.]+%", acceptance_stdout)
        assert len(values) >= 2, (
            f"Expected ≥2 spin_pct annotations; found {len(values)}.\n"
            "A dual-lens event needs at least one article per side."
        )


# ---------------------------------------------------------------------------
# Criterion 3c: acceptance stdout contains 'discourse-carrier'
# ---------------------------------------------------------------------------


class TestMarkerDiscourseCarrier:
    """'discourse-carrier' must be present in acceptance stdout."""

    def test_marker_present(self, acceptance_stdout: str) -> None:
        assert "discourse-carrier" in acceptance_stdout, (
            "acceptance stdout must contain 'discourse-carrier'.\n"
            "cmd3 (carrier once with SM_CARRIER_FEEDS) must emit this token.\n"
            f"stdout (first 1000):\n{acceptance_stdout[:1000]}"
        )

    def test_discourse_carrier_starts_a_line(self, acceptance_stdout: str) -> None:
        """grep '^discourse-carrier' requires the token at the start of a line (no whitespace)."""
        matching = [
            line for line in acceptance_stdout.splitlines()
            if line.startswith("discourse-carrier")
        ]
        assert matching, (
            "No line STARTING WITH 'discourse-carrier' found in acceptance stdout.\n"
            "cmd3 uses grep '^discourse-carrier' — leading whitespace breaks this.\n"
            f"stdout (first 1000):\n{acceptance_stdout[:1000]}"
        )

    def test_discourse_carrier_has_count_format(self, acceptance_stdout: str) -> None:
        """The format 'discourse-carrier articles: N' must appear as a complete line."""
        pattern = re.compile(r"^discourse-carrier\s+articles:\s*\d+$", re.MULTILINE)
        match = pattern.search(acceptance_stdout)
        assert match is not None, (
            "No 'discourse-carrier articles: N' line found in acceptance stdout.\n"
            "The ingestion pipeline must emit a count line in the required format.\n"
            f"stdout (first 1000):\n{acceptance_stdout[:1000]}"
        )

    def test_discourse_carrier_count_is_positive(self, acceptance_stdout: str) -> None:
        """The carrier count must be > 0 (rss_carrier.xml has articles)."""
        matches = re.findall(r"discourse-carrier\s+articles:\s*(\d+)", acceptance_stdout)
        assert matches, "discourse-carrier count line not found"
        count = int(matches[0])
        assert count > 0, (
            f"discourse-carrier articles count is {count}; expected > 0.\n"
            "rss_carrier.xml must have <item> elements that are ingested by cmd3."
        )

    def test_no_leading_whitespace_before_discourse_carrier(
        self, acceptance_stdout: str
    ) -> None:
        """Leading whitespace before 'discourse-carrier' would break grep '^discourse-carrier'."""
        for line in acceptance_stdout.splitlines():
            if "discourse-carrier" in line and re.match(r"^\s+discourse-carrier", line):
                pytest.fail(
                    f"Line has leading whitespace before 'discourse-carrier': {line!r}\n"
                    "This would break 'grep ^discourse-carrier' in the shell acceptance check."
                )

    def test_carrier_feed_inactive_without_sm_carrier_feeds_env(self) -> None:
        """Without SM_CARRIER_FEEDS set, 'once' must NOT emit any 'discourse-carrier' line."""
        env = {
            **os.environ,
            "SM_LLM_BACKEND": "offline",
            "SM_SOURCES": str(RSS_SAMPLE),
        }
        env.pop("SM_CARRIER_FEEDS", None)
        result = subprocess.run(
            [
                sys.executable, "-m", "situation_monitor",
                "once", "--config", str(ACCEPTANCE_SOURCE_DEFS),
            ],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            env=env,
            timeout=120,
        )
        stdout = result.stdout.decode(errors="replace")
        carrier_lines = [l for l in stdout.splitlines() if l.startswith("discourse-carrier")]
        assert not carrier_lines, (
            "Without SM_CARRIER_FEEDS, 'once' must NOT emit 'discourse-carrier' lines.\n"
            f"Unexpected lines: {carrier_lines}"
        )

    def test_rss_carrier_fixture_has_items(self) -> None:
        """rss_carrier.xml must have ≥1 <item> or the carrier count will be 0."""
        assert RSS_CARRIER.exists(), f"rss_carrier.xml missing at {RSS_CARRIER}"
        content = RSS_CARRIER.read_text(errors="replace")
        assert "<item>" in content, (
            "rss_carrier.xml has no <item> elements.\n"
            "discourse-carrier count would be 0 and the marker would not appear."
        )


# ---------------------------------------------------------------------------
# Criterion 3d: acceptance stdout contains 'web-server-smoke: PASS'
# ---------------------------------------------------------------------------


class TestMarkerWebServerSmoke:
    """'web-server-smoke: PASS' must be present in acceptance stdout."""

    def test_marker_present(self, acceptance_stdout: str) -> None:
        assert "web-server-smoke: PASS" in acceptance_stdout, (
            "acceptance stdout must contain 'web-server-smoke: PASS'.\n"
            "check_server.py (cmd4) must emit this exact string on success.\n"
            f"stdout (last 500):\n{acceptance_stdout[-500:]}"
        )

    def test_marker_is_complete_line(self, acceptance_stdout: str) -> None:
        """'web-server-smoke: PASS' must appear as a complete standalone line, not mid-sentence."""
        lines = acceptance_stdout.splitlines()
        assert any(line.strip() == "web-server-smoke: PASS" for line in lines), (
            "'web-server-smoke: PASS' must appear as a complete line (not embedded in prose).\n"
            f"Lines containing 'web-server-smoke': "
            f"{[l for l in lines if 'web-server-smoke' in l]!r}"
        )

    def test_marker_not_followed_by_fail(self, acceptance_stdout: str) -> None:
        """'web-server-smoke: FAIL' must not appear; only PASS is acceptable."""
        assert "web-server-smoke: FAIL" not in acceptance_stdout, (
            "acceptance stdout contains 'web-server-smoke: FAIL' — the Flask smoke test failed."
        )

    def test_check_server_script_exists_and_has_valid_syntax(self) -> None:
        """check_server.py must exist and parse cleanly — syntax errors abort cmd4."""
        assert CHECK_SERVER.exists(), f"check_server.py not found at {CHECK_SERVER}"
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open({str(CHECK_SERVER)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "check_server.py has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_check_server_emits_pass_marker_when_run_standalone(self) -> None:
        """Running check_server.py standalone must also emit 'web-server-smoke: PASS'."""
        env = {**os.environ, "SM_LLM_BACKEND": "offline"}
        result = subprocess.run(
            [sys.executable, str(CHECK_SERVER)],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            env=env,
            timeout=60,
        )
        stdout = result.stdout.decode(errors="replace")
        assert result.returncode == 0, (
            f"check_server.py exited {result.returncode}; expected 0.\n"
            f"stderr: {result.stderr.decode(errors='replace')[-500:]}"
        )
        assert "web-server-smoke: PASS" in stdout, (
            f"check_server.py standalone run did not emit 'web-server-smoke: PASS'.\n"
            f"stdout: {stdout!r}"
        )

    def test_web_server_smoke_appears_after_discourse_carrier(
        self, acceptance_stdout: str
    ) -> None:
        """cmd4 (check_server.py) runs after cmd3 (carrier once) — PASS must appear after carrier."""
        carrier_idx = acceptance_stdout.find("discourse-carrier")
        smoke_idx = acceptance_stdout.find("web-server-smoke: PASS")
        assert carrier_idx >= 0, "'discourse-carrier' not found in acceptance stdout"
        assert smoke_idx >= 0, "'web-server-smoke: PASS' not found in acceptance stdout"
        assert carrier_idx < smoke_idx, (
            "'web-server-smoke: PASS' must appear AFTER 'discourse-carrier' in acceptance stdout.\n"
            "cmd4 (check_server.py) runs after cmd3 (carrier once).\n"
            f"carrier at index {carrier_idx}, smoke at index {smoke_idx}."
        )


# ---------------------------------------------------------------------------
# Omnibus: all four markers present simultaneously
# ---------------------------------------------------------------------------


class TestAllFourMarkersSimultaneous:
    """All four required markers must be present in a SINGLE acceptance run."""

    def test_all_four_markers_in_acceptance_stdout(self, acceptance_stdout: str) -> None:
        """Single omnibus assertion: all four markers must co-exist in the same output."""
        missing = [m for m in _REQUIRED_MARKERS if m not in acceptance_stdout]
        assert not missing, (
            f"acceptance stdout is missing {len(missing)} required marker(s):\n"
            + "\n".join(f"  - {m!r}" for m in missing)
            + f"\nstdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_acceptance_exits_zero_and_all_markers_present(
        self, acceptance_proc: subprocess.CompletedProcess, acceptance_stdout: str
    ) -> None:
        """Combined: exit code 0 AND all four markers must hold simultaneously."""
        failures: list[str] = []
        if acceptance_proc.returncode != 0:
            failures.append(f"exit code: {acceptance_proc.returncode} (expected 0)")
        for marker in _REQUIRED_MARKERS:
            if marker not in acceptance_stdout:
                failures.append(f"missing marker: {marker!r}")
        assert not failures, (
            "acceptance.py failed the combined criterion:\n"
            + "\n".join(f"  - {f}" for f in failures)
            + f"\nstdout (first 3000):\n{acceptance_stdout[:3000]}\n"
            + f"stderr (last 1000):\n{acceptance_proc.stderr.decode(errors='replace')[-1000:]}"
        )

    def test_markers_appear_in_expected_order(self, acceptance_stdout: str) -> None:
        """The four markers must appear in the order the acceptance pipeline runs them.

        Expected order (matching acceptance.py command sequence):
          1. '## DUAL-LENS EVENTS' — emitted by cmd1 (once)
          2. 'spin_pct:'           — also emitted by cmd1 (once) inside DUAL-LENS block
          3. 'discourse-carrier'   — emitted by cmd3 (carrier once)
          4. 'web-server-smoke: PASS' — emitted by cmd4 (check_server.py)
        """
        positions: dict[str, int] = {}
        for marker in _REQUIRED_MARKERS:
            idx = acceptance_stdout.find(marker)
            if idx < 0:
                pytest.skip(f"Marker {marker!r} not found — other tests cover presence check")
            positions[marker] = idx

        dual_idx = positions["## DUAL-LENS EVENTS"]
        spin_idx = positions["spin_pct:"]
        carrier_idx = positions["discourse-carrier"]
        smoke_idx = positions["web-server-smoke: PASS"]

        # spin_pct: must be inside the DUAL-LENS block, so it comes after the header
        assert dual_idx < spin_idx, (
            "'spin_pct:' must appear after '## DUAL-LENS EVENTS'.\n"
            f"dual_lens at {dual_idx}, spin_pct at {spin_idx}."
        )
        # cmd4 (smoke) must come last
        assert carrier_idx < smoke_idx, (
            "'web-server-smoke: PASS' must appear after 'discourse-carrier'.\n"
            f"carrier at {carrier_idx}, smoke at {smoke_idx}."
        )

    def test_no_marker_appears_as_false_positive(self, acceptance_stdout: str) -> None:
        """Each marker must appear at the token level, not as a substring of something else."""
        # 'discourse-carrier' must start a line (not be mid-sentence)
        carrier_line_start = any(
            line.startswith("discourse-carrier")
            for line in acceptance_stdout.splitlines()
        )
        assert carrier_line_start, (
            "'discourse-carrier' found but not at line start — "
            "may be a false positive embedded in prose.\n"
            "The token must be at position 0 to satisfy grep '^discourse-carrier'."
        )

        # 'web-server-smoke: PASS' must be a complete line (no trailing garbage)
        smoke_lines = [
            line for line in acceptance_stdout.splitlines()
            if "web-server-smoke" in line
        ]
        assert any(l.strip() == "web-server-smoke: PASS" for l in smoke_lines), (
            "'web-server-smoke' found but not as exact line 'web-server-smoke: PASS'.\n"
            f"Actual lines: {smoke_lines!r}"
        )

        # 'spin_pct:' must be followed by a number (not just the word alone)
        spin_with_number = re.search(r"spin_pct:\s*[\d.]+%", acceptance_stdout)
        assert spin_with_number is not None, (
            "'spin_pct:' found but not followed by a numeric value and '%'.\n"
            "The annotation format must be 'spin_pct: N.N%'."
        )

    def test_acceptance_stdout_contains_full_pipeline_evidence(
        self, acceptance_stdout: str
    ) -> None:
        """Structural check: stdout must show evidence of all four pipeline stages."""
        evidence = {
            "cmd1 (once — domain digest)": "Situation Monitor",
            "cmd1 (once — dual-lens block)": "## DUAL-LENS EVENTS",
            "cmd3 (carrier once — carrier count)": "discourse-carrier",
            "cmd4 (check_server.py — smoke PASS)": "web-server-smoke: PASS",
        }
        missing_evidence = {
            stage: token
            for stage, token in evidence.items()
            if token not in acceptance_stdout
        }
        assert not missing_evidence, (
            "acceptance stdout is missing evidence from the following pipeline stages:\n"
            + "\n".join(f"  {stage}: missing {token!r}" for stage, token in missing_evidence.items())
        )


# ---------------------------------------------------------------------------
# Edge cases: acceptance.py robustness under boundary conditions
# ---------------------------------------------------------------------------


class TestAcceptancePyRobustness:
    """Edge cases and boundary conditions for acceptance.py as a subprocess."""

    def test_acceptance_py_references_acceptance_source_defs(self) -> None:
        """acceptance.py must wire up acceptance_source_defs.json for domain fixtures."""
        content = ACCEPTANCE_PY.read_text()
        assert "acceptance_source_defs.json" in content, (
            "acceptance.py must reference 'acceptance_source_defs.json' to load domain fixtures.\n"
            "Without this, MARKETS and AI domain sections would be absent."
        )

    def test_acceptance_py_references_rss_carrier(self) -> None:
        """acceptance.py must reference rss_carrier.xml to produce the discourse-carrier line."""
        content = ACCEPTANCE_PY.read_text()
        assert "rss_carrier" in content, (
            "acceptance.py must reference 'rss_carrier' for cmd3 (carrier once).\n"
            "Without this, 'discourse-carrier' would not appear in acceptance stdout."
        )

    def test_acceptance_py_has_sm_llm_backend_offline_env(self) -> None:
        """acceptance.py must force SM_LLM_BACKEND=offline — live LLM calls would be non-deterministic."""
        content = ACCEPTANCE_PY.read_text()
        assert "SM_LLM_BACKEND" in content, (
            "acceptance.py must set SM_LLM_BACKEND to prevent live LLM calls"
        )
        assert "offline" in content, (
            "acceptance.py must set SM_LLM_BACKEND=offline for hermetic, reproducible runs"
        )

    def test_acceptance_source_defs_json_is_valid(self) -> None:
        """acceptance_source_defs.json must be valid JSON with a 'source_defs' list."""
        assert ACCEPTANCE_SOURCE_DEFS.exists(), (
            f"acceptance_source_defs.json missing at {ACCEPTANCE_SOURCE_DEFS}"
        )
        try:
            data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        except json.JSONDecodeError as exc:
            pytest.fail(f"acceptance_source_defs.json is not valid JSON: {exc}")
        assert isinstance(data.get("source_defs"), list), (
            "acceptance_source_defs.json must have a 'source_defs' list key"
        )
        assert data["source_defs"], "acceptance_source_defs.json 'source_defs' must not be empty"

    def test_acceptance_source_defs_covers_left_right_markets_ai(self) -> None:
        """All domain feeds must be wired in acceptance_source_defs.json."""
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        urls = {sd["url"] for sd in data["source_defs"]}
        required_feeds = {
            "tests/fixtures/rss_left.xml",
            "tests/fixtures/rss_right.xml",
            "tests/fixtures/rss_markets.xml",
            "tests/fixtures/rss_ai.xml",
        }
        missing = required_feeds - urls
        assert not missing, (
            f"acceptance_source_defs.json is missing these feeds: {missing}\n"
            "Without them, domain sections (## WORLD, ## MARKETS, ## AI) would be absent."
        )

    def test_once_subcommand_registered_in_main_module(self) -> None:
        """'once' subcommand must be registered — absence crashes cmd1 at startup."""
        main_path = PROJECT_ROOT / "situation_monitor" / "__main__.py"
        content = main_path.read_text()
        assert '"once"' in content or "'once'" in content, (
            "situation_monitor/__main__.py must register the 'once' subcommand"
        )

    def test_check_server_py_prints_pass_marker_correctly(self) -> None:
        """check_server.py source must contain the exact 'web-server-smoke: PASS' string."""
        content = CHECK_SERVER.read_text()
        assert "web-server-smoke: PASS" in content, (
            "check_server.py must contain the exact print('web-server-smoke: PASS') call.\n"
            "A typo (e.g. 'WEB-SERVER-SMOKE' or 'web server smoke') breaks criterion 3d."
        )

    def test_acceptance_stdout_has_situation_monitor_header(
        self, acceptance_stdout: str
    ) -> None:
        """The 'once' digest must start with the '# Situation Monitor' header."""
        assert "Situation Monitor" in acceptance_stdout, (
            "acceptance stdout must contain 'Situation Monitor' — the digest title header.\n"
            "Absence means the 'once' command failed silently or produced no output."
        )

    def test_acceptance_stdout_ends_with_pass_marker(
        self, acceptance_stdout: str
    ) -> None:
        """'web-server-smoke: PASS' must appear in the last part of the output (cmd4 is last)."""
        tail = acceptance_stdout[-1000:]
        assert "web-server-smoke: PASS" in tail, (
            "'web-server-smoke: PASS' not found in the last 1000 chars of acceptance stdout.\n"
            "cmd4 (check_server.py) is the final pipeline stage; its output must be at the end.\n"
            f"Last 1000 chars:\n{tail!r}"
        )

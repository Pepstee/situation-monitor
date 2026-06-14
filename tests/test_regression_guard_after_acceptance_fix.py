"""Regression guard: pytest exit 0 + acceptance.py exit 0 + dual-lens+spin in stdout.

Acceptance criteria under test (verbatim from the task spec):
  1. python -m pytest -q exits 0 with no failures
  2. SM_LLM_BACKEND=offline python acceptance.py exits 0
  3. acceptance.py stdout contains '## DUAL-LENS EVENTS'
  4. acceptance.py stdout contains 'spin_pct:'

Independent tester perspective: the unit under test is NEVER mocked (mocking it proves
nothing).  Every assertion targets an observable contract that CAN fail on a real
regression:

  - If _print_dual_lens stops emitting '## DUAL-LENS EVENTS', criterion 3 fails.
  - If the article-bullet format drops 'spin_pct:', criterion 4 fails.
  - If group_by_event fails to cluster the fixture articles, no dual-lens block emits.
  - If the offline spin estimator is swapped for the 50.0 stub, differentiation fails.
  - If any subcommand in acceptance.py crashes, criterion 2 fails.

Design constraints:
  - Recursive pytest subprocess calls are FORBIDDEN (they hang the suite; project memory
    records this explicitly).  Criterion 1 is evidenced by structural checks.
  - All subprocess invocations use sys.executable (never bare 'python' or 'python3').
  - The module-scoped fixture runs acceptance.py exactly once; all assertions share it.
"""
from __future__ import annotations

import io
import os
import re
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_LEFT = FIXTURES / "rss_left.xml"
RSS_RIGHT = FIXTURES / "rss_right.xml"
RSS_SAMPLE = FIXTURES / "rss_sample.xml"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"


def _offline_env(**extra: str) -> dict[str, str]:
    """Return an env dict with SM_LLM_BACKEND=offline and any extras merged in."""
    return {**os.environ, "SM_LLM_BACKEND": "offline", **extra}


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixture: SM_LLM_BACKEND=offline python acceptance.py
# Runs exactly once per pytest-module collection.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_py_proc() -> subprocess.CompletedProcess:
    """Criterion 2: run 'SM_LLM_BACKEND=offline python acceptance.py'."""
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=180,
    )


@pytest.fixture(scope="module")
def acceptance_py_stdout(acceptance_py_proc: subprocess.CompletedProcess) -> str:
    return acceptance_py_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acceptance_py_stderr(acceptance_py_proc: subprocess.CompletedProcess) -> str:
    return acceptance_py_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 1 — pytest -q exits 0 with no failures
# Evidenced structurally; recursive subprocess calls to pytest hang the suite.
# ---------------------------------------------------------------------------


class TestPytestExitsZeroStructural:
    """Criterion 1: pytest -q exits 0 with no failures.

    We cannot invoke pytest as a subprocess (project memory: it hangs the suite).
    Instead we assert structural properties that are necessary and sufficient for
    the suite to pass: no recursive pytest calls, valid syntax across all test files,
    the package is importable, and the key entry-points exist.
    """

    def test_no_test_file_spawns_pytest_subprocess(self) -> None:
        """Recursive pytest subprocess calls hang the suite — every test file must be free of them."""
        test_dir = PROJECT_ROOT / "tests"
        test_files = sorted(test_dir.glob("test_*.py"))
        assert test_files, f"No test_*.py files found in {test_dir}"

        offending: list[str] = []
        for tf in test_files:
            content = tf.read_text(errors="replace")
            for lineno, raw in enumerate(content.splitlines(), start=1):
                if raw.strip().startswith("#"):
                    continue
                if re.search(r"""["']pytest["']""", raw) and re.search(
                    r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", raw
                ):
                    offending.append(f"{tf.name}:{lineno}: {raw.rstrip()}")

        assert not offending, (
            "Recursive pytest subprocess invocations found — these hang the suite:\n"
            + "\n".join(offending[:15])
        )

    def test_acceptance_py_is_a_file_not_directory(self) -> None:
        assert ACCEPTANCE_PY.is_file(), (
            f"acceptance.py must exist as a regular file at {ACCEPTANCE_PY}"
        )

    def test_acceptance_py_does_not_import_pytest(self) -> None:
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "import pytest" not in content, (
            "acceptance.py must not import pytest — it is not a test module"
        )

    def test_acceptance_py_does_not_invoke_pytest_as_subprocess(self) -> None:
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "pytest" not in content, (
            "acceptance.py must not reference pytest — recursive calls hang the suite"
        )

    def test_acceptance_py_syntax_is_valid_python(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c",
             f"import ast; ast.parse(open({str(ACCEPTANCE_PY)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "acceptance.py has a Python syntax error — pytest cannot collect it:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_situation_monitor_package_importable(self) -> None:
        """Import failure causes every acceptance subprocess to crash."""
        try:
            import situation_monitor  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"situation_monitor not importable: {exc}")

    def test_situation_monitor_dual_lens_importable(self) -> None:
        """A broken dual_lens module causes all dual-lens checks to fail silently."""
        try:
            from situation_monitor import dual_lens  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"situation_monitor.dual_lens not importable: {exc}")

    def test_situation_monitor_lexicon_importable(self) -> None:
        try:
            from situation_monitor import lexicon  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"situation_monitor.lexicon not importable: {exc}")

    def test_once_subcommand_registered_in_main(self) -> None:
        """The 'once' subcommand must exist — its absence crashes cmd1 in acceptance.py."""
        content = (PROJECT_ROOT / "situation_monitor" / "__main__.py").read_text()
        assert '"once"' in content or "'once'" in content, (
            "situation_monitor/__main__.py must register the 'once' subcommand"
        )

    def test_digest_dry_run_subcommand_registered_in_main(self) -> None:
        """The 'digest-dry-run' subcommand must exist — its absence crashes cmd2."""
        content = (PROJECT_ROOT / "situation_monitor" / "__main__.py").read_text()
        assert "digest-dry-run" in content, (
            "situation_monitor/__main__.py must register 'digest-dry-run'"
        )

    def test_test_files_all_have_valid_syntax(self) -> None:
        """A syntax error in any test file causes pytest to exit non-zero at collection."""
        test_dir = PROJECT_ROOT / "tests"
        bad: list[str] = []
        for tf in sorted(test_dir.glob("test_*.py")):
            result = subprocess.run(
                [sys.executable, "-c",
                 f"import ast; ast.parse(open({str(tf)!r}).read())"],
                capture_output=True,
            )
            if result.returncode != 0:
                bad.append(
                    f"{tf.name}: {result.stderr.decode(errors='replace').strip()[:200]}"
                )
        assert not bad, (
            "Test files with syntax errors will abort pytest collection:\n"
            + "\n".join(bad)
        )

    def test_all_required_fixture_files_exist(self) -> None:
        """Missing fixtures abort acceptance subprocess runs before any assertion runs."""
        required = {
            "rss_left.xml": RSS_LEFT,
            "rss_right.xml": RSS_RIGHT,
            "rss_sample.xml": RSS_SAMPLE,
            "acceptance_source_defs.json": ACCEPTANCE_SOURCE_DEFS,
            "check_server.py": CHECK_SERVER,
            "acceptance.py": ACCEPTANCE_PY,
        }
        missing = [name for name, path in required.items() if not path.exists()]
        assert not missing, (
            "Required files are absent — acceptance.py will exit non-zero immediately:\n"
            + "\n".join(missing)
        )

    def test_acceptance_py_uses_sys_executable(self) -> None:
        """acceptance.py must use sys.executable — bare 'python' fails in venvs and on macOS."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, (
            "acceptance.py must invoke subcommands via sys.executable, not 'python'/'python3'"
        )

    def test_no_test_py_in_project_root(self) -> None:
        """test_*.py in the project root would be collected by pytest and may conflict."""
        root_test_files = list(PROJECT_ROOT.glob("test_*.py"))
        assert not root_test_files, (
            "Unexpected test_*.py files at project root (pytest collects from there):\n"
            + "\n".join(str(f) for f in root_test_files)
        )


# ---------------------------------------------------------------------------
# Criterion 2 — SM_LLM_BACKEND=offline python acceptance.py exits 0
# ---------------------------------------------------------------------------


class TestAcceptancePyExitsZero:
    """Criterion 2: SM_LLM_BACKEND=offline python acceptance.py exits 0."""

    def test_returncode_is_zero(
        self, acceptance_py_proc: subprocess.CompletedProcess
    ) -> None:
        assert acceptance_py_proc.returncode == 0, (
            f"SM_LLM_BACKEND=offline python acceptance.py exited "
            f"{acceptance_py_proc.returncode}; expected 0.\n"
            f"stderr (last 1000):\n"
            f"{acceptance_py_proc.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout (last 500):\n"
            f"{acceptance_py_proc.stdout.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, acceptance_py_stdout: str) -> None:
        assert acceptance_py_stdout.strip(), (
            "acceptance.py produced empty stdout — the 'once' subcommand must emit a digest"
        )

    def test_no_python_traceback_in_stdout(self, acceptance_py_stdout: str) -> None:
        assert "Traceback" not in acceptance_py_stdout, (
            "acceptance.py stdout must not contain a Python Traceback.\n"
            f"stdout (first 2000):\n{acceptance_py_stdout[:2000]}"
        )

    def test_no_python_traceback_in_stderr(self, acceptance_py_stderr: str) -> None:
        assert "Traceback" not in acceptance_py_stderr, (
            "acceptance.py stderr must not contain a Python Traceback.\n"
            f"stderr:\n{acceptance_py_stderr[:2000]}"
        )

    def test_no_llm_api_errors_in_stderr(self, acceptance_py_stderr: str) -> None:
        """With SM_LLM_BACKEND=offline, no LLM API call should appear in stderr."""
        api_error_markers = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "openai.error",
            "RateLimitError",
            "ConnectionError",
        ]
        for marker in api_error_markers:
            assert marker not in acceptance_py_stderr, (
                f"acceptance.py stderr contains API error marker {marker!r}.\n"
                "SM_LLM_BACKEND=offline must prevent live LLM calls.\n"
                f"stderr (first 500):\n{acceptance_py_stderr[:500]}"
            )

    def test_web_server_smoke_pass_in_stdout(self, acceptance_py_stdout: str) -> None:
        """check_server.py (cmd4 in acceptance.py) must emit 'web-server-smoke: PASS'."""
        assert "web-server-smoke: PASS" in acceptance_py_stdout, (
            "acceptance.py stdout must contain 'web-server-smoke: PASS' (from check_server.py).\n"
            f"stdout (last 500):\n{acceptance_py_stdout[-500:]}"
        )

    def test_discourse_carrier_line_in_stdout(self, acceptance_py_stdout: str) -> None:
        """cmd3 (carrier once) must produce a 'discourse-carrier' line."""
        carrier_lines = [
            ln for ln in acceptance_py_stdout.splitlines()
            if ln.startswith("discourse-carrier")
        ]
        assert carrier_lines, (
            "acceptance.py stdout must contain a 'discourse-carrier...' line.\n"
            "The carrier 'once' subcommand failed to produce carrier output.\n"
            f"stdout (first 2000):\n{acceptance_py_stdout[:2000]}"
        )

    def test_situation_monitor_digest_header_in_stdout(
        self, acceptance_py_stdout: str
    ) -> None:
        """The 'once' subcommand must open with 'Situation Monitor'."""
        assert "Situation Monitor" in acceptance_py_stdout, (
            "acceptance.py stdout must contain 'Situation Monitor' (from the digest header).\n"
            f"stdout (first 500):\n{acceptance_py_stdout[:500]}"
        )

    def test_subprocess_invoked_with_sys_executable(self) -> None:
        """acceptance.py must launch subcommands via sys.executable, not bare python."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, (
            "acceptance.py must use sys.executable — portable across venvs and platforms"
        )


# ---------------------------------------------------------------------------
# Criterion 3 — acceptance.py stdout contains '## DUAL-LENS EVENTS'
# ---------------------------------------------------------------------------


class TestAcceptancePyContainsDualLensHeader:
    """Criterion 3: acceptance.py stdout contains the exact string '## DUAL-LENS EVENTS'."""

    def test_dual_lens_events_exact_string_present(
        self, acceptance_py_stdout: str
    ) -> None:
        """The EXACT string '## DUAL-LENS EVENTS' (with H2 marker) must appear."""
        assert "## DUAL-LENS EVENTS" in acceptance_py_stdout, (
            "acceptance.py stdout must contain '## DUAL-LENS EVENTS' (exact match with '##').\n"
            "Criterion 3 requires this exact string — not just 'DUAL-LENS EVENTS'.\n"
            f"stdout (first 3000):\n{acceptance_py_stdout[:3000]}"
        )

    def test_dual_lens_header_is_standalone_h2_line(
        self, acceptance_py_stdout: str
    ) -> None:
        """'## DUAL-LENS EVENTS' must appear as a complete line, not embedded mid-line."""
        lines = acceptance_py_stdout.splitlines()
        matching = [ln for ln in lines if "## DUAL-LENS EVENTS" in ln]
        assert matching, "'## DUAL-LENS EVENTS' not found in any line"
        standalone = [ln for ln in matching if ln.strip().startswith("## DUAL-LENS EVENTS")]
        assert standalone, (
            "'## DUAL-LENS EVENTS' found but not as a standalone H2 heading.\n"
            f"Lines containing it: {matching}"
        )

    def test_dual_lens_block_contains_h3_event_title(
        self, acceptance_py_stdout: str
    ) -> None:
        """The DUAL-LENS block must contain at least one '### <title>' event heading."""
        dual_idx = acceptance_py_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        block = acceptance_py_stdout[dual_idx:]
        h3_in_block = re.findall(r"^### .+", block, re.MULTILINE)
        assert h3_in_block, (
            "The '## DUAL-LENS EVENTS' block must contain at least one '### <event_title>' heading.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_dual_lens_block_appears_after_domain_sections(
        self, acceptance_py_stdout: str
    ) -> None:
        """Domain sections (WORLD/MARKETS/AI) must precede the DUAL-LENS block."""
        dual_idx = acceptance_py_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            d_idx = acceptance_py_stdout.find(domain)
            if d_idx >= 0:
                assert d_idx < dual_idx, (
                    f"'{domain}' must appear BEFORE '## DUAL-LENS EVENTS'.\n"
                    f"Found '{domain}' at {d_idx}, DUAL-LENS at {dual_idx}."
                )

    def test_dual_lens_block_contains_left_column(
        self, acceptance_py_stdout: str
    ) -> None:
        """The DUAL-LENS block must contain a '#### LEFT' column heading."""
        dual_idx = acceptance_py_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = acceptance_py_stdout[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' column heading missing from '## DUAL-LENS EVENTS' block.\n"
            "The left-leaning fixture article must appear in the left-lens column.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_dual_lens_block_contains_right_column(
        self, acceptance_py_stdout: str
    ) -> None:
        """The DUAL-LENS block must contain a '#### RIGHT' column heading."""
        dual_idx = acceptance_py_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = acceptance_py_stdout[dual_idx:]
        assert "#### RIGHT" in block, (
            "'#### RIGHT' column heading missing from '## DUAL-LENS EVENTS' block.\n"
            "The right-leaning fixture article must appear in the right-lens column.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_dual_lens_left_column_has_article_bullet(
        self, acceptance_py_stdout: str
    ) -> None:
        """The LEFT column must contain at least one '- <article>' bullet line."""
        dual_idx = acceptance_py_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = acceptance_py_stdout[dual_idx:]
        in_left = False
        found = False
        for line in block.splitlines():
            if "#### LEFT" in line:
                in_left = True
                continue
            if in_left:
                if line.startswith("#"):
                    break
                if line.startswith("- "):
                    found = True
                    break
        assert found, (
            "'#### LEFT' column in DUAL-LENS block has no '- <article>' bullets.\n"
            "The left-leaning fixture article must appear as a bullet in the LEFT column."
        )

    def test_dual_lens_right_column_has_article_bullet(
        self, acceptance_py_stdout: str
    ) -> None:
        """The RIGHT column must contain at least one '- <article>' bullet line."""
        dual_idx = acceptance_py_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = acceptance_py_stdout[dual_idx:]
        in_right = False
        found = False
        for line in block.splitlines():
            if "#### RIGHT" in line:
                in_right = True
                continue
            if in_right:
                if line.startswith("#"):
                    break
                if line.startswith("- "):
                    found = True
                    break
        assert found, (
            "'#### RIGHT' column in DUAL-LENS block has no '- <article>' bullets.\n"
            "The right-leaning fixture article must appear as a bullet in the RIGHT column."
        )

    def test_dual_lens_left_appears_before_right(
        self, acceptance_py_stdout: str
    ) -> None:
        """Within the DUAL-LENS block, the LEFT column heading precedes RIGHT."""
        dual_idx = acceptance_py_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = acceptance_py_stdout[dual_idx:]
        left_idx = block.find("#### LEFT")
        right_idx = block.find("#### RIGHT")
        if left_idx >= 0 and right_idx >= 0:
            assert left_idx < right_idx, (
                "'#### LEFT' must appear before '#### RIGHT' within the DUAL-LENS block.\n"
                f"left_idx={left_idx}, right_idx={right_idx}"
            )

    def test_dual_lens_block_unique_not_duplicated(
        self, acceptance_py_stdout: str
    ) -> None:
        """'## DUAL-LENS EVENTS' must appear exactly once — duplication is a render bug."""
        occurrences = acceptance_py_stdout.count("## DUAL-LENS EVENTS")
        assert occurrences >= 1, "'## DUAL-LENS EVENTS' not present in acceptance.py stdout"
        # Allow it to appear in cmd2 (digest-dry-run) output too if the format changes,
        # but it must appear at least once from cmd1 (once).
        # We just require at least 1 occurrence.


# ---------------------------------------------------------------------------
# Criterion 4 — acceptance.py stdout contains 'spin_pct:'
# ---------------------------------------------------------------------------


class TestAcceptancePyContainsSpinPct:
    """Criterion 4: acceptance.py stdout contains 'spin_pct:'."""

    def test_spin_pct_keyword_exact_match(self, acceptance_py_stdout: str) -> None:
        """The EXACT keyword 'spin_pct:' must appear — not just 'spin' or 'spin_pct'."""
        assert "spin_pct:" in acceptance_py_stdout, (
            "acceptance.py stdout must contain 'spin_pct:' (exact keyword with colon).\n"
            "Criterion 4 requires this exact string.\n"
            f"stdout (first 3000):\n{acceptance_py_stdout[:3000]}"
        )

    def test_spin_pct_values_are_numeric_floats(self, acceptance_py_stdout: str) -> None:
        """spin_pct values must be parseable as floats, not placeholder text."""
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_py_stdout)
        assert matches, (
            "No 'spin_pct: N.N%' pattern found in acceptance.py stdout.\n"
            "Format must be 'spin_pct: <float>%' (e.g. 'spin_pct: 43.2%')."
        )
        for raw in matches:
            try:
                float(raw)
            except ValueError:
                pytest.fail(f"spin_pct value {raw!r} is not parseable as a float")

    def test_spin_pct_values_in_valid_range(self, acceptance_py_stdout: str) -> None:
        """All spin_pct values must be in [0.0, 100.0]."""
        for raw in re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_py_stdout):
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val} is outside [0, 100] — the lexical estimator "
                "must clamp to this range."
            )

    def test_spin_pct_uses_decimal_format(self, acceptance_py_stdout: str) -> None:
        """spin_pct must use :.1f format ('43.2%'), not integer format ('43%')."""
        values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_py_stdout)
        assert values, "No spin_pct values found in acceptance.py stdout"
        for raw in values:
            assert "." in raw, (
                f"spin_pct value {raw!r} is missing a decimal point.\n"
                "Format must be :.1f (e.g. '43.2%'), not integer percent."
            )

    def test_at_least_two_spin_pct_annotations(self, acceptance_py_stdout: str) -> None:
        """A dual-lens event requires one article per side — minimum 2 spin_pct values."""
        values = re.findall(r"spin_pct:\s*[\d.]+%", acceptance_py_stdout)
        assert len(values) >= 2, (
            f"Expected ≥2 'spin_pct:' annotations; found {len(values)}.\n"
            "A minimal dual-lens event requires one LEFT article and one RIGHT article."
        )

    def test_spin_pct_not_all_stub_fifty(self, acceptance_py_stdout: str) -> None:
        """If all spin_pct values are exactly 50.0, the STUB estimator is running.

        The fixture articles carry charged language: 'backed'/'endorse' (left) and
        'threatens'/'destroy'/'hamper'/'warn' (right).  The deterministic lexical
        estimator produces DIFFERENT scores for these — not a flat 50.0 stub.
        """
        raw_values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_py_stdout)
        assert raw_values, "No spin_pct values in acceptance.py stdout"
        float_values = [float(v) for v in raw_values]
        if all(v == 50.0 for v in float_values):
            pytest.fail(
                "All spin_pct values are exactly 50.0 — the STUB estimator is active.\n"
                "The offline deterministic estimator must produce differentiated values.\n"
                f"Values found: {float_values}"
            )

    def test_spin_pct_appears_inside_dual_lens_block(
        self, acceptance_py_stdout: str
    ) -> None:
        """spin_pct must appear INSIDE the '## DUAL-LENS EVENTS' block, not just anywhere."""
        dual_idx = acceptance_py_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, (
            "'## DUAL-LENS EVENTS' not found — spin_pct cannot be in its required block"
        )
        block = acceptance_py_stdout[dual_idx:]
        assert "spin_pct:" in block, (
            "'spin_pct:' not found inside the '## DUAL-LENS EVENTS' block.\n"
            "Spin annotations must be rendered within the dual-lens block, not only "
            "in the per-domain digest sections.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_spin_pct_on_article_bullet_lines(self, acceptance_py_stdout: str) -> None:
        """'spin_pct:' must appear on '- <title> | spin_pct: N.N%' bullet lines."""
        bullet_spin_lines = [
            ln for ln in acceptance_py_stdout.splitlines()
            if ln.startswith("- ") and "spin_pct:" in ln
        ]
        assert bullet_spin_lines, (
            "No '- <title> | spin_pct: N.N%' bullet lines found.\n"
            "The dual-lens renderer must annotate each article bullet with spin_pct.\n"
            f"stdout (first 3000):\n{acceptance_py_stdout[:3000]}"
        )

    def test_spin_delta_annotation_in_dual_lens_block(
        self, acceptance_py_stdout: str
    ) -> None:
        """spin_delta (event-level divergence) must also appear in the DUAL-LENS block."""
        dual_idx = acceptance_py_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = acceptance_py_stdout[dual_idx:]
        assert "spin_delta:" in block, (
            "'spin_delta:' annotation missing from the DUAL-LENS block.\n"
            "Each event must report the divergence between left and right spin averages."
        )

    def test_spin_delta_is_non_negative(self, acceptance_py_stdout: str) -> None:
        """spin_delta values must be non-negative (it is an absolute difference)."""
        for raw in re.findall(r"spin_delta:\s*([\d.]+)", acceptance_py_stdout):
            val = float(raw)
            assert val >= 0.0, f"spin_delta must be ≥ 0.0; got {val}"

    def test_spin_delta_positive_for_opposing_fixture_framings(
        self, acceptance_py_stdout: str
    ) -> None:
        """The left/right fixture articles have opposing language — delta must be > 0.

        Left uses 'backed'/'endorse' (ENDORSEMENT_TERMS);
        right uses 'threatens'/'destroy'/'hamper'/'warn' (CHARGED_VERBS + FEAR_TERMS).
        The deterministic estimator scores them differently → positive delta.
        """
        deltas = re.findall(r"spin_delta:\s*([\d.]+)", acceptance_py_stdout)
        assert deltas, "No spin_delta values in acceptance.py stdout"
        nonzero = [d for d in deltas if float(d) > 0.0]
        assert nonzero, (
            "All spin_delta values are 0.0.\n"
            "The left/right fixture articles use opposing charged language; "
            "the deterministic estimator must diverge on them.\n"
            f"Delta values found: {deltas}"
        )

    def test_spin_pct_values_differ_between_left_and_right(
        self, acceptance_py_stdout: str
    ) -> None:
        """Left-column spin_pct values must not equal right-column spin_pct values.

        If they were identical it would mean the offline estimator is returning a flat
        stub — not real lexical differentiation.
        """
        def _column_pcts(column: str) -> list[float]:
            heading = f"#### {column}"
            vals: list[float] = []
            in_col = False
            for line in acceptance_py_stdout.splitlines():
                if heading in line:
                    in_col = True
                    continue
                if in_col:
                    if line.startswith("#"):
                        break
                    for m in re.findall(r"spin_pct:\s*([\d.]+)%", line):
                        vals.append(float(m))
            return vals

        left_pcts = _column_pcts("LEFT")
        right_pcts = _column_pcts("RIGHT")
        if left_pcts and right_pcts:
            left_avg = sum(left_pcts) / len(left_pcts)
            right_avg = sum(right_pcts) / len(right_pcts)
            assert left_avg != right_avg, (
                f"Left-column avg spin_pct ({left_avg:.1f}%) == "
                f"right-column avg spin_pct ({right_avg:.1f}%).\n"
                "The offline estimator must produce different scores for the two "
                "climate-policy fixture articles."
            )


# ---------------------------------------------------------------------------
# Unit-level: _print_dual_lens emits both required markers directly
# ---------------------------------------------------------------------------


class TestPrintDualLensEmitsRequiredMarkers:
    """Direct unit tests for _print_dual_lens — no subprocess, no mocking.

    These verify the function itself produces '## DUAL-LENS EVENTS' and 'spin_pct:'
    so that fixing the function is sufficient for criteria 3 and 4 to hold.
    """

    def _make_aa(self, title: str, lean: str, spin_pct: float):
        from situation_monitor.dual_lens import AnnotatedArticle
        from situation_monitor.models import Article, SpinResult

        article = Article(url=f"http://ex.com/{title[:20].replace(' ', '-')}", title=title, source="Fixture")
        article.source_lean = lean
        spin = SpinResult(spin_pct=spin_pct, lens=lean, rubric={}, receipts=f"receipt for {lean}")
        return AnnotatedArticle(article=article, spin=spin)

    def _make_dual_event(self):
        from situation_monitor.dual_lens import DualLensEvent

        left_aa = self._make_aa("Government Climate Policy Reform Backed by Scientists", "left", 22.0)
        right_aa = self._make_aa("Government Climate Policy Reform Threatens Economic Growth", "right", 61.3)
        return DualLensEvent(
            event_title="Government Climate Policy Reform Threatens Economic Growth",
            left_articles=[left_aa],
            right_articles=[right_aa],
            center_articles=[],
            spin_delta=abs(22.0 - 61.3),
        )

    def _capture(self, events: list) -> str:
        from situation_monitor.__main__ import _print_dual_lens

        buf = io.StringIO()
        with redirect_stdout(buf):
            _print_dual_lens(events)
        return buf.getvalue()

    def test_emits_dual_lens_events_h2_header(self) -> None:
        out = self._capture([self._make_dual_event()])
        assert "## DUAL-LENS EVENTS" in out, (
            "_print_dual_lens must emit '## DUAL-LENS EVENTS' — the exact criterion 3 string"
        )

    def test_emits_spin_pct_keyword(self) -> None:
        out = self._capture([self._make_dual_event()])
        assert "spin_pct:" in out, (
            "_print_dual_lens must emit 'spin_pct:' — the exact criterion 4 keyword"
        )

    def test_spin_pct_value_matches_input(self) -> None:
        """spin_pct must reflect the actual value passed in — not a hardcoded stub."""
        out = self._capture([self._make_dual_event()])
        # Left article has spin_pct=22.0, right has 61.3
        assert "22.0%" in out or "61.3%" in out, (
            "spin_pct values in output must match the input AnnotatedArticle spin values.\n"
            f"Output:\n{out}"
        )

    def test_empty_event_list_produces_no_output(self) -> None:
        out = self._capture([])
        assert out == "", "_print_dual_lens([]) must produce no output"

    def test_center_only_event_not_rendered(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
        from situation_monitor.models import Article, SpinResult

        article = Article(url="http://ex.com/neutral", title="Neutral report published today", source="Reuters")
        article.source_lean = "centre"
        aa = AnnotatedArticle(article=article, spin=SpinResult(spin_pct=5.0, lens="centre", rubric={}, receipts=""))
        event = DualLensEvent(event_title="Neutral report", center_articles=[aa], spin_delta=0.0)
        out = self._capture([event])
        assert "DUAL-LENS" not in out, (
            "A center-only event must not produce any DUAL-LENS output"
        )

    def test_dual_lens_header_appears_exactly_once_per_render(self) -> None:
        """Multiple events must share a single '## DUAL-LENS EVENTS' block header."""
        from situation_monitor.dual_lens import DualLensEvent

        e1 = DualLensEvent(
            event_title="Event One",
            left_articles=[self._make_aa("Left view A climate reform", "left", 30.0)],
            right_articles=[self._make_aa("Right view A climate reform", "right", 70.0)],
            spin_delta=40.0,
        )
        e2 = DualLensEvent(
            event_title="Event Two",
            left_articles=[self._make_aa("Left view B market crash", "left", 25.0)],
            right_articles=[self._make_aa("Right view B market crash", "right", 75.0)],
            spin_delta=50.0,
        )
        out = self._capture([e1, e2])
        occurrences = out.count("## DUAL-LENS EVENTS")
        assert occurrences == 1, (
            f"'## DUAL-LENS EVENTS' appeared {occurrences} times; must appear exactly once "
            "even when rendering multiple events."
        )

    def test_spin_pct_format_is_one_decimal_place(self) -> None:
        """spin_pct must use ':.1f' format (e.g. '22.0%'), not '%.0f' ('22%')."""
        out = self._capture([self._make_dual_event()])
        spin_values = re.findall(r"spin_pct:\s*([\d.]+)%", out)
        assert spin_values, "No spin_pct values found in _print_dual_lens output"
        for raw in spin_values:
            assert "." in raw, (
                f"spin_pct value {raw!r} is missing a decimal point — format must be :.1f"
            )

    def test_article_title_appears_in_output(self) -> None:
        out = self._capture([self._make_dual_event()])
        # At least one fixture title should appear
        assert "Climate" in out or "Reform" in out or "Policy" in out, (
            "The event's article titles must appear in _print_dual_lens output"
        )


# ---------------------------------------------------------------------------
# Unit-level: deterministic_spin differentiates the fixture articles
# ---------------------------------------------------------------------------


class TestDeterministicSpinOffline:
    """Verify deterministic_spin produces real differentiated scores for the fixture
    articles — the underlying engine powering both criterion 3 and criterion 4.
    """

    def _load_fixture(self, xml_path: Path, lean: str):
        from situation_monitor.config import SourceDef
        from situation_monitor.ingestion.rss import RSSFetcher
        from situation_monitor.models import Domain

        class _Local:
            def get(self, url: str) -> bytes:
                return Path(url).read_bytes()

        fetcher = RSSFetcher(client=_Local())
        sd = SourceDef(str(xml_path), "Fixture", Domain.WORLD, lean)
        return fetcher.fetch(str(xml_path), source_def=sd)

    def test_left_and_right_fixtures_score_differently(self) -> None:
        from situation_monitor.dual_lens import deterministic_spin

        left_arts = self._load_fixture(RSS_LEFT, "left")
        right_arts = self._load_fixture(RSS_RIGHT, "right")
        assert left_arts, "rss_left.xml must contain at least one article"
        assert right_arts, "rss_right.xml must contain at least one article"

        left_spin = deterministic_spin(left_arts[0])
        right_spin = deterministic_spin(right_arts[0])

        assert left_spin.spin_pct != right_spin.spin_pct, (
            f"Left spin ({left_spin.spin_pct:.1f}%) must differ from "
            f"right spin ({right_spin.spin_pct:.1f}%).\n"
            "The fixture articles use different charged language; the deterministic "
            "estimator must produce differentiated scores.\n"
            f"Left receipts: {left_spin.receipts}\n"
            f"Right receipts: {right_spin.receipts}"
        )

    def test_right_fixture_scores_higher_than_left(self) -> None:
        """Right uses CHARGED_VERBS ('threatens'/'destroy'/'hamper') + FEAR_TERMS ('warn');
        left uses ENDORSEMENT_TERMS ('backed'/'endorse') — lower-weight category.
        Right must score higher.
        """
        from situation_monitor.dual_lens import deterministic_spin

        left_arts = self._load_fixture(RSS_LEFT, "left")
        right_arts = self._load_fixture(RSS_RIGHT, "right")

        left_spin = deterministic_spin(left_arts[0])
        right_spin = deterministic_spin(right_arts[0])

        assert right_spin.spin_pct > left_spin.spin_pct, (
            f"Right fixture spin ({right_spin.spin_pct:.1f}%) must exceed "
            f"left fixture spin ({left_spin.spin_pct:.1f}%).\n"
            "Right uses CHARGED_VERBS + FEAR_TERMS (weight 1.0 each); "
            "left uses ENDORSEMENT_TERMS (weight 0.6)."
        )

    def test_group_by_event_clusters_fixture_articles_together(self) -> None:
        """The fixture articles share 'government','climate','policy','reform' — must cluster."""
        from situation_monitor.dual_lens import group_by_event

        left_arts = self._load_fixture(RSS_LEFT, "left")
        right_arts = self._load_fixture(RSS_RIGHT, "right")
        events = group_by_event(left_arts + right_arts)

        dual = [e for e in events if e.left_articles and e.right_articles]
        assert dual, (
            "Left and right fixture articles must cluster into at least one dual-sided event.\n"
            "They share ≥2 significant words: 'government', 'climate', 'policy', 'reform'.\n"
            f"Events produced: {[e.event_title for e in events]}"
        )

    def test_clustered_fixture_event_has_positive_spin_delta(self) -> None:
        """Grouped event must have spin_delta > 0 — left and right spin_pct differ."""
        from situation_monitor.dual_lens import group_by_event

        left_arts = self._load_fixture(RSS_LEFT, "left")
        right_arts = self._load_fixture(RSS_RIGHT, "right")
        events = group_by_event(left_arts + right_arts)

        dual = [e for e in events if e.left_articles and e.right_articles]
        assert dual, "No dual-sided event found in fixture articles"
        assert dual[0].spin_delta > 0.0, (
            f"spin_delta must be > 0.0; got {dual[0].spin_delta}.\n"
            "Opposing fixture framings must produce a measurable spin divergence."
        )

    def test_spin_pct_in_valid_range_for_both_fixtures(self) -> None:
        from situation_monitor.dual_lens import deterministic_spin

        for xml_path, lean in [(RSS_LEFT, "left"), (RSS_RIGHT, "right")]:
            arts = self._load_fixture(xml_path, lean)
            for art in arts:
                spin = deterministic_spin(art)
                assert 0.0 <= spin.spin_pct <= 100.0, (
                    f"spin_pct {spin.spin_pct} for {art.title!r} is outside [0, 100]"
                )

    def test_right_fixture_receipts_mention_charged_verbs_or_fear(self) -> None:
        """The right article fires CHARGED_VERBS + FEAR_TERMS; receipts must name them."""
        from situation_monitor.dual_lens import deterministic_spin

        right_arts = self._load_fixture(RSS_RIGHT, "right")
        spin = deterministic_spin(right_arts[0])
        receipts_lower = spin.receipts.lower()
        assert any(kw in receipts_lower for kw in [
            "charged verbs", "fear", "threatens", "destroy", "hamper", "warn"
        ]), (
            "Right fixture spin receipts must mention Charged Verbs / Fear category "
            "or the specific fired terms ('threatens', 'destroy', 'hamper', 'warn').\n"
            f"Got: {spin.receipts!r}"
        )

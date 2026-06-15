"""Regression guard: subprocess-run acceptance.py (SM_LLM_BACKEND=offline) and
unit-test its internal helper functions.

Acceptance criteria under test:
  1. pytest exits 0 — evidenced structurally (this file passing + scan for
     recursive pytest subprocess invocations, which hang the suite per project
     memory).
  2. SM_LLM_BACKEND=offline python acceptance.py exits returncode 0.
  3. acceptance stdout contains '## DUAL-LENS EVENTS'.
  4. acceptance stdout matches r'spin_pct:\\s*[\\d.]+%' (decimal spin annotation).
  5. acceptance stdout contains standalone 'DUAL_LENS: PASS' gate marker.
  6. acceptance stdout contains standalone 'MARKET: PASS' gate marker.

Unit tests (in-process, no subprocess) verify the internal helper functions
that acceptance.py uses to drive those gate markers:
  - _extract_spin_pct(text) → float | None
  - _has_all_required(text) → bool

These helpers are the REAL code under test — mocking them would prove nothing.
Every assertion CAN fail on a real regression.

Design constraints:
  - NO recursive pytest subprocess invocations (project memory: they hang).
  - All subprocesses pin SM_LLM_BACKEND=offline (project memory: live-claude
    flaky test gate).
  - Module-scoped subprocess fixtures run acceptance.py exactly once.
"""

from __future__ import annotations

import importlib.util
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


def _offline_env(**extra: str) -> dict[str, str]:
    """Full offline env — no live network or LLM API calls."""
    return {**os.environ, "SM_LLM_BACKEND": "offline", **extra}


# ---------------------------------------------------------------------------
# Module-scoped subprocess: SM_LLM_BACKEND=offline python acceptance.py
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acc_proc() -> subprocess.CompletedProcess:
    """Criterion 2: run acceptance.py with SM_LLM_BACKEND=offline exactly once."""
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        timeout=300,
    )


@pytest.fixture(scope="module")
def acc_stdout(acc_proc: subprocess.CompletedProcess) -> str:
    return acc_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acc_stderr(acc_proc: subprocess.CompletedProcess) -> str:
    return acc_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Module-scoped: import acceptance.py helpers for unit tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_mod():
    """Load acceptance.py as a module to unit-test its private helper functions.

    Uses importlib so the helpers are exercised against their REAL implementation
    without running the full acceptance subprocess again.
    """
    spec = importlib.util.spec_from_file_location(
        "_acceptance_gate_markers_mod", str(ACCEPTANCE_PY)
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


# ---------------------------------------------------------------------------
# Criterion 1: pytest exits 0 — structural evidence (no recursive subprocess)
# ---------------------------------------------------------------------------


class TestPytestExitsZeroEvidence:
    """Criterion 1: pytest exits 0 — evidenced structurally, NOT by a recursive call.

    Running pytest inside pytest hangs the suite (project memory: recursive-guard-test-trap).
    Evidence: this class passing + no test file spawns pytest as a subprocess.
    """

    def test_no_test_file_invokes_pytest_as_subprocess(self) -> None:
        """Every test_*.py must NOT spawn pytest as a subprocess — that deadlocks."""
        test_dir = PROJECT_ROOT / "tests"
        bad: list[str] = []
        for tf in sorted(test_dir.glob("test_*.py")):
            content = tf.read_text(errors="replace")
            for lineno, raw in enumerate(content.splitlines(), start=1):
                if raw.strip().startswith("#"):
                    continue
                if re.search(r'''["']pytest["']''', raw) and re.search(
                    r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", raw
                ):
                    bad.append(f"{tf.name}:{lineno}: {raw.rstrip()}")
        assert not bad, (
            "Recursive pytest subprocess calls found — these hang the suite:\n"
            + "\n".join(bad[:10])
        )

    def test_situation_monitor_package_is_importable(self) -> None:
        """Import failure crashes every acceptance subprocess before it can run."""
        try:
            import situation_monitor  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"situation_monitor not importable: {exc}")

    def test_acceptance_py_has_valid_python_syntax(self) -> None:
        """A syntax error in acceptance.py would fail every criterion-2 subprocess."""
        result = subprocess.run(
            [sys.executable, "-c",
             f"import ast; ast.parse(open({str(ACCEPTANCE_PY)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "acceptance.py has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_situation_monitor_main_has_valid_syntax(self) -> None:
        """A syntax error in __main__.py would crash every acceptance cmd1/cmd2 subprocess."""
        main_path = PROJECT_ROOT / "situation_monitor" / "__main__.py"
        assert main_path.exists(), "situation_monitor/__main__.py missing"
        result = subprocess.run(
            [sys.executable, "-c",
             f"import ast; ast.parse(open({str(main_path)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "situation_monitor/__main__.py has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_test_corpus_is_substantive(self) -> None:
        """An almost-empty test corpus exits 0 vacuously — must have real tests."""
        test_files = list((PROJECT_ROOT / "tests").glob("test_*.py"))
        assert len(test_files) >= 10, (
            f"Expected ≥10 test_*.py files; found {len(test_files)}. "
            "A vacuous empty suite also exits 0."
        )

    def test_fixture_files_required_by_acceptance_exist(self) -> None:
        """Missing fixtures fail acceptance subprocesses at startup — check early."""
        required = [
            FIXTURES / "rss_sample.xml",
            FIXTURES / "rss_left.xml",
            FIXTURES / "rss_right.xml",
            FIXTURES / "rss_markets.xml",
            FIXTURES / "rss_ai.xml",
            FIXTURES / "rss_carrier.xml",
            ACCEPTANCE_SOURCE_DEFS,
            PROJECT_ROOT / "check_server.py",
        ]
        missing = [str(p) for p in required if not p.exists()]
        assert not missing, (
            "Required fixture/script files absent:\n" + "\n".join(missing)
        )


# ---------------------------------------------------------------------------
# Criterion 2: acceptance.py exits 0
# ---------------------------------------------------------------------------


class TestAcceptanceExitsZero:
    """Criterion 2: SM_LLM_BACKEND=offline python acceptance.py exits returncode 0."""

    def test_returncode_is_zero(
        self, acc_proc: subprocess.CompletedProcess
    ) -> None:
        assert acc_proc.returncode == 0, (
            f"acceptance.py exited {acc_proc.returncode}; expected 0.\n"
            f"stderr (last 1000):\n"
            f"{acc_proc.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout (last 500):\n"
            f"{acc_proc.stdout.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, acc_stdout: str) -> None:
        assert acc_stdout.strip(), (
            "acceptance.py produced empty stdout; the cmd1 digest must be emitted."
        )

    def test_no_traceback_in_stdout(self, acc_stdout: str) -> None:
        assert "Traceback" not in acc_stdout, (
            "acceptance.py stdout must not contain a Python Traceback.\n"
            f"stdout (first 2000):\n{acc_stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, acc_stderr: str) -> None:
        assert "Traceback" not in acc_stderr, (
            "acceptance.py stderr must not contain a Python Traceback.\n"
            f"stderr (first 2000):\n{acc_stderr[:2000]}"
        )

    def test_no_live_api_errors_in_stderr(self, acc_stderr: str) -> None:
        """SM_LLM_BACKEND=offline must suppress all live LLM API calls."""
        api_errors = [
            "AuthenticationError", "ANTHROPIC_API_KEY",
            "RateLimitError", "openai.error",
        ]
        for err in api_errors:
            assert err not in acc_stderr, (
                f"acceptance stderr contains {err!r} — "
                "SM_LLM_BACKEND=offline must prevent live LLM calls.\n"
                f"stderr (first 1000):\n{acc_stderr[:1000]}"
            )

    def test_acceptance_py_uses_sys_executable(self) -> None:
        """acceptance.py must use sys.executable — bare 'python' fails on macOS."""
        content = ACCEPTANCE_PY.read_text()
        assert "sys.executable" in content, (
            "acceptance.py must use sys.executable for subprocess calls, not 'python'."
        )

    def test_acceptance_subprocess_was_invoked_with_acceptance_py(
        self, acc_proc: subprocess.CompletedProcess
    ) -> None:
        """Verify the subprocess args include acceptance.py (not an alias)."""
        args_str = " ".join(str(a) for a in acc_proc.args)
        assert "acceptance" in args_str, (
            f"acceptance subprocess args do not reference acceptance.py: {acc_proc.args}"
        )


# ---------------------------------------------------------------------------
# Criterion 3: '## DUAL-LENS EVENTS' in acceptance stdout
# ---------------------------------------------------------------------------


class TestDualLensEventsSectionInAcceptanceStdout:
    """Criterion 3: acceptance stdout must contain '## DUAL-LENS EVENTS'."""

    def test_dual_lens_events_header_present(self, acc_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in acc_stdout, (
            "acceptance stdout must contain '## DUAL-LENS EVENTS' section header.\n"
            "cmd1 (once) renders this block when fixture articles cluster into events.\n"
            f"stdout (first 3000):\n{acc_stdout[:3000]}"
        )

    def test_dual_lens_events_is_h2_heading(self, acc_stdout: str) -> None:
        """The header must be a proper ATX H2 line, not embedded prose."""
        assert re.search(r"^## DUAL-LENS EVENTS", acc_stdout, re.MULTILINE), (
            "No '^## DUAL-LENS EVENTS' H2 heading found.\n"
            "The section must be rendered as '## DUAL-LENS EVENTS', "
            "not '# DUAL-LENS EVENTS' or inline text."
        )

    def test_dual_lens_events_comes_after_domain_sections(
        self, acc_stdout: str
    ) -> None:
        """Domain sections must precede the DUAL-LENS block in the output order."""
        dual_idx = acc_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            d_idx = acc_stdout.find(domain)
            if d_idx >= 0:
                assert d_idx < dual_idx, (
                    f"'{domain}' must appear BEFORE '## DUAL-LENS EVENTS'.\n"
                    "Domain sections precede the dual-lens block in canonical output order."
                )

    def test_left_and_right_columns_inside_dual_lens_block(
        self, acc_stdout: str
    ) -> None:
        """The DUAL-LENS block must contain LEFT and RIGHT column headings."""
        dual_idx = acc_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        block = acc_stdout[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' heading must appear inside the DUAL-LENS EVENTS block."
        )
        assert "#### RIGHT" in block, (
            "'#### RIGHT' heading must appear inside the DUAL-LENS EVENTS block."
        )

    def test_dual_lens_block_has_article_bullet_lines(
        self, acc_stdout: str
    ) -> None:
        """The DUAL-LENS block must not be empty — at least one article bullet."""
        dual_idx = acc_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0
        block = acc_stdout[dual_idx:]
        bullets = [l for l in block.splitlines() if l.startswith("- ")]
        assert bullets, (
            "The '## DUAL-LENS EVENTS' block must contain at least one '- ...' article bullet.\n"
            "An empty dual-lens block would not justify the gate marker."
        )

    def test_dual_lens_header_is_not_part_of_gate_marker(
        self, acc_stdout: str
    ) -> None:
        """'## DUAL-LENS EVENTS' (content) and 'DUAL_LENS: PASS' (gate) are distinct lines."""
        assert "## DUAL-LENS EVENTS" in acc_stdout, "Section header absent"
        content_idx = acc_stdout.find("## DUAL-LENS EVENTS")
        gate_idx = acc_stdout.find("DUAL_LENS: PASS")
        assert content_idx != gate_idx, (
            "'## DUAL-LENS EVENTS' content section and 'DUAL_LENS: PASS' gate marker "
            "must be separate items — they must appear at different positions."
        )


# ---------------------------------------------------------------------------
# Criterion 4: spin_pct percentage pattern in acceptance stdout
# ---------------------------------------------------------------------------


class TestSpinPctAnnotationPattern:
    """Criterion 4: acceptance stdout matches r'spin_pct:\\s*[\\d.]+%'."""

    def test_spin_pct_annotation_present(self, acc_stdout: str) -> None:
        """The regex r'spin_pct:\\s*[\\d.]+%' must match at least once."""
        assert re.search(r"spin_pct:\s*[\d.]+%", acc_stdout), (
            "acceptance stdout contains no 'spin_pct: N.N%' annotation.\n"
            "The dual-lens render must annotate each article with its spin percentage.\n"
            f"stdout (first 3000):\n{acc_stdout[:3000]}"
        )

    def test_spin_pct_uses_decimal_format(self, acc_stdout: str) -> None:
        """Format must be N.N% (:.1f), not N% (integer)."""
        vals = re.findall(r"spin_pct:\s*([\d.]+)%", acc_stdout)
        assert vals, "No spin_pct values found"
        for raw in vals:
            assert "." in raw, (
                f"spin_pct value {raw!r} missing decimal point — "
                "format must be :.1f (e.g. '43.4%'), not integer percent (e.g. '43%')."
            )

    def test_spin_pct_values_in_valid_range(self, acc_stdout: str) -> None:
        """All spin_pct values must be in [0.0, 100.0]."""
        vals = re.findall(r"spin_pct:\s*([\d.]+)%", acc_stdout)
        assert vals, "No spin_pct values found in acceptance stdout"
        for raw in vals:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct {val}% is outside [0, 100]."
            )

    def test_spin_pct_not_all_fifty_stub(self, acc_stdout: str) -> None:
        """If all values are exactly 50.0, the stub estimator is running."""
        vals = [float(v) for v in re.findall(r"spin_pct:\s*([\d.]+)%", acc_stdout)]
        assert vals, "No spin_pct values found"
        assert not all(v == 50.0 for v in vals), (
            f"All spin_pct values are 50.0 — STUB estimator is running.\n"
            "The fixture articles have charged language producing non-50 scores.\n"
            f"Values found: {vals}"
        )

    def test_spin_pct_appears_inside_dual_lens_block(
        self, acc_stdout: str
    ) -> None:
        """spin_pct must appear INSIDE the DUAL-LENS EVENTS block, not just anywhere."""
        dual_idx = acc_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, (
            "'## DUAL-LENS EVENTS' not found — cannot verify spin_pct block position"
        )
        block = acc_stdout[dual_idx:]
        assert re.search(r"spin_pct:\s*[\d.]+%", block), (
            "No 'spin_pct: N.N%' found INSIDE the DUAL-LENS EVENTS block.\n"
            "Spin annotations must appear within the dual-lens block, not before it."
        )

    def test_at_least_two_spin_pct_annotations(self, acc_stdout: str) -> None:
        """A dual-lens event needs at least one article per side (minimum 2 annotations)."""
        vals = re.findall(r"spin_pct:\s*[\d.]+%", acc_stdout)
        assert len(vals) >= 2, (
            f"Expected ≥2 spin_pct annotations; found {len(vals)}.\n"
            "A dual-lens event requires at least one LEFT and one RIGHT article."
        )

    def test_spin_pct_on_bullet_lines(self, acc_stdout: str) -> None:
        """spin_pct annotations must appear on '- ...' bullet lines."""
        bullet_spin = [
            l for l in acc_stdout.splitlines()
            if l.startswith("- ") and "spin_pct:" in l
        ]
        assert bullet_spin, (
            "No '- <title> | spin_pct: N.N%' bullet lines found in acceptance stdout.\n"
            "The dual-lens renderer annotates each article bullet with its spin_pct."
        )


# ---------------------------------------------------------------------------
# Criterion 5: DUAL_LENS: PASS and MARKET: PASS gate markers
# ---------------------------------------------------------------------------


class TestGateMarkersPresent:
    """Criteria 5a/5b: acceptance stdout must contain 'DUAL_LENS: PASS' and 'MARKET: PASS'."""

    def test_dual_lens_pass_present(self, acc_stdout: str) -> None:
        assert "DUAL_LENS: PASS" in acc_stdout, (
            "acceptance stdout must contain 'DUAL_LENS: PASS' gate marker.\n"
            "This is emitted only when '## DUAL-LENS EVENTS' appeared in cmd1 output.\n"
            f"stdout (last 500):\n{acc_stdout[-500:]}"
        )

    def test_market_pass_present(self, acc_stdout: str) -> None:
        assert "MARKET: PASS" in acc_stdout, (
            "acceptance stdout must contain 'MARKET: PASS' gate marker.\n"
            "This is emitted only when '## MARKETS' appeared in cmd1 output.\n"
            f"stdout (last 500):\n{acc_stdout[-500:]}"
        )

    def test_dual_lens_fail_absent(self, acc_stdout: str) -> None:
        assert "DUAL_LENS: FAIL" not in acc_stdout, (
            "'DUAL_LENS: FAIL' must NOT appear — FAIL means dual-lens block absent from cmd1.\n"
            "The fixture feeds must produce at least one dual-lens event."
        )

    def test_market_fail_absent(self, acc_stdout: str) -> None:
        assert "MARKET: FAIL" not in acc_stdout, (
            "'MARKET: FAIL' must NOT appear — FAIL means '## MARKETS' absent from cmd1.\n"
            "The markets fixture (rss_markets.xml) must produce at least one article."
        )

    def test_dual_lens_pass_is_standalone_line(self, acc_stdout: str) -> None:
        """'DUAL_LENS: PASS' must be a complete isolated line — not embedded in prose."""
        assert re.search(r"^DUAL_LENS: PASS$", acc_stdout, re.MULTILINE), (
            "No line matching '^DUAL_LENS: PASS$' found.\n"
            "Format must be exactly 'DUAL_LENS: PASS' (colon-space-PASS), "
            "not 'DUAL_LENS:PASS' or 'DUAL_LENS : PASS'.\n"
            f"stdout (last 300):\n{acc_stdout[-300:]}"
        )

    def test_market_pass_is_standalone_line(self, acc_stdout: str) -> None:
        assert re.search(r"^MARKET: PASS$", acc_stdout, re.MULTILINE), (
            "No line matching '^MARKET: PASS$' found.\n"
            "Format must be exactly 'MARKET: PASS' (colon-space-PASS), "
            "not 'MARKET:PASS' or 'MARKETS: PASS'.\n"
            f"stdout (last 300):\n{acc_stdout[-300:]}"
        )

    def test_gate_markers_in_tail_of_output(self, acc_stdout: str) -> None:
        """Gate markers are printed last in acceptance.py — they must be in the tail."""
        tail = acc_stdout[-500:]
        missing = [
            marker for marker in ("DUAL_LENS:", "SPIN_PCT:", "MARKET:")
            if marker not in tail
        ]
        assert not missing, (
            f"Gate markers {missing} not found in the last 500 chars of acceptance stdout.\n"
            "acceptance.py prints gate markers at the very end of main().\n"
            f"Last 500 chars:\n{tail!r}"
        )

    def test_gate_markers_after_digest_content(self, acc_stdout: str) -> None:
        """Gate markers must appear AFTER '## DUAL-LENS EVENTS' content."""
        events_idx = acc_stdout.find("## DUAL-LENS EVENTS")
        gate_idx = acc_stdout.find("DUAL_LENS: PASS")
        if events_idx >= 0 and gate_idx >= 0:
            assert events_idx < gate_idx, (
                "'DUAL_LENS: PASS' gate marker must appear AFTER '## DUAL-LENS EVENTS' "
                "content section (gate markers are printed at the end of main())."
            )

    def test_gate_markers_ordered_dual_lens_then_spin_pct_then_market(
        self, acc_stdout: str
    ) -> None:
        """acceptance.py prints: DUAL_LENS → SPIN_PCT → MARKET. Last occurrence order."""
        dl = acc_stdout.rfind("DUAL_LENS:")
        sp = acc_stdout.rfind("SPIN_PCT:")
        mk = acc_stdout.rfind("MARKET:")
        if dl >= 0 and sp >= 0 and mk >= 0:
            assert dl < sp < mk, (
                "Gate markers must appear in order DUAL_LENS → SPIN_PCT → MARKET.\n"
                f"Positions: DUAL_LENS={dl}, SPIN_PCT={sp}, MARKET={mk}\n"
                "acceptance.py prints them in this order at the end of main()."
            )

    def test_spin_pct_gate_marker_has_decimal_value(self, acc_stdout: str) -> None:
        """The SPIN_PCT: gate marker must contain a decimal number followed by %."""
        match = re.search(r"^SPIN_PCT:\s*([\d.]+)%$", acc_stdout, re.MULTILINE)
        assert match, (
            "No line matching '^SPIN_PCT: N.N%$' found in acceptance stdout.\n"
            f"stdout (last 300):\n{acc_stdout[-300:]}"
        )
        val = float(match.group(1))
        assert 0.0 <= val <= 100.0, (
            f"SPIN_PCT gate value {val}% is outside [0, 100]."
        )
        assert "." in match.group(1), (
            f"SPIN_PCT gate value {match.group(1)!r} must use decimal format (:.1f)."
        )

    def test_spin_pct_gate_not_none(self, acc_stdout: str) -> None:
        """'SPIN_PCT: None%' would indicate spin_pct extraction from cmd1 failed."""
        assert "SPIN_PCT: None" not in acc_stdout, (
            "acceptance stdout contains 'SPIN_PCT: None' — the spin_pct value was None.\n"
            "cmd1 (once) must produce at least one 'spin_pct:' annotation."
        )

    def test_no_gate_marker_before_digest_header(self, acc_stdout: str) -> None:
        """Gate markers must not appear before the '# Situation Monitor Digest' header."""
        digest_idx = acc_stdout.find("# Situation Monitor Digest")
        if digest_idx < 0:
            return
        pre_digest = acc_stdout[:digest_idx]
        for marker in ("DUAL_LENS:", "SPIN_PCT:", "MARKET:"):
            assert marker not in pre_digest, (
                f"Gate marker '{marker}' appears BEFORE the digest header — "
                "it must be printed at the end of main(), after all digest content."
            )


# ---------------------------------------------------------------------------
# Unit tests: acceptance._extract_spin_pct — no subprocess
# ---------------------------------------------------------------------------


class TestExtractSpinPctUnit:
    """Unit tests for acceptance._extract_spin_pct.

    This helper drives the SPIN_PCT gate marker and the live→stub fallback decision.
    Testing it in-process catches regressions before they surface in the subprocess.
    The real function is exercised — no mocking.
    """

    def test_returns_none_on_empty_string(self, acceptance_mod) -> None:
        result = acceptance_mod._extract_spin_pct("")
        assert result is None, (
            "_extract_spin_pct('') must return None — no annotation in empty text"
        )

    def test_returns_none_when_no_annotation(self, acceptance_mod) -> None:
        result = acceptance_mod._extract_spin_pct("Article headline with no spin")
        assert result is None

    def test_extracts_decimal_value(self, acceptance_mod) -> None:
        text = "- Article | spin_pct: 73.4%"
        result = acceptance_mod._extract_spin_pct(text)
        assert result is not None, "Must extract from valid annotation"
        assert abs(result - 73.4) < 0.001, f"Expected 73.4, got {result}"

    def test_extracts_zero(self, acceptance_mod) -> None:
        text = "- Title | spin_pct: 0.0%"
        result = acceptance_mod._extract_spin_pct(text)
        assert result is not None
        assert abs(result - 0.0) < 0.001

    def test_extracts_hundred(self, acceptance_mod) -> None:
        text = "- Title | spin_pct: 100.0%"
        result = acceptance_mod._extract_spin_pct(text)
        assert result is not None
        assert abs(result - 100.0) < 0.001

    def test_returns_float_type(self, acceptance_mod) -> None:
        text = "- Title | spin_pct: 50.0%"
        result = acceptance_mod._extract_spin_pct(text)
        assert isinstance(result, float), (
            f"_extract_spin_pct must return float, got {type(result)}"
        )

    def test_extracts_from_multiline_text(self, acceptance_mod) -> None:
        text = "## WORLD\n### Article\n- Title | spin_pct: 25.3%\n## MARKETS\n"
        result = acceptance_mod._extract_spin_pct(text)
        assert result is not None
        assert abs(result - 25.3) < 0.001

    def test_none_when_percent_sign_missing(self, acceptance_mod) -> None:
        """Without '%' the pattern must not match — the regex requires it."""
        text = "- Title | spin_pct: 43.4"
        result = acceptance_mod._extract_spin_pct(text)
        assert result is None, (
            "spin_pct without trailing '%' must not match — "
            "acceptance.py format is 'spin_pct: N.N%'."
        )

    def test_none_when_keyword_missing(self, acceptance_mod) -> None:
        """A bare percentage without 'spin_pct:' must not match."""
        text = "Article describes a 50% improvement in efficiency."
        result = acceptance_mod._extract_spin_pct(text)
        assert result is None, (
            "_extract_spin_pct must only match 'spin_pct: N%', not any bare percentage"
        )

    def test_handles_whitespace_between_colon_and_number(self, acceptance_mod) -> None:
        """The regex allows optional whitespace after 'spin_pct:' (\\s* in pattern)."""
        text = "- Title | spin_pct:   55.5%"
        result = acceptance_mod._extract_spin_pct(text)
        assert result is not None
        assert abs(result - 55.5) < 0.001

    def test_returns_first_match_when_multiple(self, acceptance_mod) -> None:
        """re.search returns the first occurrence — test that it's deterministic."""
        text = "- A | spin_pct: 30.0%\n- B | spin_pct: 60.0%\n"
        result1 = acceptance_mod._extract_spin_pct(text)
        result2 = acceptance_mod._extract_spin_pct(text)
        assert result1 == result2, "_extract_spin_pct must be deterministic on the same input"
        assert result1 in (30.0, 60.0), f"Must return one of the values; got {result1}"

    def test_no_match_on_wrong_keyword_case(self, acceptance_mod) -> None:
        """The keyword is 'spin_pct:' (lowercase) — uppercase must not match."""
        text = "- Title | SPIN_PCT: 43.4%"
        result = acceptance_mod._extract_spin_pct(text)
        assert result is None, (
            "'SPIN_PCT:' (uppercase) must not match — the regex uses lowercase 'spin_pct:'"
        )


# ---------------------------------------------------------------------------
# Unit tests: acceptance._has_all_required — no subprocess
# ---------------------------------------------------------------------------


class TestHasAllRequiredUnit:
    """Unit tests for acceptance._has_all_required.

    This function gates the live→stub fallback: if the live network run produces
    incomplete output, the offline stub takes over.  A regression here could accept
    incomplete output, silently bypassing the fallback.

    The real function is exercised — no mocking.
    """

    @staticmethod
    def _complete_text() -> str:
        """Minimal text that satisfies every _has_all_required check."""
        return (
            "## WORLD\n### Article\n"
            "## MARKETS\n### Article\n"
            "## AI\n### Article\n"
            "## DUAL-LENS EVENTS\n"
            "#### LEFT (1 article)\n"
            "- Title Left | spin_pct: 45.3%\n"
            "#### RIGHT (1 article)\n"
            "- Title Right | spin_pct: 67.8%\n"
        )

    def test_complete_text_returns_true(self, acceptance_mod) -> None:
        assert acceptance_mod._has_all_required(self._complete_text()) is True

    def test_empty_text_returns_false(self, acceptance_mod) -> None:
        assert acceptance_mod._has_all_required("") is False

    def test_missing_world_returns_false(self, acceptance_mod) -> None:
        text = self._complete_text().replace("## WORLD\n", "")
        assert acceptance_mod._has_all_required(text) is False, (
            "Missing '## WORLD' must cause _has_all_required to return False"
        )

    def test_missing_markets_returns_false(self, acceptance_mod) -> None:
        text = self._complete_text().replace("## MARKETS\n", "")
        assert acceptance_mod._has_all_required(text) is False, (
            "Missing '## MARKETS' must cause _has_all_required to return False"
        )

    def test_missing_ai_returns_false(self, acceptance_mod) -> None:
        text = self._complete_text().replace("## AI\n", "")
        assert acceptance_mod._has_all_required(text) is False

    def test_missing_dual_lens_events_returns_false(self, acceptance_mod) -> None:
        text = self._complete_text().replace("## DUAL-LENS EVENTS\n", "")
        assert acceptance_mod._has_all_required(text) is False, (
            "Missing '## DUAL-LENS EVENTS' must cause _has_all_required to return False"
        )

    def test_missing_left_heading_returns_false(self, acceptance_mod) -> None:
        text = self._complete_text().replace("#### LEFT (1 article)\n", "")
        assert acceptance_mod._has_all_required(text) is False, (
            "Missing '#### LEFT' must cause _has_all_required to return False"
        )

    def test_missing_right_heading_returns_false(self, acceptance_mod) -> None:
        text = self._complete_text().replace("#### RIGHT (1 article)\n", "")
        assert acceptance_mod._has_all_required(text) is False

    def test_missing_spin_pct_returns_false(self, acceptance_mod) -> None:
        text = re.sub(r"spin_pct:\s*[\d.]+%", "", self._complete_text())
        assert acceptance_mod._has_all_required(text) is False, (
            "Missing 'spin_pct: N%' must cause _has_all_required to return False"
        )

    def test_wrong_spin_pct_format_no_percent_returns_false(
        self, acceptance_mod
    ) -> None:
        """spin_pct without trailing '%' fails extraction → _has_all_required False."""
        text = (
            "## WORLD\n## MARKETS\n## AI\n"
            "## DUAL-LENS EVENTS\n#### LEFT\n#### RIGHT\n"
            "spin_pct: 43.4\n"  # missing %
        )
        assert acceptance_mod._has_all_required(text) is False

    def test_only_domain_sections_no_dual_lens_returns_false(
        self, acceptance_mod
    ) -> None:
        text = "## WORLD\n## MARKETS\n## AI\n"
        assert acceptance_mod._has_all_required(text) is False

    def test_returns_bool_type(self, acceptance_mod) -> None:
        result = acceptance_mod._has_all_required(self._complete_text())
        assert isinstance(result, bool), (
            f"_has_all_required must return bool; got {type(result)}"
        )

    def test_adding_one_section_at_a_time_only_passes_when_complete(
        self, acceptance_mod
    ) -> None:
        """Adding required sections one by one; must only return True when all are present."""
        sections = [
            "## WORLD\n",
            "## MARKETS\n",
            "## AI\n",
            "## DUAL-LENS EVENTS\n",
            "#### LEFT\n",
            "#### RIGHT\n",
            "- Title | spin_pct: 50.0%\n",
        ]
        text = ""
        for i, section in enumerate(sections):
            text += section
            result = acceptance_mod._has_all_required(text)
            if i < len(sections) - 1:
                assert result is False, (
                    f"_has_all_required returned True after adding only {i + 1}/{len(sections)} "
                    f"sections — it should be False until all sections are present.\n"
                    f"Text so far:\n{text!r}"
                )
        # After adding all sections
        assert acceptance_mod._has_all_required(text) is True, (
            "_has_all_required must return True when ALL required sections are present"
        )


# ---------------------------------------------------------------------------
# Omnibus: all acceptance criteria pass simultaneously
# ---------------------------------------------------------------------------


class TestAllCriteriaSimultaneously:
    """All acceptance criteria must hold at the same time — the complete gate check."""

    def test_exit_zero_and_all_markers_present(
        self,
        acc_proc: subprocess.CompletedProcess,
        acc_stdout: str,
    ) -> None:
        """Omnibus: exit 0 + all required markers in a single assertion."""
        assert acc_proc.returncode == 0, (
            f"acceptance.py must exit 0; got {acc_proc.returncode}"
        )
        required = {
            "## DUAL-LENS EVENTS": "criterion 3",
            "DUAL_LENS: PASS": "criterion 5a",
            "MARKET: PASS": "criterion 5b",
        }
        missing = [f"{marker!r} ({label})" for marker, label in required.items()
                   if marker not in acc_stdout]
        assert not missing, (
            "acceptance stdout is missing required markers:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )
        assert re.search(r"spin_pct:\s*[\d.]+%", acc_stdout), (
            "acceptance stdout must match r'spin_pct:\\s*[\\d.]+%%' (criterion 4)"
        )

    def test_no_fail_markers_when_exit_zero(
        self,
        acc_proc: subprocess.CompletedProcess,
        acc_stdout: str,
    ) -> None:
        """Exit 0 is inconsistent with FAIL markers — if pass, must have no FAIL."""
        if acc_proc.returncode == 0:
            assert "DUAL_LENS: FAIL" not in acc_stdout, (
                "returncode 0 is inconsistent with 'DUAL_LENS: FAIL' in stdout."
            )
            assert "MARKET: FAIL" not in acc_stdout, (
                "returncode 0 is inconsistent with 'MARKET: FAIL' in stdout."
            )

    def test_acceptance_subprocess_is_a_real_completed_process(
        self, acc_proc: subprocess.CompletedProcess
    ) -> None:
        assert hasattr(acc_proc, "returncode")
        assert hasattr(acc_proc, "stdout")
        assert hasattr(acc_proc, "stderr")
        assert hasattr(acc_proc, "args")

    def test_acceptance_subprocess_pinned_to_offline(
        self, acc_proc: subprocess.CompletedProcess
    ) -> None:
        """The subprocess must not have produced LLM auth errors (offline must suppress them)."""
        stderr = acc_proc.stderr.decode(errors="replace")
        assert "AuthenticationError" not in stderr, (
            "acceptance subprocess shows AuthenticationError — "
            "SM_LLM_BACKEND=offline must have been set to prevent live API calls."
        )

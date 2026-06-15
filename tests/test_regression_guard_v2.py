"""Regression guard v2: pytest clean + acceptance structured output verified.

Acceptance criteria under test:
  1. pytest tests/ -x exits returncode 0 — evidenced structurally, NOT by
     recursive subprocess invocation (project memory: recursive pytest hangs
     the suite).  The fact that this file passes is the primary evidence.
  2. SM_LLM_BACKEND=offline python acceptance.py exits returncode 0.
  3. acceptance stdout contains 'DUAL_LENS: PASS' (machine-readable gate marker).
  4. acceptance stdout contains 'SPIN_PCT:' followed by a digit and '%'.
  5. acceptance stdout contains 'MARKET: PASS' (machine-readable gate marker).

Independent tester perspective: the unit under test (acceptance.py) is NEVER
mocked — mocking it proves nothing.  Every assertion targets an observable output
contract and CAN fail on a real regression:
  • returncode != 0 → criterion 2 fails.
  • dual-lens block absent from cmd1 → 'DUAL_LENS: FAIL' → criterion 3 fails.
  • no spin_pct: annotation in cmd1 → acceptance exits early → criterion 2 fails.
  • '## MARKETS' absent from cmd1 → 'MARKET: FAIL' → criterion 5 fails.
"""

from __future__ import annotations

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
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"


def _offline_env(**extra: str) -> dict[str, str]:
    return {**os.environ, "SM_LLM_BACKEND": "offline", **extra}


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixture: acceptance.py with SM_LLM_BACKEND=offline
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_proc() -> subprocess.CompletedProcess:
    """Criterion 2: run acceptance.py with SM_LLM_BACKEND=offline — exactly once."""
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        timeout=300,
    )


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acceptance_stderr(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 1: pytest exits 0 — structural evidence (no recursive subprocess)
# ---------------------------------------------------------------------------


class TestPytestCleanCriterion:
    """Criterion 1: pytest tests/ -x exits returncode 0.

    Running pytest inside a pytest test hangs the suite.  Evidence is provided
    structurally: if this class passes, pytest collected and passed these tests.
    """

    def test_situation_monitor_package_importable(self) -> None:
        """Import failure crashes every acceptance subprocess — guard it first."""
        try:
            import situation_monitor  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"situation_monitor not importable: {exc}")

    def test_acceptance_py_exists(self) -> None:
        assert ACCEPTANCE_PY.exists(), f"acceptance.py missing at {ACCEPTANCE_PY}"

    def test_acceptance_py_is_valid_python_syntax(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c",
             f"import ast; ast.parse(open({str(ACCEPTANCE_PY)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "acceptance.py has a syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_situation_monitor_main_valid_syntax(self) -> None:
        main_path = PROJECT_ROOT / "situation_monitor" / "__main__.py"
        assert main_path.exists(), "situation_monitor/__main__.py missing"
        result = subprocess.run(
            [sys.executable, "-c",
             f"import ast; ast.parse(open({str(main_path)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "situation_monitor/__main__.py has a syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_no_test_file_invokes_pytest_subprocess(self) -> None:
        """Recursive pytest subprocess invocations hang the suite — forbid them."""
        test_dir = PROJECT_ROOT / "tests"
        bad: list[str] = []
        for tf in sorted(test_dir.glob("test_*.py")):
            content = tf.read_text(errors="replace")
            for lineno, raw in enumerate(content.splitlines(), start=1):
                stripped = raw.strip()
                if stripped.startswith("#"):
                    continue
                if (
                    re.search(r'''["']pytest["']''', raw)
                    and re.search(
                        r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b",
                        raw,
                    )
                ):
                    bad.append(f"{tf.name}:{lineno}: {raw.rstrip()}")
        assert not bad, (
            "Recursive pytest subprocess calls found — these hang the suite:\n"
            + "\n".join(bad[:10])
        )

    def test_test_corpus_is_non_trivial(self) -> None:
        """A near-empty suite exits 0 vacuously — the suite must be substantive."""
        test_files = list((PROJECT_ROOT / "tests").glob("test_*.py"))
        assert len(test_files) >= 10, (
            f"Expected ≥10 test_*.py files; found {len(test_files)}. "
            "An almost-empty suite would exit 0 without verifying anything."
        )

    def test_once_subcommand_registered_in_main(self) -> None:
        content = (PROJECT_ROOT / "situation_monitor" / "__main__.py").read_text()
        assert '"once"' in content or "'once'" in content, (
            "situation_monitor/__main__.py must register the 'once' subcommand"
        )

    def test_digest_dry_run_subcommand_registered_in_main(self) -> None:
        content = (PROJECT_ROOT / "situation_monitor" / "__main__.py").read_text()
        assert "digest-dry-run" in content, (
            "situation_monitor/__main__.py must register the 'digest-dry-run' subcommand"
        )

    def test_all_required_fixture_files_present(self) -> None:
        required = [
            FIXTURES / "rss_sample.xml",
            FIXTURES / "rss_left.xml",
            FIXTURES / "rss_right.xml",
            FIXTURES / "rss_markets.xml",
            FIXTURES / "rss_ai.xml",
            FIXTURES / "rss_carrier.xml",
            FIXTURES / "acceptance_source_defs.json",
            CHECK_SERVER,
        ]
        missing = [str(p) for p in required if not p.exists()]
        assert not missing, (
            "Required fixture/script files absent — multiple tests would fail:\n"
            + "\n".join(missing)
        )


# ---------------------------------------------------------------------------
# Criterion 2: SM_LLM_BACKEND=offline python acceptance.py exits returncode 0
# ---------------------------------------------------------------------------


class TestAcceptanceExitsZero:
    """Criterion 2: acceptance.py must exit 0 with SM_LLM_BACKEND=offline."""

    def test_returncode_is_zero(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        assert acceptance_proc.returncode == 0, (
            f"acceptance.py exited {acceptance_proc.returncode}; expected 0.\n"
            f"stderr (last 1000):\n"
            f"{acceptance_proc.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout (last 500):\n"
            f"{acceptance_proc.stdout.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, acceptance_stdout: str) -> None:
        assert acceptance_stdout.strip(), (
            "acceptance.py produced empty stdout; the 'once' digest must be emitted."
        )

    def test_no_python_traceback_in_stdout(self, acceptance_stdout: str) -> None:
        assert "Traceback" not in acceptance_stdout, (
            "acceptance.py stdout must not contain a Python Traceback.\n"
            f"stdout (first 2000):\n{acceptance_stdout[:2000]}"
        )

    def test_no_python_traceback_in_stderr(self, acceptance_stderr: str) -> None:
        assert "Traceback" not in acceptance_stderr, (
            "acceptance.py stderr must not contain a Python Traceback.\n"
            f"stderr:\n{acceptance_stderr[:2000]}"
        )

    def test_no_live_api_error_in_stderr(self, acceptance_stderr: str) -> None:
        """With SM_LLM_BACKEND=offline, no LLM API error must appear in stderr."""
        bad_indicators = ["AuthenticationError", "ANTHROPIC_API_KEY", "RateLimitError"]
        for indicator in bad_indicators:
            assert indicator not in acceptance_stderr, (
                f"acceptance stderr contains API error {indicator!r} — "
                "SM_LLM_BACKEND=offline must prevent live LLM calls."
            )

    def test_acceptance_uses_sys_executable_internally(self) -> None:
        """acceptance.py must use sys.executable — bare 'python' fails on macOS."""
        content = ACCEPTANCE_PY.read_text()
        assert "sys.executable" in content, (
            "acceptance.py must use sys.executable, not 'python' or 'python3'."
        )


# ---------------------------------------------------------------------------
# Criterion 3: 'DUAL_LENS: PASS' in acceptance stdout
# ---------------------------------------------------------------------------


class TestDualLensPassMarker:
    """Criterion 3: acceptance stdout must contain 'DUAL_LENS: PASS'."""

    def test_dual_lens_pass_present(self, acceptance_stdout: str) -> None:
        assert "DUAL_LENS: PASS" in acceptance_stdout, (
            "acceptance stdout must contain 'DUAL_LENS: PASS' gate marker.\n"
            "This marker is printed only when '## DUAL-LENS EVENTS' appears in cmd1 output.\n"
            f"stdout (last 500):\n{acceptance_stdout[-500:]}"
        )

    def test_dual_lens_not_fail(self, acceptance_stdout: str) -> None:
        """'DUAL_LENS: FAIL' must NOT appear — FAIL would mean the dual-lens block is absent."""
        assert "DUAL_LENS: FAIL" not in acceptance_stdout, (
            "acceptance stdout contains 'DUAL_LENS: FAIL' — dual-lens block is absent "
            "from cmd1 output.  The fixture feeds must produce at least one dual-lens event."
        )

    def test_dual_lens_marker_on_its_own_line(self, acceptance_stdout: str) -> None:
        """'DUAL_LENS: PASS' must appear as a complete standalone line."""
        lines = acceptance_stdout.splitlines()
        assert any(line.strip() == "DUAL_LENS: PASS" for line in lines), (
            "'DUAL_LENS: PASS' must appear as a complete line, not embedded in prose.\n"
            f"Lines containing DUAL_LENS: "
            f"{[l for l in lines if 'DUAL_LENS' in l]}"
        )

    def test_dual_lens_marker_appears_after_digest_content(
        self, acceptance_stdout: str
    ) -> None:
        """The gate marker must appear AFTER the digest content (printed last in main())."""
        dual_lens_events_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        gate_marker_idx = acceptance_stdout.find("DUAL_LENS: PASS")
        if dual_lens_events_idx >= 0 and gate_marker_idx >= 0:
            assert dual_lens_events_idx < gate_marker_idx, (
                "'DUAL_LENS: PASS' gate marker must appear AFTER '## DUAL-LENS EVENTS' "
                "content — the gate markers are printed at the very end of main()."
            )

    def test_dual_lens_marker_format_exactly_colon_space_pass(
        self, acceptance_stdout: str
    ) -> None:
        """The format must be exactly 'DUAL_LENS: PASS' — colon, space, then PASS."""
        pattern = re.compile(r"^DUAL_LENS: PASS$", re.MULTILINE)
        assert pattern.search(acceptance_stdout), (
            "No line matching exactly '^DUAL_LENS: PASS$' found.\n"
            "Format must be 'DUAL_LENS: PASS' (colon-space-PASS), not 'DUAL_LENS:PASS' "
            "or 'DUAL_LENS : PASS'.\n"
            f"stdout (last 300):\n{acceptance_stdout[-300:]}"
        )


# ---------------------------------------------------------------------------
# Criterion 4: 'SPIN_PCT:' followed by a digit and '%' in acceptance stdout
# ---------------------------------------------------------------------------


class TestSpinPctMarker:
    """Criterion 4: acceptance stdout must contain 'SPIN_PCT:' + digit + '%'."""

    def test_spin_pct_keyword_present(self, acceptance_stdout: str) -> None:
        assert "SPIN_PCT:" in acceptance_stdout, (
            "acceptance stdout must contain 'SPIN_PCT:' gate marker.\n"
            f"stdout (last 500):\n{acceptance_stdout[-500:]}"
        )

    def test_spin_pct_followed_by_digit_and_percent(self, acceptance_stdout: str) -> None:
        """The acceptance criterion: 'SPIN_PCT:' followed by a digit and '%'."""
        match = re.search(r"SPIN_PCT:\s*(\d[\d.]*)%", acceptance_stdout)
        assert match is not None, (
            "No 'SPIN_PCT: <digit>%' pattern found in acceptance stdout.\n"
            "acceptance.py prints: print(f'SPIN_PCT: {spin_pct:.1f}%')\n"
            "This requires cmd1 to contain at least one 'spin_pct:' annotation.\n"
            f"stdout (last 500):\n{acceptance_stdout[-500:]}"
        )

    def test_spin_pct_value_is_parseable_float(self, acceptance_stdout: str) -> None:
        """The numeric value after 'SPIN_PCT:' must be a parseable float."""
        match = re.search(r"SPIN_PCT:\s*([\d.]+)%", acceptance_stdout)
        assert match is not None, "No 'SPIN_PCT: N.N%' found in acceptance stdout"
        try:
            val = float(match.group(1))
        except ValueError:
            pytest.fail(
                f"SPIN_PCT value {match.group(1)!r} is not a parseable float"
            )
        assert 0.0 <= val <= 100.0, (
            f"SPIN_PCT value {val}% is outside the valid [0, 100] range.\n"
            "The spin estimator output is clamped to this range."
        )

    def test_spin_pct_uses_decimal_format(self, acceptance_stdout: str) -> None:
        """acceptance.py uses ':.1f' format — value must contain a decimal point."""
        match = re.search(r"SPIN_PCT:\s*([\d.]+)%", acceptance_stdout)
        assert match is not None, "No 'SPIN_PCT: N.N%' found in acceptance stdout"
        raw = match.group(1)
        assert "." in raw, (
            f"SPIN_PCT value {raw!r} missing decimal point.\n"
            "Format is ':.1f' (e.g. '43.4%'), not integer percent (e.g. '43%')."
        )

    def test_spin_pct_marker_on_its_own_line(self, acceptance_stdout: str) -> None:
        """The SPIN_PCT gate marker must appear on a complete line."""
        lines = acceptance_stdout.splitlines()
        spin_lines = [l for l in lines if l.startswith("SPIN_PCT:")]
        assert spin_lines, (
            "No line STARTING WITH 'SPIN_PCT:' found in acceptance stdout.\n"
            f"Lines containing SPIN_PCT: {[l for l in lines if 'SPIN_PCT' in l]}"
        )

    def test_spin_pct_not_none_literal(self, acceptance_stdout: str) -> None:
        """'SPIN_PCT: None%' would indicate the spin estimator found no spin_pct annotation."""
        assert "SPIN_PCT: None" not in acceptance_stdout, (
            "acceptance stdout contains 'SPIN_PCT: None' — the spin_pct value was not found.\n"
            "cmd1 (once) must produce at least one 'spin_pct:' annotation in its output."
        )

    def test_spin_pct_appears_after_web_server_smoke(
        self, acceptance_stdout: str
    ) -> None:
        """Gate markers are printed in main() AFTER cmd4 (check_server.py), which prints
        'web-server-smoke: PASS'.  SPIN_PCT: must therefore follow it."""
        web_idx = acceptance_stdout.find("web-server-smoke: PASS")
        spin_idx = acceptance_stdout.find("SPIN_PCT:")
        if web_idx >= 0 and spin_idx >= 0:
            assert web_idx < spin_idx, (
                "'SPIN_PCT:' must appear AFTER 'web-server-smoke: PASS'.\n"
                "acceptance.py prints the gate markers at the very end of main(), "
                "after check_server.py (cmd4) completes."
            )


# ---------------------------------------------------------------------------
# Criterion 5: 'MARKET: PASS' in acceptance stdout
# ---------------------------------------------------------------------------


class TestMarketPassMarker:
    """Criterion 5: acceptance stdout must contain 'MARKET: PASS'."""

    def test_market_pass_present(self, acceptance_stdout: str) -> None:
        assert "MARKET: PASS" in acceptance_stdout, (
            "acceptance stdout must contain 'MARKET: PASS' gate marker.\n"
            "This marker is printed only when '## MARKETS' appears in cmd1 output.\n"
            f"stdout (last 500):\n{acceptance_stdout[-500:]}"
        )

    def test_market_not_fail(self, acceptance_stdout: str) -> None:
        """'MARKET: FAIL' must NOT appear — FAIL would mean MARKETS section is absent."""
        assert "MARKET: FAIL" not in acceptance_stdout, (
            "acceptance stdout contains 'MARKET: FAIL' — '## MARKETS' is absent "
            "from cmd1 output.  The markets fixture (rss_markets.xml) must be loaded."
        )

    def test_market_marker_on_its_own_line(self, acceptance_stdout: str) -> None:
        """'MARKET: PASS' must appear as a complete standalone line."""
        lines = acceptance_stdout.splitlines()
        assert any(line.strip() == "MARKET: PASS" for line in lines), (
            "'MARKET: PASS' must appear as a complete line, not embedded in prose.\n"
            f"Lines containing MARKET: "
            f"{[l for l in lines if 'MARKET' in l and 'PASS' in l]}"
        )

    def test_market_marker_format_exactly_colon_space_pass(
        self, acceptance_stdout: str
    ) -> None:
        """The format must be exactly 'MARKET: PASS' — colon, space, PASS."""
        pattern = re.compile(r"^MARKET: PASS$", re.MULTILINE)
        assert pattern.search(acceptance_stdout), (
            "No line matching '^MARKET: PASS$' found.\n"
            "Format must be 'MARKET: PASS', not 'MARKET:PASS' or 'MARKETS: PASS'.\n"
            f"stdout (last 300):\n{acceptance_stdout[-300:]}"
        )

    def test_market_marker_appears_after_dual_lens_marker(
        self, acceptance_stdout: str
    ) -> None:
        """Gate markers are printed in order: DUAL_LENS then SPIN_PCT then MARKET."""
        dual_idx = acceptance_stdout.find("DUAL_LENS:")
        market_idx = acceptance_stdout.find("MARKET: PASS")
        if dual_idx >= 0 and market_idx >= 0:
            assert dual_idx < market_idx, (
                "'MARKET: PASS' must appear AFTER 'DUAL_LENS:' in acceptance stdout.\n"
                "acceptance.py prints: DUAL_LENS, SPIN_PCT, MARKET — in that order."
            )


# ---------------------------------------------------------------------------
# All three gate markers present simultaneously
# ---------------------------------------------------------------------------


class TestAllGateMarkersSimultaneously:
    """All three gate markers must be present at the same time — omnibus check."""

    def test_all_three_gate_markers_present(self, acceptance_stdout: str) -> None:
        missing = []
        if "DUAL_LENS: PASS" not in acceptance_stdout:
            missing.append("DUAL_LENS: PASS")
        if not re.search(r"SPIN_PCT:\s*\d[\d.]*%", acceptance_stdout):
            missing.append("SPIN_PCT: <digit>%")
        if "MARKET: PASS" not in acceptance_stdout:
            missing.append("MARKET: PASS")
        assert not missing, (
            f"acceptance stdout is missing these required gate markers: {missing}\n"
            "All three must be present for the acceptance gate to pass.\n"
            f"stdout (last 500):\n{acceptance_stdout[-500:]}"
        )

    def test_gate_markers_appear_at_end_of_output(self, acceptance_stdout: str) -> None:
        """The gate markers must be in the last 200 characters of stdout — printed last."""
        tail = acceptance_stdout[-200:]
        markers_in_tail = sum([
            "DUAL_LENS:" in tail,
            "SPIN_PCT:" in tail,
            "MARKET:" in tail,
        ])
        assert markers_in_tail >= 2, (
            "At least 2 of the 3 gate markers must appear in the last 200 characters "
            "of acceptance stdout (they are printed at the very end of main()).\n"
            f"Last 200 chars:\n{tail!r}"
        )

    def test_no_gate_marker_appears_before_digest_header(
        self, acceptance_stdout: str
    ) -> None:
        """Gate markers come after the digest — they must not appear before '# Situation Monitor'."""
        digest_idx = acceptance_stdout.find("# Situation Monitor Digest")
        if digest_idx < 0:
            return
        pre_digest = acceptance_stdout[:digest_idx]
        for marker in ("DUAL_LENS:", "SPIN_PCT:", "MARKET:"):
            assert marker not in pre_digest, (
                f"Gate marker '{marker}' appears BEFORE the digest header — "
                "it must be printed at the end of main(), after all digest content."
            )

    def test_dual_lens_spin_pct_market_appear_in_order(
        self, acceptance_stdout: str
    ) -> None:
        """Gate markers must appear in the order printed by acceptance.py: DL → SP → MK."""
        dl_idx = acceptance_stdout.rfind("DUAL_LENS:")
        sp_idx = acceptance_stdout.rfind("SPIN_PCT:")
        mk_idx = acceptance_stdout.rfind("MARKET:")
        if dl_idx >= 0 and sp_idx >= 0 and mk_idx >= 0:
            assert dl_idx < sp_idx < mk_idx, (
                "Gate markers must appear in order: DUAL_LENS → SPIN_PCT → MARKET.\n"
                f"Found at positions: DUAL_LENS={dl_idx}, SPIN_PCT={sp_idx}, MARKET={mk_idx}"
            )

    def test_returncode_zero_implies_no_fail_markers(
        self,
        acceptance_proc: subprocess.CompletedProcess,
        acceptance_stdout: str,
    ) -> None:
        """If exit 0, neither DUAL_LENS: FAIL nor MARKET: FAIL must appear."""
        if acceptance_proc.returncode == 0:
            assert "DUAL_LENS: FAIL" not in acceptance_stdout, (
                "returncode 0 is inconsistent with 'DUAL_LENS: FAIL' appearing in stdout.\n"
                "acceptance.py exits 1 when any gate marker is FAIL."
            )
            assert "MARKET: FAIL" not in acceptance_stdout, (
                "returncode 0 is inconsistent with 'MARKET: FAIL' appearing in stdout.\n"
                "acceptance.py exits 1 when any gate marker is FAIL."
            )


# ---------------------------------------------------------------------------
# Structural checks: acceptance.py prints the correct gate markers
# ---------------------------------------------------------------------------


class TestAcceptancePyGateMarkerStructure:
    """acceptance.py source must contain the code that produces the required gate markers."""

    def test_acceptance_py_prints_dual_lens_pass(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "DUAL_LENS:" in content, (
            "acceptance.py must contain 'DUAL_LENS:' print statement for the gate marker"
        )
        assert "PASS" in content, (
            "acceptance.py must contain 'PASS' in its gate marker print statements"
        )

    def test_acceptance_py_prints_spin_pct_marker(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "SPIN_PCT:" in content, (
            "acceptance.py must contain 'SPIN_PCT:' in its gate marker print statement"
        )

    def test_acceptance_py_prints_market_pass(self) -> None:
        content = ACCEPTANCE_PY.read_text()
        assert "MARKET:" in content, (
            "acceptance.py must contain 'MARKET:' in its gate marker print statement"
        )

    def test_acceptance_py_gate_markers_are_last_prints(self) -> None:
        """The gate marker prints must appear AFTER the check_server.py block."""
        content = ACCEPTANCE_PY.read_text()
        check_server_idx = content.find("check_server.py")
        dual_lens_print_idx = content.find('print(f"DUAL_LENS:')
        if check_server_idx >= 0 and dual_lens_print_idx >= 0:
            assert check_server_idx < dual_lens_print_idx, (
                "acceptance.py must print gate markers AFTER the check_server.py cmd4 block"
            )

    def test_acceptance_py_uses_pass_fail_strings(self) -> None:
        """The gate markers must use 'PASS'/'FAIL' not 'True'/'False' or 'Y'/'N'."""
        content = ACCEPTANCE_PY.read_text()
        assert "PASS" in content, "acceptance.py gate markers must use 'PASS' string"
        assert "FAIL" in content, "acceptance.py gate markers must use 'FAIL' string"

    def test_acceptance_py_extracts_spin_pct_from_cmd1(self) -> None:
        """acceptance.py must have a spin_pct extraction function for cmd1 output."""
        content = ACCEPTANCE_PY.read_text()
        assert "_extract_spin_pct" in content or "spin_pct" in content, (
            "acceptance.py must extract spin_pct from cmd1 output before printing the gate marker"
        )

    def test_acceptance_py_exits_nonzero_on_fail_markers(self) -> None:
        """When any gate check fails, acceptance.py must exit with a non-zero code."""
        content = ACCEPTANCE_PY.read_text()
        assert "sys.exit(1)" in content or "sys.exit(rc)" in content, (
            "acceptance.py must call sys.exit(1) when a gate check fails"
        )


# ---------------------------------------------------------------------------
# Additional content checks — acceptance stdout completeness
# ---------------------------------------------------------------------------


class TestAcceptanceOutputCompleteness:
    """acceptance stdout must contain the full pipeline output, not just gate markers."""

    def test_contains_digest_header(self, acceptance_stdout: str) -> None:
        assert "Situation Monitor" in acceptance_stdout, (
            "acceptance stdout must contain a 'Situation Monitor' heading from cmd1"
        )

    def test_contains_dual_lens_events_section(self, acceptance_stdout: str) -> None:
        assert "DUAL-LENS EVENTS" in acceptance_stdout, (
            "acceptance stdout must contain '## DUAL-LENS EVENTS' from cmd1 (once).\n"
            "This is the content section that triggers DUAL_LENS: PASS."
        )

    def test_contains_markets_section(self, acceptance_stdout: str) -> None:
        assert "## MARKETS" in acceptance_stdout, (
            "acceptance stdout must contain '## MARKETS' from cmd1 (once).\n"
            "This is the content section that triggers MARKET: PASS."
        )

    def test_contains_spin_pct_annotation_from_cmd1(self, acceptance_stdout: str) -> None:
        """The spin_pct: annotation from cmd1 feeds into the SPIN_PCT: gate marker."""
        assert "spin_pct:" in acceptance_stdout, (
            "acceptance stdout must contain 'spin_pct:' per-article annotation from cmd1.\n"
            "The SPIN_PCT: gate marker is derived from this annotation."
        )

    def test_contains_web_server_smoke_pass(self, acceptance_stdout: str) -> None:
        """cmd4 (check_server.py) must complete and emit its pass marker."""
        assert "web-server-smoke: PASS" in acceptance_stdout, (
            "acceptance stdout must contain 'web-server-smoke: PASS' from cmd4 (check_server.py).\n"
            "The gate markers are only printed AFTER cmd4 succeeds."
        )

    def test_contains_telegram_digest_from_cmd2(self, acceptance_stdout: str) -> None:
        """cmd2 (digest-dry-run) must emit its Telegram-format header."""
        assert "*Situation Monitor*" in acceptance_stdout, (
            "acceptance stdout must contain '*Situation Monitor*' from cmd2 (digest-dry-run).\n"
            "The Telegram-format digest runs independently as cmd2."
        )

    def test_contains_discourse_carrier_line_from_cmd3(self, acceptance_stdout: str) -> None:
        """cmd3 (carrier once) must emit a 'discourse-carrier' line."""
        carrier_lines = [
            line for line in acceptance_stdout.splitlines()
            if line.startswith("discourse-carrier")
        ]
        assert carrier_lines, (
            "acceptance stdout must contain a line starting with 'discourse-carrier' from cmd3.\n"
            "cmd3 runs 'once' with SM_CARRIER_FEEDS set to rss_carrier.xml."
        )

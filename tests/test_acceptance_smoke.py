"""Acceptance smoke guard: 'python3 acceptance.py' exits 0 with all four required markers.

Acceptance criteria (verbatim):
  1. tests/test_acceptance_smoke.py runs 'python3 acceptance.py' as subprocess
     from the project root with SM_LLM_BACKEND=offline
  2. asserts returncode == 0
  3. asserts '## DUAL-LENS EVENTS' in combined stdout
  4. asserts 'spin_pct:' in combined stdout
  5. asserts 'web-server-smoke: PASS' in combined stdout

"combined stdout" means stdout+stderr merged so that markers emitted by child
processes (which inherit acceptance.py's file descriptors) are captured even if
a sub-step writes to stderr.

Independent-tester constraints:
  - NEVER mock acceptance.py or its dependencies — mocking proves nothing.
  - No recursive pytest subprocess invocations (they hang the suite).
  - sys.executable is used only for the structural self-check of acceptance.py;
    the subprocess under test is launched via the literal 'python3' per the spec.
  - SM_LLM_BACKEND=offline is set explicitly for every subprocess spawned here.
"""
from __future__ import annotations

import os
import re
import shutil
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


# ---------------------------------------------------------------------------
# Module-scoped subprocess: 'python3 acceptance.py', SM_LLM_BACKEND=offline
# stderr=STDOUT so child subprocess output is included in the combined capture.
# ---------------------------------------------------------------------------


def _offline_env() -> dict[str, str]:
    return {**os.environ, "SM_LLM_BACKEND": "offline"}


@pytest.fixture(scope="module")
def smoke_proc() -> subprocess.CompletedProcess:
    """Run 'python3 acceptance.py' with SM_LLM_BACKEND=offline, stderr merged into stdout."""
    return subprocess.run(
        ["python3", str(ACCEPTANCE_PY)],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,  # combined stdout
        env=_offline_env(),
        cwd=str(PROJECT_ROOT),
        timeout=300,
    )


@pytest.fixture(scope="module")
def combined_stdout(smoke_proc: subprocess.CompletedProcess) -> str:
    """Combined stdout (stdout+stderr merged) decoded as text."""
    return smoke_proc.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# Prerequisites: python3 and acceptance.py must be findable
# ---------------------------------------------------------------------------


class TestPrerequisites:
    """Gates that must hold before the subprocess test can mean anything."""

    def test_python3_is_on_path(self) -> None:
        """'python3' must exist on PATH — the subprocess command would FileNotFoundError without it."""
        assert shutil.which("python3") is not None, (
            "'python3' not found on PATH.\n"
            "The acceptance smoke criterion runs 'python3 acceptance.py' literally; "
            "python3 must be available."
        )

    def test_acceptance_py_exists_at_project_root(self) -> None:
        """acceptance.py must exist at the project root — its absence makes the criterion impossible."""
        assert ACCEPTANCE_PY.exists(), (
            f"acceptance.py not found at {ACCEPTANCE_PY}.\n"
            "The smoke guard runs 'python3 acceptance.py'; the file must be present."
        )

    def test_acceptance_py_is_a_file_not_a_directory(self) -> None:
        assert ACCEPTANCE_PY.is_file(), (
            f"{ACCEPTANCE_PY} exists but is not a regular file."
        )

    def test_acceptance_py_is_non_empty(self) -> None:
        content = ACCEPTANCE_PY.read_text(errors="replace").strip()
        assert content, "acceptance.py is empty — it must contain a runnable Python script."

    def test_acceptance_py_has_valid_python_syntax(self) -> None:
        """A syntax error crashes every smoke run before any output is produced."""
        result = subprocess.run(
            [sys.executable, "-m", "py_compile", str(ACCEPTANCE_PY)],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "acceptance.py has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_sm_llm_backend_is_propagated_to_env(self) -> None:
        """SM_LLM_BACKEND=offline must be in the env passed to the smoke subprocess.

        Verify that _offline_env() produces the key; if this key is absent the
        live LLM backend activates and acceptance.py will fail with an API error.
        """
        env = _offline_env()
        assert "SM_LLM_BACKEND" in env, "_offline_env() must set SM_LLM_BACKEND"
        assert env["SM_LLM_BACKEND"] == "offline", (
            f"SM_LLM_BACKEND must be 'offline'; got {env['SM_LLM_BACKEND']!r}"
        )

    def test_fixture_source_defs_present(self) -> None:
        """acceptance_source_defs.json drives the domain fixture feeds — missing = crash at startup."""
        src = FIXTURES / "acceptance_source_defs.json"
        assert src.exists(), (
            f"acceptance_source_defs.json not found at {src}.\n"
            "acceptance.py uses this to configure domain-specific RSS fixtures."
        )

    def test_check_server_py_exists(self) -> None:
        """check_server.py (cmd4 in acceptance.py) must exist — its absence causes a non-zero exit."""
        check_server = PROJECT_ROOT / "check_server.py"
        assert check_server.exists(), (
            f"check_server.py not found at {check_server}.\n"
            "acceptance.py's cmd4 runs check_server.py; missing = exit 1."
        )

    def test_rss_sample_fixture_present(self) -> None:
        """rss_sample.xml is the primary offline fixture — missing = all ingestion fails."""
        rss_sample = FIXTURES / "rss_sample.xml"
        assert rss_sample.exists(), (
            f"rss_sample.xml not found at {rss_sample}.\n"
            "acceptance.py sets SM_SOURCES to this file; missing = empty digest."
        )

    def test_rss_carrier_fixture_present(self) -> None:
        """rss_carrier.xml is needed for cmd3 (carrier once) inside acceptance.py."""
        rss_carrier = FIXTURES / "rss_carrier.xml"
        assert rss_carrier.exists(), (
            f"rss_carrier.xml not found at {rss_carrier}.\n"
            "acceptance.py's cmd3 uses this fixture for the carrier once subcommand."
        )


# ---------------------------------------------------------------------------
# Criterion 2: returncode == 0
# ---------------------------------------------------------------------------


class TestReturncodeZero:
    """Criterion 2: 'python3 acceptance.py' with SM_LLM_BACKEND=offline exits 0."""

    def test_returncode_is_zero(self, smoke_proc: subprocess.CompletedProcess) -> None:
        """Primary criterion 2: exit code must be exactly 0."""
        stdout_tail = (smoke_proc.stdout or b"").decode(errors="replace")[-1000:]
        assert smoke_proc.returncode == 0, (
            f"'python3 acceptance.py' exited {smoke_proc.returncode} (expected 0).\n"
            f"Combined output (last 1000 chars):\n{stdout_tail}"
        )

    def test_returncode_is_not_negative(
        self, smoke_proc: subprocess.CompletedProcess
    ) -> None:
        """A negative returncode indicates a signal (crash); guard against it explicitly."""
        assert smoke_proc.returncode >= 0, (
            f"acceptance.py was killed by a signal (returncode={smoke_proc.returncode}).\n"
            "Negative return codes indicate SIGSEGV, SIGKILL, etc."
        )

    def test_combined_output_is_non_empty(self, combined_stdout: str) -> None:
        """A zero-exit with empty output indicates the script short-circuited all output."""
        assert combined_stdout.strip(), (
            "'python3 acceptance.py' produced no output.\n"
            "The script must emit a full digest before exiting 0."
        )

    def test_no_python_traceback_in_combined_output(self, combined_stdout: str) -> None:
        """A Traceback in captured output means an unhandled exception — even if exit was 0."""
        assert "Traceback (most recent call last)" not in combined_stdout, (
            "Combined output contains a Python Traceback — a subprocess crashed "
            "but the parent may have swallowed the exit code.\n"
            f"Output (first 2000):\n{combined_stdout[:2000]}"
        )

    def test_no_live_api_errors_in_combined_output(self, combined_stdout: str) -> None:
        """SM_LLM_BACKEND=offline must suppress all live LLM calls; API errors are failures."""
        live_api_indicators = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "RateLimitError",
            "APIConnectionError",
            "openai.error",
        ]
        for indicator in live_api_indicators:
            assert indicator not in combined_stdout, (
                f"Combined output contains {indicator!r} — the offline backend "
                "must prevent all live LLM API calls.\n"
                f"Output (first 1000):\n{combined_stdout[:1000]}"
            )

    def test_no_modulenotfounderror_in_combined_output(self, combined_stdout: str) -> None:
        """A ModuleNotFoundError means a missing dependency — the offline run must be self-contained."""
        assert "ModuleNotFoundError" not in combined_stdout, (
            "Combined output contains 'ModuleNotFoundError'.\n"
            "All required dependencies must be installed for the smoke run to succeed.\n"
            f"Output (first 1000):\n{combined_stdout[:1000]}"
        )

    def test_subprocess_was_launched_from_project_root(self) -> None:
        """The subprocess must run with cwd=project_root — acceptance.py builds paths from __file__."""
        assert (PROJECT_ROOT / "acceptance.py").exists(), (
            "acceptance.py must be at the project root which is used as cwd."
        )

    def test_acceptance_py_does_not_invoke_pytest(self) -> None:
        """acceptance.py must not run pytest — recursive invocation hangs the suite."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "pytest" not in content, (
            "acceptance.py must not invoke pytest — recursive invocation hangs the suite."
        )


# ---------------------------------------------------------------------------
# Criterion 3: '## DUAL-LENS EVENTS' in combined stdout
# ---------------------------------------------------------------------------


class TestDualLensEventsMarker:
    """Criterion 3: '## DUAL-LENS EVENTS' must appear in the combined output."""

    def test_dual_lens_events_marker_present(self, combined_stdout: str) -> None:
        """Primary criterion 3: '## DUAL-LENS EVENTS' must be in the combined output."""
        assert "## DUAL-LENS EVENTS" in combined_stdout, (
            "'## DUAL-LENS EVENTS' not found in combined output of 'python3 acceptance.py'.\n"
            "The dual-lens section must be rendered as an H2 header.\n"
            f"Output (last 2000):\n{combined_stdout[-2000:]}"
        )

    def test_dual_lens_events_is_h2_not_prose(self, combined_stdout: str) -> None:
        """The marker must appear as '## DUAL-LENS EVENTS' at line start, not embedded in text."""
        assert re.search(r"^## DUAL-LENS EVENTS", combined_stdout, re.MULTILINE), (
            "No '^## DUAL-LENS EVENTS' line-start H2 heading found.\n"
            "The string embedded in prose (e.g. inside an article title) does not satisfy criterion 3."
        )

    def test_dual_lens_events_is_not_h3_or_deeper(self, combined_stdout: str) -> None:
        """The dual-lens header must be exactly H2 (two hashes), not H3+ (three or more)."""
        assert not re.search(r"^#{3,} DUAL-LENS EVENTS", combined_stdout, re.MULTILINE), (
            "Found '### DUAL-LENS EVENTS' (H3+) — criterion 3 requires exactly '## DUAL-LENS EVENTS' (H2)."
        )

    def test_dual_lens_events_appears_after_domain_sections(
        self, combined_stdout: str
    ) -> None:
        """'## DUAL-LENS EVENTS' must follow the domain digest sections (WORLD/MARKETS/AI)."""
        dual_idx = combined_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found — see previous test"
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            d_idx = combined_stdout.find(domain)
            if d_idx >= 0:
                assert d_idx < dual_idx, (
                    f"'{domain}' (at {d_idx}) must appear BEFORE '## DUAL-LENS EVENTS' "
                    f"(at {dual_idx}) in the output."
                )

    def test_dual_lens_events_section_is_not_empty(self, combined_stdout: str) -> None:
        """The section must have content below the header — a bare header is not a valid digest."""
        dual_idx = combined_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        section = combined_stdout[dual_idx + len("## DUAL-LENS EVENTS"):]
        non_blank = section.strip()
        assert non_blank, (
            "'## DUAL-LENS EVENTS' header found but no content follows it.\n"
            "The section must contain at least one dual-lens event."
        )

    def test_dual_lens_events_marker_appears_exactly_once(
        self, combined_stdout: str
    ) -> None:
        """The section header must appear once — duplication indicates a renderer loop bug."""
        count = combined_stdout.count("## DUAL-LENS EVENTS")
        assert count == 1, (
            f"'## DUAL-LENS EVENTS' appears {count} times in combined output; expected exactly 1.\n"
            "Multiple occurrences indicate a renderer loop or digest-duplication bug."
        )

    def test_left_right_headings_present_under_dual_lens_block(
        self, combined_stdout: str
    ) -> None:
        """LEFT and RIGHT H4 headings must appear inside the DUAL-LENS EVENTS section."""
        dual_idx = combined_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        block = combined_stdout[dual_idx:]
        assert "#### LEFT" in block, (
            "'#### LEFT' not found inside the '## DUAL-LENS EVENTS' block.\n"
            f"Block (first 500):\n{block[:500]}"
        )
        assert "#### RIGHT" in block, (
            "'#### RIGHT' not found inside the '## DUAL-LENS EVENTS' block.\n"
            f"Block (first 500):\n{block[:500]}"
        )


# ---------------------------------------------------------------------------
# Criterion 4: 'spin_pct:' in combined stdout
# ---------------------------------------------------------------------------


class TestSpinPctMarker:
    """Criterion 4: 'spin_pct:' must appear in the combined output."""

    def test_spin_pct_marker_present(self, combined_stdout: str) -> None:
        """Primary criterion 4: 'spin_pct:' must be in the combined output."""
        assert "spin_pct:" in combined_stdout, (
            "'spin_pct:' not found in combined output of 'python3 acceptance.py'.\n"
            "The dual-lens renderer annotates each article bullet with its spin percentage.\n"
            f"Output (last 2000):\n{combined_stdout[-2000:]}"
        )

    def test_spin_pct_followed_by_numeric_value(self, combined_stdout: str) -> None:
        """'spin_pct:' must be followed by a number — a bare keyword with no value is a format error."""
        assert re.search(r"spin_pct:\s*\d+", combined_stdout), (
            "Found 'spin_pct:' in combined output but not followed by a numeric value.\n"
            "Expected format: 'spin_pct: N.N%'.\n"
            "Lines containing 'spin_pct:':\n"
            + "\n".join(
                ln for ln in combined_stdout.splitlines() if "spin_pct:" in ln
            )[:500]
        )

    def test_spin_pct_includes_percentage_sign(self, combined_stdout: str) -> None:
        """'spin_pct:' must be followed by a value ending with '%'."""
        assert re.search(r"spin_pct:\s*\d+\.?\d*%", combined_stdout), (
            "No 'spin_pct: N%' or 'spin_pct: N.N%' pattern found in combined output.\n"
            "The '%' suffix is mandatory — without it the value is unformatted raw data."
        )

    def test_spin_pct_uses_decimal_format(self, combined_stdout: str) -> None:
        """spin_pct must use :.1f format (e.g. '43.4%'), not integer format ('43%')."""
        assert re.search(r"spin_pct:\s*\d+\.\d+%", combined_stdout), (
            "No 'spin_pct: N.N%' decimal-format pattern found in combined output.\n"
            "The spin estimator must emit one decimal place (:.1f), not integer percent."
        )

    def test_spin_pct_values_in_valid_range(self, combined_stdout: str) -> None:
        """All spin_pct values must be in [0.0, 100.0]."""
        values = re.findall(r"spin_pct:\s*([\d.]+)%", combined_stdout)
        assert values, "No 'spin_pct: N%' values found (see previous tests)"
        for raw in values:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid range [0, 100].\n"
                "The lexical estimator must clamp its output to this range."
            )

    def test_spin_pct_marker_inside_dual_lens_block(self, combined_stdout: str) -> None:
        """'spin_pct:' must appear inside the '## DUAL-LENS EVENTS' section, not before it."""
        dual_idx = combined_stdout.find("## DUAL-LENS EVENTS")
        if dual_idx < 0:
            pytest.skip("'## DUAL-LENS EVENTS' not found — covered by criterion 3 tests")
        block = combined_stdout[dual_idx:]
        assert "spin_pct:" in block, (
            "'spin_pct:' not found inside the '## DUAL-LENS EVENTS' block.\n"
            "Spin annotations must be rendered within the dual-lens section.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_spin_pct_on_article_bullet_line(self, combined_stdout: str) -> None:
        """'spin_pct:' must appear on a '- <title>' bullet line, not as a standalone label."""
        spin_bullets = [
            ln for ln in combined_stdout.splitlines()
            if ln.startswith("- ") and "spin_pct:" in ln
        ]
        assert spin_bullets, (
            "No '- ...' bullet lines containing 'spin_pct:' found in combined output.\n"
            "The dual-lens renderer must embed spin_pct on article bullet lines "
            "(e.g. '- Article Title | spin_pct: 43.4%')."
        )

    def test_spin_pct_values_are_not_all_stub_fifty(self, combined_stdout: str) -> None:
        """All-50.0 values indicate the stub estimator is running, not the real lexical scorer."""
        values = re.findall(r"spin_pct:\s*([\d.]+)%", combined_stdout)
        assert values, "No spin_pct values found"
        floats = [float(v) for v in values]
        assert not all(v == 50.0 for v in floats), (
            "All spin_pct values are exactly 50.0 — the STUB estimator is running.\n"
            "The fixture articles have charged language that produces differentiated scores.\n"
            f"Values found: {floats}"
        )

    def test_at_least_two_spin_pct_annotations(self, combined_stdout: str) -> None:
        """A minimal dual-lens event requires one LEFT and one RIGHT article — minimum 2 values."""
        values = re.findall(r"spin_pct:\s*[\d.]+%", combined_stdout)
        assert len(values) >= 2, (
            f"Expected ≥2 'spin_pct:' annotations; found {len(values)}.\n"
            "A valid dual-lens event must have at least one article per side."
        )

    def test_spin_delta_annotation_also_present(self, combined_stdout: str) -> None:
        """spin_delta (divergence between LEFT and RIGHT columns) must also be present."""
        assert "spin_delta:" in combined_stdout, (
            "'spin_delta:' not found in combined output.\n"
            "The dual-lens block must annotate each event with the spin divergence score."
        )


# ---------------------------------------------------------------------------
# Criterion 5: 'web-server-smoke: PASS' in combined stdout
# ---------------------------------------------------------------------------


class TestWebServerSmokeMarker:
    """Criterion 5: 'web-server-smoke: PASS' must appear in the combined output."""

    def test_web_server_smoke_pass_marker_present(self, combined_stdout: str) -> None:
        """Primary criterion 5: 'web-server-smoke: PASS' must be in the combined output."""
        assert "web-server-smoke: PASS" in combined_stdout, (
            "'web-server-smoke: PASS' not found in combined output of 'python3 acceptance.py'.\n"
            "check_server.py (cmd4 in acceptance.py) must emit this exact string on success.\n"
            f"Output (last 1000):\n{combined_stdout[-1000:]}"
        )

    def test_web_server_smoke_case_exact(self, combined_stdout: str) -> None:
        """The marker is case-sensitive: 'web-server-smoke: PASS' not 'PASS' or 'pass'."""
        # Test that the lowercase 'pass' or wrong-case variants don't masquerade
        assert "web-server-smoke: PASS" in combined_stdout, (
            "Exact marker 'web-server-smoke: PASS' missing — case or spelling mismatch.\n"
            "check_server.py prints: print('web-server-smoke: PASS')"
        )
        # Ensure it's not e.g. 'FAIL' that slipped through
        assert "web-server-smoke: FAIL" not in combined_stdout, (
            "'web-server-smoke: FAIL' found in combined output — the Flask smoke test failed."
        )

    def test_web_server_smoke_not_spurious_match(self, combined_stdout: str) -> None:
        """The marker must appear as a complete token, not embedded mid-sentence."""
        # The canonical output is 'web-server-smoke: PASS\n'
        # Check it appears with standard line boundaries
        assert re.search(r"web-server-smoke: PASS", combined_stdout), (
            "Could not find 'web-server-smoke: PASS' as a clean match.\n"
            "check_server.py must print it on its own line."
        )

    def test_flask_http_200_implied_by_pass(self, combined_stdout: str) -> None:
        """'web-server-smoke: PASS' implies the Flask app returned HTTP 200 — 'FAIL' means otherwise."""
        # If the marker is present, the assertion inside check_server.py passed.
        # Guard against a code path that prints PASS unconditionally (gate gaming).
        assert "web-server-smoke: PASS" in combined_stdout, (
            "'web-server-smoke: PASS' absent — Flask app did not return HTTP 200."
        )
        # If there is any explicit failure marker it must not co-exist with PASS
        if "Expected HTTP 200" in combined_stdout:
            pytest.fail(
                "Combined output contains 'Expected HTTP 200' error alongside other output — "
                "the Flask smoke assert fired but the failure was swallowed."
            )

    def test_run_summary_txt_written_by_check_server(self) -> None:
        """check_server.py writes run_summary.txt as a side-effect; its presence is evidence
        that check_server.py ran and completed (not that it was skipped or never executed)."""
        run_summary = PROJECT_ROOT / "run_summary.txt"
        # run_summary.txt is created during acceptance runs; check it post-run
        # We cannot assert on timing here, but its content is validated below.
        if run_summary.exists():
            content = run_summary.read_text(errors="replace")
            assert "WEB: PASS" in content, (
                "run_summary.txt exists but does not contain 'WEB: PASS'.\n"
                "check_server.py writes 'WEB: PASS' on success; its absence suggests "
                "check_server.py did not complete normally.\n"
                f"run_summary.txt contents:\n{content}"
            )

    def test_web_server_smoke_marker_is_last_significant_output(
        self, combined_stdout: str
    ) -> None:
        """cmd4 (check_server.py) is the last step in acceptance.py; its marker should appear
        near the end of the combined output, not at the very beginning."""
        marker = "web-server-smoke: PASS"
        marker_idx = combined_stdout.find(marker)
        assert marker_idx >= 0, f"'{marker}' not found in combined output"
        # The marker must not be in the first 10% of the output (it's the last step)
        ten_pct = len(combined_stdout) // 10
        assert marker_idx > ten_pct, (
            f"'{marker}' appears too early (at position {marker_idx}) in the combined output.\n"
            "It is the last acceptance step and must not precede the digest sections."
        )


# ---------------------------------------------------------------------------
# Combined omnibus: all four criteria in a single assertion
# ---------------------------------------------------------------------------


class TestAllFourCriteriaSimultaneously:
    """All four output criteria must hold in a single 'python3 acceptance.py' run."""

    def test_all_four_markers_present_in_one_run(
        self,
        smoke_proc: subprocess.CompletedProcess,
        combined_stdout: str,
    ) -> None:
        """Compound criterion: returncode==0 AND all three output markers in combined stdout."""
        # Criterion 2: returncode
        assert smoke_proc.returncode == 0, (
            f"'python3 acceptance.py' exited {smoke_proc.returncode}.\n"
            f"Combined output (last 1000):\n{combined_stdout[-1000:]}"
        )
        # Criterion 3
        assert "## DUAL-LENS EVENTS" in combined_stdout, (
            "'## DUAL-LENS EVENTS' missing from combined stdout."
        )
        # Criterion 4
        assert "spin_pct:" in combined_stdout, (
            "'spin_pct:' missing from combined stdout."
        )
        # Criterion 5
        assert "web-server-smoke: PASS" in combined_stdout, (
            "'web-server-smoke: PASS' missing from combined stdout."
        )

    def test_markers_appear_in_expected_sequence(self, combined_stdout: str) -> None:
        """The four markers must appear in the order imposed by acceptance.py's pipeline:
        digest output (DUAL-LENS EVENTS, spin_pct) before check_server output (web-server-smoke)."""
        dual_idx = combined_stdout.find("## DUAL-LENS EVENTS")
        spin_idx = combined_stdout.find("spin_pct:")
        web_idx = combined_stdout.find("web-server-smoke: PASS")

        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        assert spin_idx >= 0, "'spin_pct:' not found"
        assert web_idx >= 0, "'web-server-smoke: PASS' not found"

        assert dual_idx < web_idx, (
            f"'## DUAL-LENS EVENTS' (at {dual_idx}) must appear BEFORE "
            f"'web-server-smoke: PASS' (at {web_idx}).\n"
            "Acceptance cmd1 (once/digest) runs before cmd4 (check_server.py)."
        )
        assert spin_idx < web_idx, (
            f"'spin_pct:' (at {spin_idx}) must appear BEFORE "
            f"'web-server-smoke: PASS' (at {web_idx})."
        )

    def test_offline_mode_confirmed_by_absence_of_api_calls(
        self, combined_stdout: str
    ) -> None:
        """All three positive markers with no API errors confirms SM_LLM_BACKEND=offline worked."""
        for marker in ("## DUAL-LENS EVENTS", "spin_pct:", "web-server-smoke: PASS"):
            assert marker in combined_stdout, (
                f"Required marker {marker!r} not in combined stdout."
            )
        for bad in ("AuthenticationError", "ANTHROPIC_API_KEY", "RateLimitError"):
            assert bad not in combined_stdout, (
                f"Offline mode violated — {bad!r} found in combined output."
            )

    def test_smoke_run_produces_domain_headers(self, combined_stdout: str) -> None:
        """A full offline run must produce domain H2 headers (WORLD/MARKETS/AI) in addition
        to the four mandated markers — a smoke pass without a real digest is gate gaming."""
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            assert domain in combined_stdout, (
                f"Domain header '{domain}' missing from combined stdout.\n"
                "A valid acceptance run must produce domain-labelled article sections."
            )

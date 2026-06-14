"""Regression guard: pytest exit-0 and offline acceptance verification.

Acceptance criteria under test (verbatim):
  1. subprocess run of sys.executable -m pytest tests/ -x --tb=short exits returncode 0
  2. subprocess run of SM_LLM_BACKEND=offline sys.executable acceptance exits returncode 0
  3. acceptance stdout contains at least one domain header: 'WORLD', 'MARKETS', or 'AI'
  4. acceptance stdout contains both 'LEFT' and 'RIGHT'
  5. acceptance stdout matches regex r'\\d+%' (spin percentage present)

Independent tester perspective: the unit under test is NEVER mocked; mocking it proves
nothing.  Every assertion targets an observable output contract and CAN fail on a real
regression.

Design constraints obeyed:
  - Recursive pytest subprocess invocations are FORBIDDEN (project memory: they hang
    the suite).  Criterion 1 is evidenced by structural checks, not by running pytest.
  - All subprocess runs use sys.executable (not bare 'python' or 'python3').
  - Module-scoped fixtures ensure the acceptance script runs exactly once.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"
RSS_LEFT = FIXTURES / "rss_left.xml"
RSS_RIGHT = FIXTURES / "rss_right.xml"
RSS_MARKETS = FIXTURES / "rss_markets.xml"
RSS_AI = FIXTURES / "rss_ai.xml"
RSS_CARRIER = FIXTURES / "rss_carrier.xml"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"


def _offline_env(**extra: str) -> dict[str, str]:
    return {**os.environ, "SM_LLM_BACKEND": "offline", **extra}


# ---------------------------------------------------------------------------
# Module-scoped subprocess: SM_LLM_BACKEND=offline python acceptance
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_proc() -> subprocess.CompletedProcess:
    """Run the acceptance script with SM_LLM_BACKEND=offline — exactly as criterion 2 states."""
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_FILE)],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=180,
    )


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acceptance_stderr(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 1: pytest tests/ -x --tb=short exits returncode 0
# Evidenced structurally — NOT by recursive subprocess invocation.
# ---------------------------------------------------------------------------


class TestPytestExitsZeroCriterion:
    """Criterion 1: pytest tests/ -x --tb=short exits returncode 0.

    Running pytest inside a pytest test hangs the suite (project memory).
    Evidence is provided by:
      a. This test file passing (all collected tests must pass for pytest to exit 0).
      b. No test file contains a recursive pytest subprocess call.
      c. The test corpus and the package are structurally sound.
    """

    def test_no_test_file_invokes_pytest_as_subprocess(self) -> None:
        """Every test_*.py file must NOT spawn pytest as a subprocess — that hangs."""
        test_dir = PROJECT_ROOT / "tests"
        test_files = list(test_dir.glob("test_*.py"))
        assert test_files, f"No test_*.py files found in {test_dir}"

        bad = []
        for tf in test_files:
            content = tf.read_text(errors="replace")
            for lineno, raw in enumerate(content.splitlines(), start=1):
                line = raw.strip()
                if line.startswith("#"):
                    continue
                # Matches: subprocess.run([..., "pytest", ...])
                # or: subprocess.run([sys.executable, "-m", "pytest", ...])
                if re.search(r'["\']pytest["\']', raw) and re.search(
                    r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", raw
                ):
                    bad.append(f"{tf.name}:{lineno}: {raw.rstrip()}")

        assert not bad, (
            "Recursive pytest subprocess calls found — these hang the suite:\n"
            + "\n".join(bad[:10])
        )

    def test_acceptance_file_does_not_invoke_pytest(self) -> None:
        """The acceptance script must not run pytest — that would be recursive."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "pytest" not in content, (
            "acceptance file must not invoke pytest — recursive invocation hangs the suite."
        )

    def test_test_corpus_is_non_trivial(self) -> None:
        """pytest exits 0 vacuously on an empty suite — the suite must be substantive."""
        test_files = list((PROJECT_ROOT / "tests").glob("test_*.py"))
        assert len(test_files) >= 10, (
            f"Expected ≥10 test_*.py files; found {len(test_files)}. "
            "An almost-empty suite would exit 0 without verifying anything."
        )

    def test_situation_monitor_package_importable(self) -> None:
        """Import failure crashes all acceptance runs — guard it first."""
        try:
            import situation_monitor  # noqa: F401
        except ImportError as exc:
            pytest.fail(f"situation_monitor not importable: {exc}")

    def test_situation_monitor_main_syntax_is_valid(self) -> None:
        """A syntax error in __main__.py crashes every acceptance subprocess."""
        main_path = PROJECT_ROOT / "situation_monitor" / "__main__.py"
        assert main_path.exists(), "situation_monitor/__main__.py missing"
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open({str(main_path)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "situation_monitor/__main__.py has a syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_acceptance_file_syntax_is_valid_python(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", f"import ast; ast.parse(open({str(ACCEPTANCE_FILE)!r}).read())"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            "acceptance file has a Python syntax error:\n"
            + result.stderr.decode(errors="replace")
        )

    def test_acceptance_once_subcommand_is_registered(self) -> None:
        """The 'once' subcommand must exist — its absence crashes cmd1."""
        content = (PROJECT_ROOT / "situation_monitor" / "__main__.py").read_text()
        assert '"once"' in content or "'once'" in content, (
            "situation_monitor/__main__.py must register the 'once' subcommand"
        )

    def test_acceptance_digest_dry_run_subcommand_is_registered(self) -> None:
        """The 'digest-dry-run' subcommand must exist — its absence crashes cmd2."""
        content = (PROJECT_ROOT / "situation_monitor" / "__main__.py").read_text()
        assert "digest-dry-run" in content, (
            "situation_monitor/__main__.py must register the 'digest-dry-run' subcommand"
        )

    def test_all_fixture_files_present_before_pytest_runs(self) -> None:
        """Missing fixtures cause multiple acceptance subprocess tests to fail at startup."""
        required = [
            RSS_FIXTURE, RSS_LEFT, RSS_RIGHT, RSS_MARKETS, RSS_AI,
            RSS_CARRIER, ACCEPTANCE_SOURCE_DEFS, CHECK_SERVER,
        ]
        missing = [str(f) for f in required if not f.exists()]
        assert not missing, (
            "Required fixture/script files are absent; multiple tests would fail:\n"
            + "\n".join(missing)
        )


# ---------------------------------------------------------------------------
# Criterion 2: SM_LLM_BACKEND=offline python acceptance exits returncode 0
# ---------------------------------------------------------------------------


class TestOfflineAcceptanceExitsZero:
    """Criterion 2: SM_LLM_BACKEND=offline sys.executable acceptance exits returncode 0."""

    def test_acceptance_exits_zero(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        assert acceptance_proc.returncode == 0, (
            f"SM_LLM_BACKEND=offline python acceptance exited {acceptance_proc.returncode}; "
            f"expected 0.\n"
            f"stderr (last 1000):\n"
            f"{acceptance_proc.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout (last 500):\n"
            f"{acceptance_proc.stdout.decode(errors='replace')[-500:]}"
        )

    def test_acceptance_stdout_non_empty(self, acceptance_stdout: str) -> None:
        assert acceptance_stdout.strip(), (
            "SM_LLM_BACKEND=offline python acceptance produced empty stdout; "
            "the 'once' digest must be emitted."
        )

    def test_no_traceback_in_stdout(self, acceptance_stdout: str) -> None:
        assert "Traceback" not in acceptance_stdout, (
            "acceptance stdout must not contain a Python Traceback.\n"
            f"stdout (first 2000):\n{acceptance_stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, acceptance_stderr: str) -> None:
        assert "Traceback" not in acceptance_stderr, (
            "acceptance stderr must not contain a Python Traceback.\n"
            f"stderr:\n{acceptance_stderr[:2000]}"
        )

    def test_offline_mode_prevents_live_api_calls(self, acceptance_stderr: str) -> None:
        """With SM_LLM_BACKEND=offline, no LLM API call should appear in stderr."""
        api_error_indicators = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "openai.error",
            "RateLimitError",
        ]
        for indicator in api_error_indicators:
            assert indicator not in acceptance_stderr, (
                f"acceptance stderr contains API error indicator {indicator!r} — "
                "SM_LLM_BACKEND=offline must prevent live LLM calls.\n"
                f"stderr:\n{acceptance_stderr[:1000]}"
            )

    def test_web_server_smoke_pass_emitted(self, acceptance_stdout: str) -> None:
        """check_server.py (cmd4 inside acceptance) must emit 'web-server-smoke: PASS'."""
        assert "web-server-smoke: PASS" in acceptance_stdout, (
            "acceptance stdout must contain 'web-server-smoke: PASS' from check_server.py.\n"
            f"stdout (last 500):\n{acceptance_stdout[-500:]}"
        )

    def test_discourse_carrier_line_emitted(self, acceptance_stdout: str) -> None:
        """cmd3 (carrier once) inside acceptance must emit a 'discourse-carrier' line."""
        carrier_lines = [
            line for line in acceptance_stdout.splitlines()
            if line.startswith("discourse-carrier")
        ]
        assert carrier_lines, (
            "acceptance stdout must contain a line starting with 'discourse-carrier'.\n"
            f"stdout (first 1000):\n{acceptance_stdout[:1000]}"
        )

    def test_acceptance_uses_sys_executable_not_bare_python(self) -> None:
        """The acceptance script must use sys.executable — bare 'python' fails on macOS."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "sys.executable" in content, (
            "acceptance file must use sys.executable, not 'python' or 'python3'.\n"
            "On macOS only 'python3' exists; sys.executable is the portable reference."
        )


# ---------------------------------------------------------------------------
# Criterion 3: acceptance stdout contains at least one of WORLD, MARKETS, AI
# ---------------------------------------------------------------------------


class TestAcceptanceDomainHeaders:
    """Criterion 3: acceptance stdout contains at least one domain header."""

    def test_at_least_one_domain_header_present(self, acceptance_stdout: str) -> None:
        found = any(
            f"## {domain}" in acceptance_stdout
            for domain in ("WORLD", "MARKETS", "AI")
        )
        assert found, (
            "acceptance stdout contains none of '## WORLD', '## MARKETS', '## AI'.\n"
            "At least one domain section must appear for the digest to be valid.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_world_header_is_h2_heading(self, acceptance_stdout: str) -> None:
        """'WORLD' must appear as '## WORLD' — not just the word embedded in a title."""
        assert re.search(r"^## WORLD\b", acceptance_stdout, re.MULTILINE), (
            "No '^## WORLD' H2 heading found in acceptance stdout.\n"
            "World-domain articles must produce a proper ATX H2 section header.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_markets_header_is_h2_heading(self, acceptance_stdout: str) -> None:
        assert re.search(r"^## MARKETS\b", acceptance_stdout, re.MULTILINE), (
            "No '^## MARKETS' H2 heading found in acceptance stdout.\n"
            "rss_markets.xml must produce a MARKETS-domain H2 section header."
        )

    def test_ai_header_is_h2_heading(self, acceptance_stdout: str) -> None:
        assert re.search(r"^## AI\b", acceptance_stdout, re.MULTILINE), (
            "No '^## AI' H2 heading found in acceptance stdout.\n"
            "rss_ai.xml must produce an AI-domain H2 section header."
        )

    def test_all_three_domain_headers_present(self, acceptance_stdout: str) -> None:
        """All three must appear — the fixture covers all three."""
        missing = [
            domain for domain in ("WORLD", "MARKETS", "AI")
            if f"## {domain}" not in acceptance_stdout
        ]
        assert not missing, (
            f"acceptance stdout missing domain H2 headers: {missing}.\n"
            "acceptance_source_defs.json references all three domain feeds.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_domain_section_order_world_markets_ai(self, acceptance_stdout: str) -> None:
        """Canonical order: WORLD → MARKETS → AI (reflects Domain enum order)."""
        world_idx = acceptance_stdout.find("## WORLD")
        markets_idx = acceptance_stdout.find("## MARKETS")
        ai_idx = acceptance_stdout.find("## AI")
        if world_idx >= 0 and markets_idx >= 0:
            assert world_idx < markets_idx, (
                "'## WORLD' must appear before '## MARKETS'"
            )
        if markets_idx >= 0 and ai_idx >= 0:
            assert markets_idx < ai_idx, (
                "'## MARKETS' must appear before '## AI'"
            )

    def test_domain_sections_appear_before_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """Domain sections must precede '## DUAL-LENS EVENTS'."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        if dual_idx < 0:
            return
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            d_idx = acceptance_stdout.find(domain)
            if d_idx >= 0:
                assert d_idx < dual_idx, (
                    f"'{domain}' must appear before '## DUAL-LENS EVENTS' "
                    f"(found at {d_idx}, dual-lens at {dual_idx})"
                )

    def test_each_domain_section_has_at_least_one_article(
        self, acceptance_stdout: str
    ) -> None:
        """Empty domain sections (H2 header with no articles) are a structural failure."""
        lines = acceptance_stdout.splitlines()
        current_domain = None
        domain_article_counts: dict[str, int] = {}
        for line in lines:
            m = re.match(r"^## (WORLD|MARKETS|AI)$", line)
            if m:
                current_domain = m.group(1)
                domain_article_counts[current_domain] = 0
            elif current_domain and line.startswith("### "):
                domain_article_counts[current_domain] = domain_article_counts.get(current_domain, 0) + 1
            elif line.startswith("## DUAL-LENS") or line.startswith("## All"):
                current_domain = None

        for domain, count in domain_article_counts.items():
            assert count > 0, (
                f"Domain section '## {domain}' has no article entries (### headings).\n"
                "An empty domain section would indicate the fixture feed produced no articles."
            )


# ---------------------------------------------------------------------------
# Criterion 4: acceptance stdout contains both 'LEFT' and 'RIGHT'
# ---------------------------------------------------------------------------


class TestAcceptanceDualColumnMarkers:
    """Criterion 4: acceptance stdout contains both 'LEFT' and 'RIGHT'."""

    def test_left_marker_present(self, acceptance_stdout: str) -> None:
        assert "LEFT" in acceptance_stdout, (
            "acceptance stdout must contain 'LEFT'.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_right_marker_present(self, acceptance_stdout: str) -> None:
        assert "RIGHT" in acceptance_stdout, (
            "acceptance stdout must contain 'RIGHT'.\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_both_left_and_right_present(self, acceptance_stdout: str) -> None:
        assert "LEFT" in acceptance_stdout and "RIGHT" in acceptance_stdout, (
            "acceptance stdout must contain BOTH 'LEFT' and 'RIGHT'.\n"
            "A dual-lens event without both sides is structurally invalid."
        )

    def test_left_is_h4_heading_not_embedded_prose(self, acceptance_stdout: str) -> None:
        """'LEFT' must appear as '#### LEFT' H4 heading, not as a word in an article title."""
        assert re.search(r"^#### LEFT\b", acceptance_stdout, re.MULTILINE), (
            "No '^#### LEFT' H4 heading found in acceptance stdout.\n"
            "The dual-lens renderer must emit '#### LEFT (N articles)' headings."
        )

    def test_right_is_h4_heading_not_embedded_prose(self, acceptance_stdout: str) -> None:
        assert re.search(r"^#### RIGHT\b", acceptance_stdout, re.MULTILINE), (
            "No '^#### RIGHT' H4 heading found in acceptance stdout.\n"
            "The dual-lens renderer must emit '#### RIGHT (N articles)' headings."
        )

    def test_left_and_right_are_inside_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """LEFT and RIGHT must appear INSIDE the DUAL-LENS EVENTS block, not before it."""
        dual_idx = acceptance_stdout.find("DUAL-LENS EVENTS")
        assert dual_idx >= 0, (
            "'DUAL-LENS EVENTS' not found in acceptance stdout — "
            "LEFT/RIGHT headings cannot be in their required position."
        )
        block = acceptance_stdout[dual_idx:]
        assert "LEFT" in block, (
            "'LEFT' not found inside the DUAL-LENS EVENTS block.\n"
            f"Block (first 500):\n{block[:500]}"
        )
        assert "RIGHT" in block, (
            "'RIGHT' not found inside the DUAL-LENS EVENTS block.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_left_appears_before_right_in_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """Within the DUAL-LENS block, LEFT renders before RIGHT."""
        dual_idx = acceptance_stdout.find("DUAL-LENS EVENTS")
        if dual_idx < 0:
            pytest.skip("No DUAL-LENS EVENTS block in stdout")
        block = acceptance_stdout[dual_idx:]
        left_idx = block.find("#### LEFT")
        right_idx = block.find("#### RIGHT")
        if left_idx >= 0 and right_idx >= 0:
            assert left_idx < right_idx, (
                "'#### LEFT' must appear before '#### RIGHT' within the DUAL-LENS block"
            )

    def test_left_column_has_bullet_article(self, acceptance_stdout: str) -> None:
        """'#### LEFT' column must contain at least one '- <title>' article bullet."""
        left_idx = acceptance_stdout.find("#### LEFT")
        assert left_idx >= 0, "'#### LEFT' not found in acceptance stdout"
        block_from_left = acceptance_stdout[left_idx:]
        next_heading = re.search(r"\n#+[ ]", block_from_left[5:])
        end = (next_heading.start() + 5) if next_heading else len(block_from_left)
        left_section = block_from_left[:end]
        bullet_lines = [l for l in left_section.splitlines() if l.startswith("- ")]
        assert bullet_lines, (
            "'#### LEFT' column must contain at least one '- article' bullet.\n"
            f"LEFT section:\n{left_section[:500]}"
        )

    def test_right_column_has_bullet_article(self, acceptance_stdout: str) -> None:
        """'#### RIGHT' column must contain at least one '- <title>' article bullet."""
        right_idx = acceptance_stdout.find("#### RIGHT")
        assert right_idx >= 0, "'#### RIGHT' not found in acceptance stdout"
        block_from_right = acceptance_stdout[right_idx:]
        next_heading = re.search(r"\n#+[ ]", block_from_right[5:])
        end = (next_heading.start() + 5) if next_heading else len(block_from_right)
        right_section = block_from_right[:end]
        bullet_lines = [l for l in right_section.splitlines() if l.startswith("- ")]
        assert bullet_lines, (
            "'#### RIGHT' column must contain at least one '- article' bullet.\n"
            f"RIGHT section:\n{right_section[:500]}"
        )

    def test_left_and_right_article_count_annotations(
        self, acceptance_stdout: str
    ) -> None:
        """The heading format '#### LEFT (N article(s))' must include the count."""
        # Pattern: #### LEFT (1 article) or #### LEFT (3 articles)
        pattern = re.compile(r"^#### (LEFT|RIGHT)\s*\(\d+ articles?\)$", re.MULTILINE)
        matches = pattern.findall(acceptance_stdout)
        assert matches, (
            "No '#### LEFT (N articles)' or '#### RIGHT (N articles)' headings found.\n"
            "The dual-lens renderer must annotate headings with article counts."
        )


# ---------------------------------------------------------------------------
# Criterion 5: acceptance stdout matches r'\d+%'
# ---------------------------------------------------------------------------


class TestAcceptanceSpinPercentage:
    """Criterion 5: acceptance stdout matches the regex r'\\d+%'."""

    def test_digit_percent_pattern_present(self, acceptance_stdout: str) -> None:
        """The minimal criterion: at least one '<digit>%' must appear."""
        assert re.search(r"\d+%", acceptance_stdout), (
            "acceptance stdout contains no '<digit>%' pattern.\n"
            "The spin estimator must emit at least one numeric percentage.\n"
            f"stdout (first 2000):\n{acceptance_stdout[:2000]}"
        )

    def test_spin_pct_keyword_present(self, acceptance_stdout: str) -> None:
        """'spin_pct:' keyword must appear — not just any '%' in a URL or date."""
        assert "spin_pct:" in acceptance_stdout, (
            "acceptance stdout must contain 'spin_pct:' keyword.\n"
            "The dual-lens renderer annotates each article with its spin percentage."
        )

    def test_spin_pct_followed_by_decimal_percent(self, acceptance_stdout: str) -> None:
        """'spin_pct:' must be followed by 'N.N%' on the same line (:.1f format)."""
        match = re.search(r"spin_pct:\s*\d+\.\d+%", acceptance_stdout)
        assert match is not None, (
            "No 'spin_pct: N.N%' pattern found in acceptance stdout.\n"
            "Format must be :.1f (e.g. '43.4%'), not integer percent (e.g. '43%').\n"
            f"stdout (first 3000):\n{acceptance_stdout[:3000]}"
        )

    def test_spin_pct_values_in_valid_range(self, acceptance_stdout: str) -> None:
        """All spin_pct values must be in [0.0, 100.0]."""
        spin_values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert spin_values, "No 'spin_pct: N.N%' values found in acceptance stdout"
        for raw in spin_values:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside [0, 100] — "
                "the lexical estimator clamps to this range."
            )

    def test_spin_pct_decimal_point_present(self, acceptance_stdout: str) -> None:
        """spin_pct must use floating-point format ('43.4%'), not integer ('43%')."""
        spin_values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert spin_values, "No spin_pct values in acceptance stdout"
        for raw in spin_values:
            assert "." in raw, (
                f"spin_pct value {raw!r} is missing a decimal point.\n"
                "Format must be :.1f (e.g. '43.4%'), not '%.0f' (e.g. '43%')."
            )

    def test_at_least_two_spin_pct_values(self, acceptance_stdout: str) -> None:
        """A dual-lens event requires at least one article per side — minimum 2 values."""
        spin_values = re.findall(r"spin_pct:\s*[\d.]+%", acceptance_stdout)
        assert len(spin_values) >= 2, (
            f"Expected ≥2 'spin_pct:' annotations; found {len(spin_values)}.\n"
            "A minimal dual-lens event requires one LEFT and one RIGHT article."
        )

    def test_spin_pct_appears_inside_dual_lens_block(self, acceptance_stdout: str) -> None:
        """The '<digit>%' pattern must appear INSIDE the DUAL-LENS EVENTS block."""
        dual_idx = acceptance_stdout.find("DUAL-LENS EVENTS")
        assert dual_idx >= 0, (
            "'DUAL-LENS EVENTS' not found — spin_pct cannot be in its required block"
        )
        block = acceptance_stdout[dual_idx:]
        assert re.search(r"\d+%", block), (
            "No '<digit>%' pattern found inside the DUAL-LENS EVENTS block.\n"
            "Spin annotations must be rendered within the dual-lens block.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_spin_values_are_not_all_stub_fifty(self, acceptance_stdout: str) -> None:
        """If all spin_pct values are exactly 50.0, the stub estimator is running.

        The fixture articles contain charged language; the REAL deterministic lexical
        estimator produces differentiated values — not all 50.0 (that's the stub output).
        """
        spin_values = re.findall(r"spin_pct:\s*([\d.]+)%", acceptance_stdout)
        assert spin_values, "No spin_pct values in acceptance stdout"
        float_values = [float(v) for v in spin_values]
        all_fifty = all(v == 50.0 for v in float_values)
        assert not all_fifty, (
            "All spin_pct values are exactly 50.0 — the STUB estimator is running.\n"
            "The fixture articles have charged language producing non-50 scores.\n"
            f"Values found: {float_values}"
        )

    def test_spin_delta_non_negative(self, acceptance_stdout: str) -> None:
        """spin_delta (divergence between LEFT and RIGHT avg spin) must be ≥ 0."""
        deltas = re.findall(r"spin_delta:\s*([\d.]+)", acceptance_stdout)
        assert deltas, "acceptance stdout must contain 'spin_delta:' event annotations"
        for raw in deltas:
            assert float(raw) >= 0.0, f"spin_delta must be non-negative; got {raw!r}"

    def test_spin_delta_nonzero_for_left_right_fixture(self, acceptance_stdout: str) -> None:
        """The left/right fixture articles have different framing — delta must diverge."""
        deltas = re.findall(r"spin_delta:\s*([\d.]+)", acceptance_stdout)
        assert deltas, "No spin_delta values found in acceptance stdout"
        nonzero = [d for d in deltas if float(d) > 0.0]
        assert nonzero, (
            "All spin_delta values are 0.0.\n"
            "The left-leaning and right-leaning fixture articles have different charged "
            "language; their spin_pct values should differ, producing a non-zero delta.\n"
            f"All delta values: {deltas}"
        )

    def test_spin_pct_on_bullet_lines_in_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """spin_pct must appear on '- <title> | spin_pct: N.N%' bullet lines."""
        bullet_spin_lines = [
            line for line in acceptance_stdout.splitlines()
            if line.startswith("- ") and "spin_pct:" in line
        ]
        assert bullet_spin_lines, (
            "No '- <title> | spin_pct: N.N%' bullet lines found.\n"
            "The dual-lens renderer must annotate each article bullet with spin_pct."
        )


# ---------------------------------------------------------------------------
# Lexical spin estimator — unit tests (offline, no subprocess)
# ---------------------------------------------------------------------------


class TestLexicalSpinEstimatorUnit:
    """Unit tests for situation_monitor.lexicon.score_text.

    These exercise the REAL implementation — mocking it would prove nothing.
    """

    def test_neutral_headline_scores_zero(self) -> None:
        from situation_monitor.lexicon import score_text
        score = score_text("Council Meets on Monday")
        assert score.spin_pct == 0.0, (
            f"A neutral headline must score 0.0; got {score.spin_pct}"
        )

    def test_fear_term_in_title_scores_above_zero(self) -> None:
        from situation_monitor.lexicon import score_text
        score = score_text("Crisis Threatens Community Safety")
        assert score.spin_pct > 0.0, (
            "A headline with fear/charged terms must score above 0.0"
        )

    def test_loaded_language_in_title_scores_above_zero(self) -> None:
        from situation_monitor.lexicon import score_text
        score = score_text("Extremist Regime Spreads Propaganda")
        assert score.spin_pct > 0.0, (
            "A headline with loaded language must score above 0.0"
        )

    def test_endorsement_framing_scores_above_zero(self) -> None:
        from situation_monitor.lexicon import score_text
        score = score_text("Landmark Breakthrough Hailed by Scientists")
        assert score.spin_pct > 0.0, (
            "Endorsement framing (hailed, breakthrough, landmark) must score above 0.0"
        )

    def test_spin_pct_never_exceeds_100(self) -> None:
        from situation_monitor.lexicon import score_text
        dense = " ".join([
            "chaos extremist regime tyranny ruthless brutal",
            "slams blasts destroy threatens surge plummet",
            "terror catastrophe collapse disaster doom panic",
        ] * 5)
        score = score_text(dense)
        assert score.spin_pct <= 100.0, (
            f"spin_pct must never exceed 100.0; got {score.spin_pct}"
        )

    def test_spin_pct_never_negative(self) -> None:
        from situation_monitor.lexicon import score_text
        score = score_text("", body="")
        assert score.spin_pct >= 0.0, "spin_pct must never be negative"

    def test_empty_input_scores_exactly_zero(self) -> None:
        from situation_monitor.lexicon import score_text
        score = score_text("", "")
        assert score.spin_pct == 0.0, "Empty title and body must score 0.0"

    def test_score_is_deterministic(self) -> None:
        from situation_monitor.lexicon import score_text
        title = "Markets Surge on Record Earnings Season"
        score1 = score_text(title)
        score2 = score_text(title)
        assert score1.spin_pct == score2.spin_pct, (
            "score_text must be deterministic — same input must yield same spin_pct"
        )

    def test_body_with_charged_terms_raises_score(self) -> None:
        from situation_monitor.lexicon import score_text
        title = "Council Meeting Scheduled"
        body = "Chaos erupted as extremists threatened the regime in a catastrophic disaster."
        score_no_body = score_text(title)
        score_with_body = score_text(title, body)
        assert score_with_body.spin_pct >= score_no_body.spin_pct, (
            "Adding charged body text must not decrease spin_pct"
        )

    def test_receipts_are_non_empty_for_charged_text(self) -> None:
        from situation_monitor.lexicon import score_text
        score = score_text("Government Threatens Regime Collapse")
        receipts = score.receipts()
        assert isinstance(receipts, str)
        assert receipts.strip(), "receipts() must not be empty for charged text"

    def test_receipts_mention_fired_category(self) -> None:
        from situation_monitor.lexicon import score_text
        score = score_text("Extremist Regime Chaos Threatens")
        receipts = score.receipts()
        # At least one category label must appear in the human-readable receipts
        assert any(cat in receipts for cat in [
            "Loaded Language", "Charged Verbs", "Fear", "Endorsement"
        ]), f"receipts() must name the category; got: {receipts!r}"

    def test_title_hits_weighted_higher_than_body_hits(self) -> None:
        from situation_monitor.lexicon import score_text
        # Same term in title vs body — title should yield higher or equal score
        charged_word = "threatens"
        score_in_title = score_text(f"Government {charged_word} Economy")
        score_in_body = score_text("Government News", body=f"It {charged_word} stability.")
        # Title weight is 2x body weight; title-hit score should be >= body-only score
        assert score_in_title.spin_pct >= score_in_body.spin_pct, (
            "A charged term in the title must contribute at least as much as in the body.\n"
            f"Title score: {score_in_title.spin_pct}, body-only score: {score_in_body.spin_pct}"
        )

    def test_subscores_are_non_negative(self) -> None:
        from situation_monitor.lexicon import score_text
        score = score_text("Extremist Regime Crisis Threatens Collapse")
        for cat, subscore in score.subscores.items():
            assert subscore >= 0.0, f"Subscore for '{cat}' is negative: {subscore}"

    def test_fired_contains_only_words_from_input(self) -> None:
        from situation_monitor.lexicon import score_text
        title = "Regime Threatens Economy"
        score = score_text(title)
        all_input_words = set(re.findall(r"[a-z][a-z'-]*", title.lower()))
        for cat, words in score.fired.items():
            for word in words:
                assert word in all_input_words, (
                    f"Fired word {word!r} not in input title words {all_input_words}.\n"
                    "score_text must only report words actually present in the input."
                )


# ---------------------------------------------------------------------------
# Dual-lens group_by_event — unit tests (offline, no subprocess)
# ---------------------------------------------------------------------------


class TestGroupByEventUnit:
    """Unit tests for situation_monitor.dual_lens.group_by_event.

    The real implementation is exercised — no mocking.
    """

    def test_empty_articles_returns_empty(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        assert group_by_event([]) == [], "Empty input must return empty event list"

    def test_single_article_yields_one_event(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import Article
        articles = [Article(url="http://a.com/1", title="Economy Grows Steadily Quarter", source="T")]
        events = group_by_event(articles)
        assert len(events) == 1, "One article must produce exactly one event cluster"

    def test_unrelated_articles_produce_separate_events(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import Article
        articles = [
            Article(url="http://a.com/1", title="Climate Policy Reform Backed Scientists", source="A"),
            Article(url="http://a.com/2", title="Rocket Launch Mars Mission Success", source="B"),
        ]
        events = group_by_event(articles)
        assert len(events) == 2, (
            "Articles sharing no significant words must cluster into separate events"
        )

    def test_related_articles_cluster_into_one_event(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import Article
        articles = [
            Article(url="http://a.com/1", title="Government Climate Policy Reform Backed Scientists", source="L", source_lean="left"),
            Article(url="http://a.com/2", title="Government Climate Policy Reform Threatens Growth", source="R", source_lean="right"),
        ]
        events = group_by_event(articles)
        assert len(events) == 1, (
            "Articles sharing ≥2 significant words must cluster into one event"
        )

    def test_spin_delta_non_negative(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import Article
        articles = [
            Article(url="http://a.com/1", title="Policy Crisis Reform Impact Severe", source="L", source_lean="left"),
            Article(url="http://a.com/2", title="Policy Crisis Reform Threatens Markets", source="R", source_lean="right"),
        ]
        events = group_by_event(articles)
        for event in events:
            assert event.spin_delta >= 0.0, (
                f"spin_delta must be non-negative; got {event.spin_delta}"
            )

    def test_left_lean_articles_bucket_to_left(self) -> None:
        from situation_monitor.dual_lens import group_by_event, deterministic_spin
        from situation_monitor.models import Article, SpinResult
        left_article = Article(
            url="http://a.com/1", title="Reform Policy Change Backed", source="LP", source_lean="left"
        )

        def forced_left_spin(a: Article) -> SpinResult:
            return SpinResult(spin_pct=60.0, lens="left", rubric={}, receipts="test")

        events = group_by_event([left_article], spin_fn=forced_left_spin)
        assert events, "Must produce at least one event"
        event = events[0]
        assert len(event.left_articles) == 1, (
            "A left-lean article with lens='left' must bucket to left_articles"
        )
        assert len(event.right_articles) == 0, (
            "A left-lean article must not appear in right_articles"
        )

    def test_right_lean_articles_bucket_to_right(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import Article, SpinResult

        right_article = Article(
            url="http://a.com/1", title="Reform Policy Markets Economy Growth", source="RP", source_lean="right"
        )

        def forced_right_spin(a: Article) -> SpinResult:
            return SpinResult(spin_pct=70.0, lens="right", rubric={}, receipts="test")

        events = group_by_event([right_article], spin_fn=forced_right_spin)
        assert events
        event = events[0]
        assert len(event.right_articles) == 1, (
            "A right-lean article with lens='right' must bucket to right_articles"
        )
        assert len(event.left_articles) == 0

    def test_centre_lean_articles_bucket_to_center(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import Article, SpinResult

        def forced_centre_spin(a: Article) -> SpinResult:
            return SpinResult(spin_pct=45.0, lens="centre", rubric={}, receipts="test")

        article = Article(url="http://a.com/1", title="Economy Report Published Quarter Analysis", source="CP", source_lean="centre")
        events = group_by_event([article], spin_fn=forced_centre_spin)
        assert events
        event = events[0]
        assert len(event.center_articles) == 1, (
            "A centre-lean article must bucket to center_articles"
        )

    def test_event_title_is_longest_cluster_title(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import Article
        short_title = "Climate Policy Reform"
        long_title = "Government Climate Policy Reform Threatens Sweeping Economic Growth Changes"
        articles = [
            Article(url="http://a.com/1", title=short_title, source="A"),
            Article(url="http://a.com/2", title=long_title, source="B"),
        ]
        events = group_by_event(articles)
        if len(events) == 1:
            assert events[0].event_title == long_title, (
                f"Event title must be the longest article title in the cluster.\n"
                f"Expected: {long_title!r}\nGot: {events[0].event_title!r}"
            )

    def test_spin_pct_always_in_range_for_all_articles(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import Article
        articles = [
            Article(url=f"http://a.com/{i}", title=f"Story {i} Threatens Crisis Collapse Economy", source="X")
            for i in range(6)
        ]
        events = group_by_event(articles)
        for event in events:
            all_aa = event.left_articles + event.right_articles + event.center_articles
            for aa in all_aa:
                assert 0.0 <= aa.spin.spin_pct <= 100.0, (
                    f"spin_pct {aa.spin.spin_pct}% is outside [0, 100] for article "
                    f"{aa.article.title!r}"
                )

    def test_custom_spin_fn_is_called(self) -> None:
        from situation_monitor.dual_lens import group_by_event
        from situation_monitor.models import Article, SpinResult
        call_count = [0]

        def counting_spin(a: Article) -> SpinResult:
            call_count[0] += 1
            return SpinResult(spin_pct=50.0, lens="centre", rubric={}, receipts="counted")

        articles = [
            Article(url=f"http://a.com/{i}", title=f"Event Story Politics Economy {i}", source="X")
            for i in range(4)
        ]
        group_by_event(articles, spin_fn=counting_spin)
        assert call_count[0] == len(articles), (
            f"spin_fn must be called once per article; "
            f"expected {len(articles)} calls, got {call_count[0]}"
        )


# ---------------------------------------------------------------------------
# Structural guard: no test artifacts pollute the pytest collection
# ---------------------------------------------------------------------------


class TestNoArtifactPollution:
    """Artifacts created by acceptance runs must not be collectible by pytest."""

    def test_run_summary_txt_is_not_a_py_file(self) -> None:
        """run_summary.txt (written by check_server.py) must remain .txt."""
        txt_path = PROJECT_ROOT / "run_summary.txt"
        py_path = PROJECT_ROOT / "run_summary.py"
        assert not py_path.exists(), (
            "run_summary.py must not exist — run_summary.txt is the artefact;\n"
            "a .py file at this path would be collected by pytest and could pollute the suite."
        )

    def test_no_test_py_files_in_project_root(self) -> None:
        """test_*.py files in the project root would be collected by pytest unexpectedly."""
        root_test_files = [
            f for f in PROJECT_ROOT.glob("test_*.py")
        ]
        assert not root_test_files, (
            "test_*.py files found in project root — pytest collects from here:\n"
            + "\n".join(str(f) for f in root_test_files)
        )

    def test_acceptance_file_itself_not_a_test_module(self) -> None:
        """The 'acceptance' script must not be named test_*.py and must not import pytest."""
        assert ACCEPTANCE_FILE.name == "acceptance", (
            f"Acceptance file must be named 'acceptance', not {ACCEPTANCE_FILE.name!r}"
        )
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "import pytest" not in content, (
            "acceptance file must not import pytest — it is not a test module"
        )

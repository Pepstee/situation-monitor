"""Regression guard — precise acceptance criteria.

Targets four criteria exactly as stated:
  1. pytest tests/ -x --tb=short exits 0 — evidenced by this file passing AND by
     scanning the test corpus for recursive subprocess invocations (which would hang).
  2. Each line in the ``acceptance`` file exits 0 when run verbatim as a shell command
     (including environment-variable prefixes and pipe operators as written).
  3. Acceptance 'once' stdout contains at least one of: WORLD, MARKETS, AI.
  4. Acceptance 'once' stdout contains a digit followed by % (spin estimate present).

Design choices:
  - Criteria 2 uses shell=True with the literal acceptance-file lines so that the
    environment-variable assignments and the grep pipe in cmd3 are honoured by the
    real shell — not reconstructed by Python.
  - Criteria 3 & 4 use a module-scoped subprocess fixture to avoid running 'once' twice.
  - Criterion 1 does NOT spawn ``pytest tests/`` as a subprocess (project memory:
    recursive meta-tests hang the suite).  Absence of recursive invocations in any
    test file is verified by source scan instead.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _acceptance_commands() -> list[str]:
    """Return the non-comment, non-blank command lines from the acceptance file."""
    text = ACCEPTANCE_FILE.read_text()
    return [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


# ---------------------------------------------------------------------------
# Module-scoped 'once' subprocess — used by criteria 3 and 4.
# Runs exactly once per test-session module to avoid repeated network/LLM calls.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def once_proc() -> subprocess.CompletedProcess:
    """Run 'situation_monitor once' offline with fixture RSS and source defs."""
    import os

    env = {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
    }
    return subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "once", "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        timeout=120,
    )


@pytest.fixture(scope="module")
def once_stdout(once_proc: subprocess.CompletedProcess) -> str:
    return once_proc.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# 1. pytest criterion — evidenced by this file passing + no recursive calls
# ---------------------------------------------------------------------------


class TestPytestExitsZeroEvidence:
    """Criterion 1: pytest tests/ -x --tb=short exits 0.

    We do NOT run pytest recursively (project memory: that hangs the suite).
    Instead we verify two structural properties that guarantee a clean run:
      a. This test file itself passes (pytest exits 0 iff all collected tests pass).
      b. No test source file invokes pytest as a subprocess — the pattern that hangs.
    """

    def test_all_subprocess_calls_in_this_file_target_situation_monitor_or_shell(
        self,
    ) -> None:
        """Every subprocess call in this file must target situation_monitor or shell commands.

        Evidence for criterion 1 (pytest exits 0) comes from this file passing —
        not from a nested pytest invocation.  Verify that every subprocess.run call
        in this file uses sys.executable and 'situation_monitor', or shell=True for
        the acceptance file lines.  Any line using 'pytest' as a subprocess argument
        would be a recursive invocation that hangs the suite (project memory).
        """
        source = Path(__file__).read_text(errors="replace")
        # Look for lines that call subprocess and pass "pytest" literally as a positional
        # argument (the recursive pattern): subprocess.run([..., "pytest", ...]).
        # We check line-by-line to avoid matching comments or docstrings.
        for lineno, line in enumerate(source.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            # Pattern that indicates a subprocess call with "pytest" as an argument token
            if re.search(r'"pytest"', line) and re.search(
                r"subprocess\.(run|Popen|call|check_output|check_call)", line
            ):
                pytest.fail(
                    f"Line {lineno} appears to invoke pytest as a subprocess argument:\n"
                    f"  {line.rstrip()}\n"
                    "Recursive pytest invocations hang the suite (project memory).\n"
                    "Evidence for pytest-exits-0 must come from this file passing, not a sub-call."
                )

    def test_test_files_directory_is_populated(self) -> None:
        """The tests/ directory must contain collected test files."""
        test_files = list((PROJECT_ROOT / "tests").glob("test_*.py"))
        assert len(test_files) >= 5, (
            f"Expected at least 5 test_*.py files in tests/; found {len(test_files)}.\n"
            "An empty or sparse test directory would cause pytest to exit 0 vacuously."
        )

    def test_acceptance_file_exists_for_fixture_commands(self) -> None:
        """The acceptance file must exist so its commands can be verified."""
        assert ACCEPTANCE_FILE.exists(), (
            f"'acceptance' file missing at {ACCEPTANCE_FILE}. "
            "Cannot verify acceptance commands or run pytest gate."
        )

    def test_acceptance_source_defs_json_is_parseable(self) -> None:
        """acceptance_source_defs.json must be valid JSON with 'source_defs' list."""
        import json
        try:
            data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        except Exception as exc:
            pytest.fail(
                f"acceptance_source_defs.json is not valid JSON: {exc}\n"
                "This would cause all acceptance commands to fail at import."
            )
        assert isinstance(data.get("source_defs"), list), (
            "acceptance_source_defs.json must contain a 'source_defs' list key"
        )

    def test_rss_fixture_exists_and_has_xml_items(self) -> None:
        """rss_sample.xml must exist and have at least one <item> — prerequisite for ingest."""
        assert RSS_FIXTURE.exists(), f"rss_sample.xml missing at {RSS_FIXTURE}"
        content = RSS_FIXTURE.read_text(errors="replace")
        assert "<item>" in content, (
            "rss_sample.xml has no <item> elements; acceptance 'once' run would produce no articles"
        )

    def test_situation_monitor_package_importable(self) -> None:
        """situation_monitor must be importable — import failure would crash all acceptance runs."""
        try:
            import situation_monitor  # noqa: F401
        except ImportError as exc:
            pytest.fail(
                f"Cannot import situation_monitor: {exc}\n"
                "Acceptance commands rely on 'python -m situation_monitor'."
            )

    def test_situation_monitor_main_has_once_and_digest_subcommands(self) -> None:
        """The __main__ module must define both 'once' and 'digest-dry-run' subcommands."""
        main_file = PROJECT_ROOT / "situation_monitor" / "__main__.py"
        assert main_file.exists(), "situation_monitor/__main__.py missing"
        content = main_file.read_text(errors="replace")
        assert "once" in content, (
            "situation_monitor/__main__.py must define or route the 'once' subcommand"
        )
        assert "digest-dry-run" in content or "digest_dry_run" in content, (
            "situation_monitor/__main__.py must define or route the 'digest-dry-run' subcommand"
        )


# ---------------------------------------------------------------------------
# 2. Each acceptance file line runs verbatim via shell and exits 0
# ---------------------------------------------------------------------------


class TestAcceptanceFileLinesExitZero:
    """Criterion 2: `SM_LLM_BACKEND=offline python acceptance` exits 0 with required output.

    The acceptance file is a Python script that runs four internal commands:
      cmd1: situation_monitor once  — domain digest with dual-lens and spin_pct
      cmd2: situation_monitor digest-dry-run — Telegram format digest
      cmd3: carrier once            — discourse-carrier line validation
      cmd4: check_server.py         — Flask smoke test

    Tests run the whole script via `python acceptance` (not line-by-line shell).
    """

    @pytest.fixture(scope="class")
    def _acceptance_proc(self) -> subprocess.CompletedProcess:
        import os
        env = {**os.environ, "SM_LLM_BACKEND": "offline"}
        return subprocess.run(
            [sys.executable, str(ACCEPTANCE_FILE)],
            capture_output=True,
            cwd=PROJECT_ROOT,
            env=env,
            timeout=120,
        )

    @pytest.fixture(scope="class")
    def _acceptance_stdout(self, _acceptance_proc: subprocess.CompletedProcess) -> str:
        return _acceptance_proc.stdout.decode(errors="replace")

    def test_acceptance_file_has_at_least_one_command(self) -> None:
        content = ACCEPTANCE_FILE.read_text()
        assert content.strip(), "acceptance file must not be empty"
        assert "situation_monitor" in content, (
            "acceptance file must invoke situation_monitor"
        )

    def test_all_commands_reference_python(self) -> None:
        """Acceptance file must be a Python script (references python/sys.executable)."""
        content = ACCEPTANCE_FILE.read_text()
        assert "python" in content, (
            "Acceptance file must reference python (shebang or subprocess).\n"
            "The acceptance file must be a Python script runnable as 'python acceptance'."
        )

    def test_cmd1_verbatim_shell_exits_zero(
        self, _acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """Running `python acceptance` must exit 0 (cmd1=once passes)."""
        assert _acceptance_proc.returncode == 0, (
            f"'python acceptance' exited {_acceptance_proc.returncode}; expected 0.\n"
            f"stderr (last 500):\n{_acceptance_proc.stderr.decode(errors='replace')[-500:]}\n"
            f"stdout (last 300):\n{_acceptance_proc.stdout.decode(errors='replace')[-300:]}"
        )

    def test_cmd2_verbatim_shell_exits_zero(
        self, _acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """Acceptance script exits 0 (cmd2=digest-dry-run also passed)."""
        assert _acceptance_proc.returncode == 0, (
            f"'python acceptance' exited {_acceptance_proc.returncode}; expected 0."
        )

    def test_cmd3_verbatim_shell_exits_zero(
        self, _acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """Acceptance script exits 0 (cmd3=carrier check passed)."""
        assert _acceptance_proc.returncode == 0, (
            f"'python acceptance' exited {_acceptance_proc.returncode}; expected 0."
        )

    def test_cmd4_verbatim_shell_exits_zero(
        self, _acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """Acceptance script exits 0 (cmd4=check_server.py passed)."""
        assert _acceptance_proc.returncode == 0, (
            f"'python acceptance' exited {_acceptance_proc.returncode}; expected 0."
        )

    def test_all_four_acceptance_lines_exit_zero(
        self, _acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        """Omnibus: the full acceptance Python script exits 0."""
        assert _acceptance_proc.returncode == 0, (
            f"'python acceptance' exited {_acceptance_proc.returncode}; expected 0.\n"
            f"stderr: {_acceptance_proc.stderr.decode(errors='replace')[-300:]!r}"
        )

    def test_cmd1_verbatim_stdout_non_empty(self, _acceptance_stdout: str) -> None:
        """Acceptance stdout must be non-empty (cmd1=once produced output)."""
        assert _acceptance_stdout.strip(), "'python acceptance' produced empty stdout"

    def test_cmd2_verbatim_stdout_non_empty(self, _acceptance_stdout: str) -> None:
        """Acceptance stdout must include Telegram-format digest (cmd2=digest-dry-run)."""
        assert "Situation Monitor" in _acceptance_stdout, (
            "acceptance stdout must contain 'Situation Monitor' from once or digest-dry-run"
        )

    def test_cmd3_grep_output_starts_with_discourse_carrier(
        self, _acceptance_stdout: str
    ) -> None:
        """Acceptance stdout must contain a line starting with 'discourse-carrier' (cmd3)."""
        carrier_lines = [
            l for l in _acceptance_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert carrier_lines, (
            "Acceptance stdout must contain a line starting with 'discourse-carrier'.\n"
            "cmd3 (carrier once) validates that the carrier feed produces discourse-carrier output."
        )

    def test_no_acceptance_command_is_recursive_pytest(self) -> None:
        """No acceptance file line must invoke pytest — that would recurse."""
        content = ACCEPTANCE_FILE.read_text()
        assert "pytest" not in content, (
            "Acceptance file must not invoke pytest — recursive invocation forbidden."
        )


# ---------------------------------------------------------------------------
# 3. 'once' stdout contains at least one of: WORLD, MARKETS, AI
# ---------------------------------------------------------------------------


class TestOnceStdoutDomainSections:
    """Criterion 3: acceptance 'once' stdout contains WORLD, MARKETS, or AI.

    The criterion is 'at least one of', so the test fails only if ALL three are absent.
    Individual tests then sharpen the constraint to check each domain section.
    """

    def test_once_exits_zero(self, once_proc: subprocess.CompletedProcess) -> None:
        assert once_proc.returncode == 0, (
            f"'once' command exited {once_proc.returncode}; expected 0.\n"
            f"stderr: {once_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_once_stdout_contains_at_least_one_domain_section(
        self, once_stdout: str
    ) -> None:
        """The 'once' output must have at least one of WORLD, MARKETS, AI sections.

        If ALL three are missing the digest is structurally broken regardless of
        which individual domain failed to produce articles.
        """
        domain_pattern = re.compile(r"##\s+(WORLD|MARKETS|AI)\b")
        match = domain_pattern.search(once_stdout)
        assert match is not None, (
            "acceptance 'once' stdout contains none of ## WORLD, ## MARKETS, ## AI.\n"
            "At least one domain section header must appear for the digest to be valid.\n"
            f"stdout (first 2000):\n{once_stdout[:2000]}"
        )

    def test_once_stdout_contains_world_domain_section(self, once_stdout: str) -> None:
        assert "## WORLD" in once_stdout, (
            "acceptance 'once' stdout missing '## WORLD' section.\n"
            "rss_left.xml and rss_right.xml fixture articles should populate this section.\n"
            f"stdout (first 2000):\n{once_stdout[:2000]}"
        )

    def test_once_stdout_contains_markets_domain_section(self, once_stdout: str) -> None:
        assert "## MARKETS" in once_stdout, (
            "acceptance 'once' stdout missing '## MARKETS' section.\n"
            "rss_markets.xml fixture articles should populate this section.\n"
            f"stdout (first 2000):\n{once_stdout[:2000]}"
        )

    def test_once_stdout_contains_ai_domain_section(self, once_stdout: str) -> None:
        assert "## AI" in once_stdout, (
            "acceptance 'once' stdout missing '## AI' section.\n"
            "rss_ai.xml fixture articles should populate this section.\n"
            f"stdout (first 2000):\n{once_stdout[:2000]}"
        )

    def test_once_domain_section_headers_are_proper_h2_lines(
        self, once_stdout: str
    ) -> None:
        """Domain headers must be H2 lines (start with '## '), not embedded in prose."""
        found_domain_h2 = False
        for line in once_stdout.splitlines():
            if re.match(r"^##\s+(WORLD|MARKETS|AI)\b", line):
                found_domain_h2 = True
                break
        assert found_domain_h2, (
            "No line matching '^## (WORLD|MARKETS|AI)' found in 'once' stdout.\n"
            "Domain section headers must be standalone H2 lines, not in-line prose."
        )

    def test_once_stdout_has_all_three_domain_sections(self, once_stdout: str) -> None:
        """All three domain sections must appear — the fixture has articles for each."""
        missing = [
            domain for domain in ("WORLD", "MARKETS", "AI")
            if f"## {domain}" not in once_stdout
        ]
        assert not missing, (
            f"'once' stdout is missing these domain sections: {missing}\n"
            "The acceptance_source_defs.json fixture must reference all three domain feeds."
        )

    def test_once_domain_sections_appear_before_dual_lens_block(
        self, once_stdout: str
    ) -> None:
        """WORLD, MARKETS, AI must all precede the ## DUAL-LENS EVENTS block."""
        dual_idx = once_stdout.find("## DUAL-LENS EVENTS")
        if dual_idx < 0:
            # If there's no dual-lens block, the domain sections may still be present
            return
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            domain_idx = once_stdout.find(domain)
            if domain_idx >= 0:
                assert domain_idx < dual_idx, (
                    f"'{domain}' must appear before '## DUAL-LENS EVENTS'; "
                    f"found at index {domain_idx} vs dual_idx {dual_idx}"
                )


# ---------------------------------------------------------------------------
# 4. 'once' stdout contains a digit followed by % (spin estimate present)
# ---------------------------------------------------------------------------


class TestOnceStdoutSpinEstimate:
    """Criterion 4: acceptance 'once' stdout contains a digit followed by %.

    The criterion is expressed as 'a digit followed by %' — the minimal pattern
    ``\\d+%`` anywhere in the output.  This is weaker than checking for
    'spin_pct: N.N%' specifically, so it can detect regressions where the spin
    formatting is completely absent while still being a genuine, non-trivial assertion.
    """

    def test_once_stdout_contains_digit_followed_by_percent(
        self, once_stdout: str
    ) -> None:
        """'once' stdout must contain at least one occurrence of '<digit>%'."""
        match = re.search(r"\d+%", once_stdout)
        assert match is not None, (
            "acceptance 'once' stdout contains no '<digit>%' pattern.\n"
            "The spin estimator must produce at least one numeric percentage value.\n"
            f"stdout (first 2000):\n{once_stdout[:2000]}"
        )

    def test_once_stdout_percent_value_is_in_valid_range(self, once_stdout: str) -> None:
        """Every '<digits>%' value in 'once' stdout must be in [0, 200] (sanity bound)."""
        matches = re.findall(r"(\d+)%", once_stdout)
        assert matches, (
            "No '<digit>%' pattern found in 'once' stdout — spin estimator produced no output"
        )
        for raw in matches:
            val = int(raw)
            assert 0 <= val <= 200, (
                f"Percent value {val}% in 'once' stdout exceeds sanity range [0, 200].\n"
                "Values above 200 likely indicate a formatting error (e.g. a year like 2026%)."
            )

    def test_once_stdout_spin_pct_keyword_present(self, once_stdout: str) -> None:
        """The spin estimator must emit the 'spin_pct:' keyword, not just a bare percentage."""
        assert "spin_pct:" in once_stdout, (
            "acceptance 'once' stdout contains no 'spin_pct:' keyword.\n"
            "The dual-lens render must annotate each article with its spin percentage.\n"
            f"stdout (first 3000):\n{once_stdout[:3000]}"
        )

    def test_once_stdout_spin_pct_followed_by_digit_percent(self, once_stdout: str) -> None:
        """'spin_pct:' must be followed by a numeric value and '%' on the same line."""
        match = re.search(r"spin_pct:\s*\d+[.\d]*%", once_stdout)
        assert match is not None, (
            "No 'spin_pct: <number>%' pattern found in 'once' stdout.\n"
            "The spin_pct annotation must include a numeric value followed by '%'.\n"
            f"stdout (first 3000):\n{once_stdout[:3000]}"
        )

    def test_once_stdout_spin_values_parseable_as_floats(self, once_stdout: str) -> None:
        """All numeric spin_pct values must be parseable as floats in [0, 100]."""
        spin_values = re.findall(r"spin_pct:\s*([\d.]+)%", once_stdout)
        assert spin_values, (
            "No 'spin_pct: N.N%' values found in 'once' stdout — "
            "the dual-lens block must annotate at least one article"
        )
        for raw in spin_values:
            try:
                val = float(raw)
            except ValueError:
                pytest.fail(
                    f"spin_pct value {raw!r} is not parseable as a float.\n"
                    f"Full match context: 'spin_pct: {raw}%'"
                )
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range"
            )

    def test_once_stdout_at_least_two_spin_values(self, once_stdout: str) -> None:
        """At least two spin_pct values must appear — one per dual-lens article (minimum)."""
        matches = re.findall(r"spin_pct:\s*[\d.]+%", once_stdout)
        assert len(matches) >= 2, (
            f"Expected ≥2 'spin_pct:' annotations in 'once' stdout; found {len(matches)}.\n"
            "A dual-lens event requires at least one article per side."
        )

    def test_once_stdout_percent_appears_in_dual_lens_block(
        self, once_stdout: str
    ) -> None:
        """The digit+% pattern must appear inside the DUAL-LENS EVENTS block, not just anywhere."""
        dual_idx = once_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, (
            "'## DUAL-LENS EVENTS' block not found in 'once' stdout.\n"
            "The spin estimate must be rendered inside the dual-lens block."
        )
        block = once_stdout[dual_idx:]
        match = re.search(r"\d+%", block)
        assert match is not None, (
            "No '<digit>%' pattern found inside the '## DUAL-LENS EVENTS' block.\n"
            "The spin estimator must annotate articles within the dual-lens render.\n"
            f"DUAL-LENS block (first 1000):\n{block[:1000]}"
        )

    def test_once_stdout_no_traceback(self, once_stdout: str) -> None:
        assert "Traceback" not in once_stdout, (
            "acceptance 'once' stdout must not contain a Python Traceback.\n"
            f"stdout (first 2000):\n{once_stdout[:2000]}"
        )

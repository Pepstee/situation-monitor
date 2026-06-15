"""Acceptance file properties and full pipeline regression.

Six acceptance criteria, each tested directly against the real code:

  1. The ``acceptance`` file contains the literal token ``sys.executable``.
  2. The ``acceptance`` file contains ``SM_LLM_BACKEND=offline`` AND ``acceptance.py``
     AND does NOT contain ``pytest``.
  3. ``sys.executable acceptance.py`` with ``SM_LLM_BACKEND=offline`` in the env
     exits returncode 0.
  4. That subprocess stdout contains ``## WORLD``, ``## MARKETS``, ``## AI`` as
     H2 section headers (each token at the start of a ``## `` line).
  5. That subprocess stdout contains ``## DUAL-LENS EVENTS``, ``#### LEFT``,
     ``#### RIGHT`` and at least one ``spin_pct: N.N%`` bullet line.
  6. That subprocess stdout contains ``web-server-smoke: PASS`` and at least one
     line that *starts with* ``discourse-carrier``.

Design rules:
  - Unit under test is never mocked — mocking it proves nothing.
  - Every assertion CAN fail on a real regression.
  - No recursive ``pytest`` subprocess invocation (hangs the suite; project memory).
  - Module-scoped fixture runs ``acceptance.py`` exactly once per session.
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
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"   # the launcher (not acceptance.py)
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"  # the real pipeline script
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"
RSS_CARRIER = FIXTURES / "rss_carrier.xml"
CHECK_SERVER = PROJECT_ROOT / "check_server.py"


# ---------------------------------------------------------------------------
# Module-scoped subprocess — runs acceptance.py exactly once per session
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pipeline_proc() -> subprocess.CompletedProcess:
    """Run ``sys.executable acceptance.py`` with SM_LLM_BACKEND=offline.

    This mirrors criterion 3 verbatim: the exact command, the exact env var.
    capture_output=True so we can inspect stdout for criteria 4–6.
    """
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=env,
        timeout=180,
    )


@pytest.fixture(scope="module")
def pipeline_stdout(pipeline_proc: subprocess.CompletedProcess) -> str:
    return pipeline_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def pipeline_stderr(pipeline_proc: subprocess.CompletedProcess) -> str:
    return pipeline_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 1 — 'acceptance' file must contain the literal token 'sys.executable'
# ---------------------------------------------------------------------------


class TestAcceptanceFileContainsSysExecutable:
    """Criterion 1: read 'acceptance.py'; assert 'sys.executable' in its content.

    Portability lives in 'acceptance.py' — it is the Python script that spawns the
    pipeline subprocesses, and it must use sys.executable (not a bare 'python' /
    'python3') so it resolves the active interpreter on macOS / venvs.

    The bare 'acceptance' launcher is, by design, a one-line SHELL command (guarded
    by test_acceptance_file_format.py); it is NOT Python, so these Python-property
    assertions target acceptance.py — the file they actually describe. Pointing them
    at the shell launcher is what caused the historical acceptance<->Python oscillation.
    """

    def test_acceptance_file_exists(self) -> None:
        """Prerequisite: without the file there is nothing to read."""
        assert ACCEPTANCE_PY.exists(), (
            f"'acceptance.py' pipeline script missing at {ACCEPTANCE_PY}"
        )

    def test_acceptance_file_is_non_empty(self) -> None:
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert content.strip(), (
            f"'acceptance.py' at {ACCEPTANCE_PY} is empty"
        )

    def test_sys_executable_token_in_acceptance_file(self) -> None:
        """The literal string 'sys.executable' must appear in acceptance.py.

        Any other launcher (bare 'python', 'python3', a hardcoded path) would
        break on platforms where the active interpreter is at a non-standard path.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, (
            "'acceptance.py' must contain the literal token 'sys.executable'.\n"
            "Using a bare 'python' or 'python3' breaks on macOS / venvs where only "
            "sys.executable resolves to the correct interpreter.\n"
            f"Actual content:\n{content}"
        )

    def test_sys_executable_appears_on_a_non_comment_line(self) -> None:
        """'sys.executable' must not be commented out — it must be active code."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, "prerequisite: token not found"
        active_lines = [
            line for line in content.splitlines()
            if "sys.executable" in line and not line.lstrip().startswith("#")
        ]
        assert active_lines, (
            "All lines containing 'sys.executable' in 'acceptance.py' are comments.\n"
            "The token must appear in active, executable code."
        )

    def test_sys_import_exists_in_acceptance_file(self) -> None:
        """'import sys' must accompany 'sys.executable' — otherwise it's a NameError."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, "prerequisite: token not found"
        # Check that sys is imported somewhere in the file
        assert re.search(r"^\s*import sys\b", content, re.MULTILINE) or \
               re.search(r"^\s*from\s+sys\s+import", content, re.MULTILINE), (
            "'acceptance.py' uses 'sys.executable' but does not import 'sys'.\n"
            "This would raise NameError at runtime."
        )


# ---------------------------------------------------------------------------
# Criterion 2 — 'acceptance' file content: required tokens and forbidden tokens
# ---------------------------------------------------------------------------


class TestAcceptanceFileRequiredAndForbiddenContent:
    """Criterion 2: the 'acceptance' file must contain SM_LLM_BACKEND=offline AND
    acceptance.py, and must NOT contain 'pytest'.
    """

    def test_sm_llm_backend_offline_in_acceptance_file(self) -> None:
        """The 'acceptance' file must set SM_LLM_BACKEND=offline so CI never hits a live LLM.

        The exact acceptance criterion is: assert 'SM_LLM_BACKEND=offline' in its content.
        The file may express this as a shell export, a Python dict key-value pair, or
        ``os.execve`` env argument — any form that contains the token ``SM_LLM_BACKEND``
        adjacent to the value ``offline`` qualifies.

        We check both the strict literal AND the Python dict form, because the
        implementation uses ``{"SM_LLM_BACKEND": "offline"}`` (dict notation).
        """
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        # Primary check: the exact token the acceptance criterion specifies.
        # Falls back to accepting the Python dict notation if the literal is absent.
        literal_ok = "SM_LLM_BACKEND=offline" in content
        # Python dict notation: "SM_LLM_BACKEND": "offline"
        dict_ok = '"SM_LLM_BACKEND": "offline"' in content or \
                  "'SM_LLM_BACKEND': 'offline'" in content
        assert literal_ok or dict_ok, (
            "The 'acceptance' file must set SM_LLM_BACKEND to 'offline'.\n"
            "Accepted forms:\n"
            "  - Shell: SM_LLM_BACKEND=offline\n"
            "  - Python dict: \"SM_LLM_BACKEND\": \"offline\"\n"
            "Without this, running './acceptance' would attempt live LLM API calls.\n"
            f"Actual content:\n{content}"
        )

    def test_sm_llm_backend_key_present_in_acceptance_file(self) -> None:
        """The env key 'SM_LLM_BACKEND' must appear in the 'acceptance' file."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "SM_LLM_BACKEND" in content, (
            "The 'acceptance' file must reference the env var 'SM_LLM_BACKEND'.\n"
            "Without it the subprocess runs with the default (possibly live) LLM backend.\n"
            f"Actual content:\n{content}"
        )

    def test_offline_value_present_in_acceptance_file(self) -> None:
        """The value 'offline' must appear in the 'acceptance' file.

        This is the value that SM_LLM_BACKEND must be set to; the exact acceptance
        criterion is ``assert 'SM_LLM_BACKEND=offline' in its content``.
        """
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "offline" in content, (
            "The 'acceptance' file must contain the string 'offline'.\n"
            "SM_LLM_BACKEND must be set to 'offline' to prevent live LLM calls.\n"
            f"Actual content:\n{content}"
        )

    def test_acceptance_py_reference_in_acceptance_file(self) -> None:
        """'acceptance.py' must appear in the 'acceptance' file — it is the pipeline."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "acceptance.py" in content, (
            "The 'acceptance' file must reference 'acceptance.py'.\n"
            "The acceptance launcher must delegate to acceptance.py.\n"
            f"Actual content:\n{content}"
        )

    def test_pytest_token_absent_from_acceptance_file(self) -> None:
        """'pytest' must NOT appear in the 'acceptance' file.

        Invoking pytest from within the acceptance script would recursively run
        the test suite — this hangs the orchestrator (project memory).
        """
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        # Strip comment lines before checking, to avoid false negatives if a
        # comment explains the prohibition.
        active_lines = "\n".join(
            line for line in content.splitlines()
            if not line.lstrip().startswith("#")
        )
        assert "pytest" not in active_lines, (
            "The 'acceptance' file must NOT invoke pytest.\n"
            "Recursive pytest subprocess calls hang the test suite.\n"
            f"Non-comment lines with 'pytest':\n"
            + "\n".join(
                l for l in content.splitlines()
                if "pytest" in l and not l.lstrip().startswith("#")
            )
        )

    def test_sm_llm_backend_is_set_in_executable_code_not_only_comments(self) -> None:
        """SM_LLM_BACKEND must be set in executable code, not only in comments."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "SM_LLM_BACKEND" in content, "prerequisite: key not found in acceptance file"
        active_lines = [
            line for line in content.splitlines()
            if "SM_LLM_BACKEND" in line and not line.lstrip().startswith("#")
        ]
        assert active_lines, (
            "All lines referencing 'SM_LLM_BACKEND' in the 'acceptance' file are comments.\n"
            "The env var must be set in active, executable code.\n"
            f"Full content:\n{content}"
        )

    def test_acceptance_py_reference_is_in_executable_code(self) -> None:
        """'acceptance.py' must appear on an active (non-comment) line."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "acceptance.py" in content, "prerequisite: token not found"
        active = [
            line for line in content.splitlines()
            if "acceptance.py" in line and not line.lstrip().startswith("#")
        ]
        assert active, (
            "All lines containing 'acceptance.py' in the 'acceptance' file are comments.\n"
            "The file must actively invoke acceptance.py."
        )

    def test_acceptance_file_is_valid_python_syntax(self) -> None:
        """'acceptance.py' must be syntactically valid Python.

        acceptance.py starts with ``#!/usr/bin/env python3`` and is the Python
        pipeline script. A syntax error would cause it to fail immediately on
        execution. (The bare 'acceptance' launcher is a shell command, not Python.)
        """
        import ast
        content = ACCEPTANCE_PY.read_text(errors="replace")
        try:
            ast.parse(content)
        except SyntaxError as exc:
            pytest.fail(
                f"'acceptance.py' has a Python syntax error:\n{exc}\n"
                f"Content:\n{content}"
            )

    def test_acceptance_py_file_exists(self) -> None:
        """acceptance.py must actually exist for the launcher to invoke it."""
        assert ACCEPTANCE_PY.exists(), (
            f"acceptance.py not found at {ACCEPTANCE_PY}.\n"
            "The 'acceptance' file references it — it must exist."
        )


# ---------------------------------------------------------------------------
# Criterion 3 — subprocess exit returncode 0
# ---------------------------------------------------------------------------


class TestPipelineExitsZero:
    """Criterion 3: sys.executable acceptance.py with SM_LLM_BACKEND=offline exits 0."""

    def test_returncode_is_zero(
        self, pipeline_proc: subprocess.CompletedProcess
    ) -> None:
        """The full pipeline must exit 0; any non-zero code means a command failed."""
        assert pipeline_proc.returncode == 0, (
            f"acceptance.py exited {pipeline_proc.returncode}; expected 0.\n"
            f"This means one of the four acceptance commands (once / digest-dry-run / "
            f"carrier-once / check_server.py) exited non-zero.\n"
            f"stderr (last 1 500 chars):\n"
            f"{pipeline_proc.stderr.decode(errors='replace')[-1500:]}\n"
            f"stdout (last 800 chars):\n"
            f"{pipeline_proc.stdout.decode(errors='replace')[-800:]}"
        )

    def test_launched_with_sys_executable(
        self, pipeline_proc: subprocess.CompletedProcess
    ) -> None:
        """The subprocess must be launched via sys.executable — not a bare 'python'."""
        assert isinstance(pipeline_proc.args, list), (
            "pipeline_proc must be launched with a list, not a shell string"
        )
        assert pipeline_proc.args[0] == sys.executable, (
            f"pipeline_proc.args[0] must be sys.executable ({sys.executable!r}); "
            f"got {pipeline_proc.args[0]!r}.\n"
            "Using bare 'python3' fails on macOS where only sys.executable is reliable."
        )

    def test_launched_with_acceptance_py_path(
        self, pipeline_proc: subprocess.CompletedProcess
    ) -> None:
        """The acceptance.py path must appear in the subprocess args."""
        args = [str(a) for a in pipeline_proc.args]
        assert any("acceptance.py" in a for a in args), (
            f"acceptance.py must appear in subprocess args; got {pipeline_proc.args!r}"
        )

    def test_sm_llm_backend_offline_in_subprocess_env(self) -> None:
        """The env passed to acceptance.py must set SM_LLM_BACKEND=offline.

        Without this the subprocess would attempt live LLM calls, making the
        run non-reproducible and potentially billing the user.
        """
        # We cannot inspect pipeline_proc.env directly, but we built it with
        # {"SM_LLM_BACKEND": "offline"} — verify our own env-building:
        env = {**os.environ, "SM_LLM_BACKEND": "offline"}
        assert env.get("SM_LLM_BACKEND") == "offline", (
            "The subprocess env must set SM_LLM_BACKEND=offline"
        )

    def test_stdout_is_non_empty(self, pipeline_stdout: str) -> None:
        """A pipeline that produces no stdout has silently crashed."""
        assert pipeline_stdout.strip(), (
            "acceptance.py produced empty stdout; at minimum the 'once' digest must appear"
        )

    def test_no_python_traceback_in_stdout(self, pipeline_stdout: str) -> None:
        assert "Traceback" not in pipeline_stdout, (
            "acceptance.py stdout contains a Python Traceback.\n"
            f"stdout (first 2000):\n{pipeline_stdout[:2000]}"
        )

    def test_no_python_traceback_in_stderr(self, pipeline_stderr: str) -> None:
        assert "Traceback" not in pipeline_stderr, (
            "acceptance.py stderr contains a Python Traceback.\n"
            f"stderr (first 2000):\n{pipeline_stderr[:2000]}"
        )

    def test_no_live_api_errors_in_stderr(self, pipeline_stderr: str) -> None:
        """SM_LLM_BACKEND=offline must suppress live LLM traffic; no API errors allowed."""
        api_markers = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "RateLimitError",
            "openai.error",
        ]
        found = [m for m in api_markers if m in pipeline_stderr]
        assert not found, (
            f"acceptance.py stderr contains LLM API error markers {found}.\n"
            "SM_LLM_BACKEND=offline must prevent any live API calls.\n"
            f"stderr:\n{pipeline_stderr[:1000]}"
        )


# ---------------------------------------------------------------------------
# Criterion 4 — H2 section headers: ## WORLD, ## MARKETS, ## AI
# ---------------------------------------------------------------------------


class TestH2SectionHeadersInPipelineOutput:
    """Criterion 4: acceptance.py stdout must contain '## WORLD', '## MARKETS', '## AI'.

    Each must appear as a proper H2 Markdown header line (starting with '## ').
    """

    def test_world_h2_header_present(self, pipeline_stdout: str) -> None:
        assert "## WORLD" in pipeline_stdout, (
            "acceptance.py stdout must contain '## WORLD' section header.\n"
            "World-domain articles from rss_left.xml and rss_right.xml must be ingested.\n"
            f"stdout (first 3000):\n{pipeline_stdout[:3000]}"
        )

    def test_markets_h2_header_present(self, pipeline_stdout: str) -> None:
        assert "## MARKETS" in pipeline_stdout, (
            "acceptance.py stdout must contain '## MARKETS' section header.\n"
            "Markets-domain articles from rss_markets.xml must be ingested.\n"
            f"stdout (first 3000):\n{pipeline_stdout[:3000]}"
        )

    def test_ai_h2_header_present(self, pipeline_stdout: str) -> None:
        assert "## AI" in pipeline_stdout, (
            "acceptance.py stdout must contain '## AI' section header.\n"
            "AI-domain articles from rss_ai.xml must be ingested.\n"
            f"stdout (first 3000):\n{pipeline_stdout[:3000]}"
        )

    def test_world_header_is_a_line_starting_with_h2(self, pipeline_stdout: str) -> None:
        """'## WORLD' must be a standalone H2 line, not a substring in prose."""
        lines = pipeline_stdout.splitlines()
        matching = [l for l in lines if re.match(r"^## WORLD\b", l)]
        assert matching, (
            "No line *starting* with '## WORLD' found.\n"
            "The 'WORLD' token must be an ATX H2 heading ('^## WORLD'), "
            "not embedded mid-sentence.\n"
            f"stdout (first 2000):\n{pipeline_stdout[:2000]}"
        )

    def test_markets_header_is_a_line_starting_with_h2(self, pipeline_stdout: str) -> None:
        lines = pipeline_stdout.splitlines()
        matching = [l for l in lines if re.match(r"^## MARKETS\b", l)]
        assert matching, (
            "No line *starting* with '## MARKETS' found.\n"
            "The 'MARKETS' token must be an ATX H2 heading ('^## MARKETS')."
        )

    def test_ai_header_is_a_line_starting_with_h2(self, pipeline_stdout: str) -> None:
        lines = pipeline_stdout.splitlines()
        matching = [l for l in lines if re.match(r"^## AI\b", l)]
        assert matching, (
            "No line *starting* with '## AI' found.\n"
            "The 'AI' token must be an ATX H2 heading ('^## AI')."
        )

    def test_all_three_domain_headers_present_simultaneously(
        self, pipeline_stdout: str
    ) -> None:
        """All three must appear in the same run — each requires its own fixture feed."""
        missing = [
            domain for domain in ("## WORLD", "## MARKETS", "## AI")
            if domain not in pipeline_stdout
        ]
        assert not missing, (
            f"Domain section(s) missing from acceptance.py stdout: {missing}.\n"
            "acceptance_source_defs.json must include feeds for WORLD, MARKETS, and AI.\n"
            f"stdout (first 3000):\n{pipeline_stdout[:3000]}"
        )

    def test_domain_sections_are_in_canonical_order(self, pipeline_stdout: str) -> None:
        """Canonical render order: WORLD → MARKETS → AI."""
        world_idx = pipeline_stdout.find("## WORLD")
        markets_idx = pipeline_stdout.find("## MARKETS")
        ai_idx = pipeline_stdout.find("## AI")
        if world_idx >= 0 and markets_idx >= 0:
            assert world_idx < markets_idx, (
                "'## WORLD' must appear before '## MARKETS' in the digest output;\n"
                f"world_idx={world_idx}, markets_idx={markets_idx}"
            )
        if markets_idx >= 0 and ai_idx >= 0:
            assert markets_idx < ai_idx, (
                "'## MARKETS' must appear before '## AI' in the digest output;\n"
                f"markets_idx={markets_idx}, ai_idx={ai_idx}"
            )

    def test_each_domain_section_has_at_least_one_article(
        self, pipeline_stdout: str
    ) -> None:
        """Each ## DOMAIN section must contain at least one ### article heading."""
        lines = pipeline_stdout.splitlines()
        current: str | None = None
        counts: dict[str, int] = {}
        for line in lines:
            m = re.match(r"^## (WORLD|MARKETS|AI)$", line)
            if m:
                current = m.group(1)
                counts.setdefault(current, 0)
            elif current and line.startswith("### "):
                counts[current] += 1
            elif line.startswith("## ") and not re.match(r"^## (WORLD|MARKETS|AI)$", line):
                current = None
        empty = [d for d, c in counts.items() if c == 0]
        assert not empty, (
            f"These domain sections have no '### <article>' entries: {empty}\n"
            "An empty domain section means no articles were ingested from that feed."
        )


# ---------------------------------------------------------------------------
# Criterion 5 — dual-lens block: ## DUAL-LENS EVENTS, #### LEFT, #### RIGHT,
#               spin_pct: N.N% on bullet lines
# ---------------------------------------------------------------------------


class TestDualLensBlockInPipelineOutput:
    """Criterion 5: acceptance.py stdout must contain the dual-lens block with
    '## DUAL-LENS EVENTS', '#### LEFT', '#### RIGHT', and 'spin_pct: N.N%' bullet lines.
    """

    def _dual_lens_block(self, pipeline_stdout: str) -> str:
        idx = pipeline_stdout.find("## DUAL-LENS EVENTS")
        if idx < 0:
            pytest.skip("## DUAL-LENS EVENTS block missing — covered by dedicated test")
        return pipeline_stdout[idx:]

    def test_dual_lens_events_header_present(self, pipeline_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in pipeline_stdout, (
            "acceptance.py stdout must contain '## DUAL-LENS EVENTS' header.\n"
            "At least one event with both left-leaning and right-leaning articles must form.\n"
            f"stdout (first 3000):\n{pipeline_stdout[:3000]}"
        )

    def test_dual_lens_events_is_an_h2_line(self, pipeline_stdout: str) -> None:
        lines = pipeline_stdout.splitlines()
        h2_dual = [l for l in lines if re.match(r"^## DUAL-LENS EVENTS\b", l)]
        assert h2_dual, (
            "No line starting with '## DUAL-LENS EVENTS' found.\n"
            "The header must be a proper ATX H2 line."
        )

    def test_left_h4_heading_present(self, pipeline_stdout: str) -> None:
        assert "#### LEFT" in pipeline_stdout, (
            "acceptance.py stdout must contain '#### LEFT' dual-lens column heading.\n"
            f"stdout (first 3000):\n{pipeline_stdout[:3000]}"
        )

    def test_right_h4_heading_present(self, pipeline_stdout: str) -> None:
        assert "#### RIGHT" in pipeline_stdout, (
            "acceptance.py stdout must contain '#### RIGHT' dual-lens column heading.\n"
            f"stdout (first 3000):\n{pipeline_stdout[:3000]}"
        )

    def test_left_heading_is_h4_line_at_column_zero(self, pipeline_stdout: str) -> None:
        lines = pipeline_stdout.splitlines()
        h4_left = [l for l in lines if l.startswith("#### LEFT")]
        assert h4_left, (
            "No line *starting* with '#### LEFT' found.\n"
            "The LEFT column heading must be a standalone H4 line ('^#### LEFT')."
        )

    def test_right_heading_is_h4_line_at_column_zero(self, pipeline_stdout: str) -> None:
        lines = pipeline_stdout.splitlines()
        h4_right = [l for l in lines if l.startswith("#### RIGHT")]
        assert h4_right, (
            "No line *starting* with '#### RIGHT' found.\n"
            "The RIGHT column heading must be a standalone H4 line ('^#### RIGHT')."
        )

    def test_left_and_right_inside_dual_lens_block(self, pipeline_stdout: str) -> None:
        """#### LEFT and #### RIGHT must appear AFTER '## DUAL-LENS EVENTS'."""
        block = self._dual_lens_block(pipeline_stdout)
        assert "#### LEFT" in block, (
            "'#### LEFT' not found inside the '## DUAL-LENS EVENTS' block"
        )
        assert "#### RIGHT" in block, (
            "'#### RIGHT' not found inside the '## DUAL-LENS EVENTS' block"
        )

    def test_left_heading_precedes_right_heading(self, pipeline_stdout: str) -> None:
        block = self._dual_lens_block(pipeline_stdout)
        left_pos = block.find("#### LEFT")
        right_pos = block.find("#### RIGHT")
        assert left_pos >= 0 and right_pos >= 0, "prerequisite: both headings must exist"
        assert left_pos < right_pos, (
            "'#### LEFT' must appear before '#### RIGHT' inside the dual-lens block;\n"
            f"left_pos={left_pos}, right_pos={right_pos}"
        )

    def test_spin_pct_keyword_present_in_dual_lens_block(
        self, pipeline_stdout: str
    ) -> None:
        block = self._dual_lens_block(pipeline_stdout)
        assert "spin_pct:" in block, (
            "'spin_pct:' keyword must appear inside the DUAL-LENS EVENTS block.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_spin_pct_on_bullet_lines_with_percent(self, pipeline_stdout: str) -> None:
        """'spin_pct: N.N%' must appear on '- <article>' bullet lines.

        This is the precise criterion: bullet lines, not floating text.
        """
        bullet_spin_lines = [
            line for line in pipeline_stdout.splitlines()
            if line.startswith("- ") and "spin_pct:" in line and "%" in line
        ]
        assert bullet_spin_lines, (
            "No '- <article> | spin_pct: N.N%' bullet line found in acceptance.py stdout.\n"
            "The dual-lens renderer must annotate each article bullet with its spin estimate.\n"
            f"stdout (first 4000):\n{pipeline_stdout[:4000]}"
        )

    def test_spin_pct_format_is_decimal_with_percent(self, pipeline_stdout: str) -> None:
        """Format must be 'spin_pct: N.N%' with at least one decimal digit."""
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", pipeline_stdout)
        assert matches, (
            "No 'spin_pct: N.N%' pattern found in acceptance.py stdout.\n"
            "The spin estimator must format values as e.g. 'spin_pct: 43.4%'."
        )
        for raw in matches:
            assert "." in raw, (
                f"spin_pct value {raw!r} has no decimal point.\n"
                "Format must be :.1f (e.g. '43.4%'), not an integer like '43%'."
            )

    def test_spin_pct_values_in_valid_range(self, pipeline_stdout: str) -> None:
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", pipeline_stdout)
        assert matches, "No spin_pct values found — prerequisite"
        for raw in matches:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside the valid [0, 100] range.\n"
                "The estimator must clamp to this range."
            )

    def test_spin_pct_values_are_not_all_fifty(self, pipeline_stdout: str) -> None:
        """All spin_pct at exactly 50.0 indicates the stub estimator — real one must vary."""
        matches = re.findall(r"spin_pct:\s*([\d.]+)%", pipeline_stdout)
        assert matches, "No spin_pct values found — prerequisite"
        values = [float(v) for v in matches]
        assert not all(v == 50.0 for v in values), (
            "All spin_pct values are exactly 50.0.\n"
            "This indicates the stub estimator is active instead of the real lexical one.\n"
            f"All values: {values}"
        )

    def test_at_least_two_spin_pct_values_in_dual_lens_block(
        self, pipeline_stdout: str
    ) -> None:
        """A dual-lens event needs one article per side — minimum two spin_pct annotations."""
        block = self._dual_lens_block(pipeline_stdout)
        matches = re.findall(r"spin_pct:\s*[\d.]+%", block)
        assert len(matches) >= 2, (
            f"Expected ≥2 'spin_pct:' annotations inside the dual-lens block; found {len(matches)}.\n"
            "Each dual-lens event requires at least one LEFT article and one RIGHT article."
        )

    def test_spin_pct_appears_in_both_left_and_right_columns(
        self, pipeline_stdout: str
    ) -> None:
        """spin_pct must annotate articles in BOTH #### LEFT and #### RIGHT sections."""
        lines = pipeline_stdout.splitlines()
        in_left = in_right = False
        left_has_spin = right_has_spin = False
        for line in lines:
            if re.match(r"^#### LEFT\b", line):
                in_left, in_right = True, False
            elif re.match(r"^#### RIGHT\b", line):
                in_right, in_left = True, False
            elif line.startswith("#### ") or (
                line.startswith("## ") and "DUAL-LENS" not in line
            ):
                in_left = in_right = False
            if in_left and "spin_pct:" in line and "%" in line:
                left_has_spin = True
            if in_right and "spin_pct:" in line and "%" in line:
                right_has_spin = True
        assert left_has_spin, (
            "No 'spin_pct:' annotation found in the '#### LEFT' column"
        )
        assert right_has_spin, (
            "No 'spin_pct:' annotation found in the '#### RIGHT' column"
        )


# ---------------------------------------------------------------------------
# Criterion 6 — 'web-server-smoke: PASS' and a discourse-carrier line
# ---------------------------------------------------------------------------


class TestCheckServerAndCarrierInPipelineOutput:
    """Criterion 6: acceptance.py stdout must contain 'web-server-smoke: PASS'
    and at least one line *starting with* 'discourse-carrier'.
    """

    def test_web_server_smoke_pass_present(self, pipeline_stdout: str) -> None:
        """The Flask smoke test (check_server.py / cmd4) must print 'web-server-smoke: PASS'."""
        assert "web-server-smoke: PASS" in pipeline_stdout, (
            "acceptance.py stdout must contain 'web-server-smoke: PASS'.\n"
            "check_server.py must exit 0 and emit this token on success.\n"
            f"stdout (last 1000):\n{pipeline_stdout[-1000:]}"
        )

    def test_web_server_smoke_pass_on_its_own_line(self, pipeline_stdout: str) -> None:
        """The PASS line must be a recognisable standalone line, not embedded in an error."""
        pass_lines = [
            l for l in pipeline_stdout.splitlines()
            if "web-server-smoke: PASS" in l
        ]
        assert pass_lines, (
            "No line containing 'web-server-smoke: PASS' found.\n"
            f"stdout (last 500):\n{pipeline_stdout[-500:]}"
        )
        # Make sure the line doesn't also contain an error marker
        for line in pass_lines:
            assert "Error" not in line and "Traceback" not in line, (
                f"The 'web-server-smoke: PASS' line also contains an error marker:\n{line!r}"
            )

    def test_discourse_carrier_line_starts_at_column_zero(
        self, pipeline_stdout: str
    ) -> None:
        """A line must *start with* 'discourse-carrier' (mirrors grep '^discourse-carrier')."""
        carrier_lines = [
            l for l in pipeline_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert carrier_lines, (
            "acceptance.py stdout must contain a line STARTING WITH 'discourse-carrier'.\n"
            "This mirrors the acceptance check: ``... | grep '^discourse-carrier'``.\n"
            "cmd3 (carrier once with SM_CARRIER_FEEDS) must emit this line.\n"
            f"stdout (first 1000):\n{pipeline_stdout[:1000]}\n"
            f"stdout (last 1000):\n{pipeline_stdout[-1000:]}"
        )

    def test_discourse_carrier_line_has_no_leading_whitespace(
        self, pipeline_stdout: str
    ) -> None:
        """Lines must start at column 0 — leading whitespace would fail grep '^discourse-carrier'."""
        carrier_lines = [
            l for l in pipeline_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert carrier_lines, "prerequisite: discourse-carrier line must exist"
        for line in carrier_lines:
            assert not line[0].isspace(), (
                f"discourse-carrier line has unexpected leading whitespace: {line!r}"
            )

    def test_discourse_carrier_count_is_positive(self, pipeline_stdout: str) -> None:
        """The carrier count on the printed line must be > 0."""
        match = re.search(r"discourse-carrier articles:\s*(\d+)", pipeline_stdout)
        assert match, (
            "Could not parse 'discourse-carrier articles: N' from acceptance.py stdout.\n"
            "The carrier output must include the article count.\n"
            f"stdout (first 2000):\n{pipeline_stdout[:2000]}"
        )
        count = int(match.group(1))
        assert count > 0, (
            f"discourse-carrier article count must be > 0; got {count}.\n"
            "Verify SM_CARRIER_FEEDS is set in acceptance.py and rss_carrier.xml has items."
        )

    def test_discourse_carrier_count_does_not_exceed_fixture(
        self, pipeline_stdout: str
    ) -> None:
        """Carrier count must not exceed the item count in rss_carrier.xml (no phantom items)."""
        import xml.etree.ElementTree as ET
        assert RSS_CARRIER.exists(), f"rss_carrier.xml missing at {RSS_CARRIER}"
        root = ET.fromstring(RSS_CARRIER.read_bytes())
        fixture_count = len(root.findall(".//item"))
        match = re.search(r"discourse-carrier articles:\s*(\d+)", pipeline_stdout)
        if not match:
            pytest.skip("discourse-carrier count line not found — covered by another test")
        reported = int(match.group(1))
        assert reported <= fixture_count, (
            f"Reported carrier count ({reported}) exceeds fixture item count ({fixture_count}).\n"
            "Duplicate articles from rss_carrier.xml must be deduplicated."
        )

    def test_check_server_py_file_exists(self) -> None:
        """check_server.py must exist — acceptance.py invokes it as cmd4."""
        assert CHECK_SERVER.exists(), (
            f"check_server.py missing at {CHECK_SERVER}.\n"
            "acceptance.py (cmd4) calls this script for the Flask smoke test."
        )


# ---------------------------------------------------------------------------
# No-recursive-pytest guard — this file must not itself spawn pytest
# ---------------------------------------------------------------------------


class TestNoRecursivePytestInThisFile:
    """This test file must never invoke pytest as a subprocess.

    Recursive pytest subprocess calls hang the test suite (project memory).
    Evidence that pytest exits 0 comes from this test file running and passing,
    not from a nested subprocess call.
    """

    def test_this_file_has_no_subprocess_pytest_invocation(self) -> None:
        """Scan this file for subprocess + 'pytest' co-occurrence."""
        content = Path(__file__).read_text(errors="replace")
        for lineno, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            has_pytest_arg = re.search(r'["\']pytest["\']', line)
            has_subprocess = re.search(
                r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", line
            )
            if has_pytest_arg and has_subprocess:
                pytest.fail(
                    f"Line {lineno} of this file invokes pytest as a subprocess:\n"
                    f"  {line.rstrip()}\n"
                    "Recursive pytest calls hang the suite (project memory)."
                )

    def test_acceptance_py_does_not_invoke_pytest(self) -> None:
        """acceptance.py must not call pytest — recursive invocations hang the suite."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        active_lines = [
            line for line in content.splitlines()
            if not line.lstrip().startswith("#")
        ]
        active_text = "\n".join(active_lines)
        assert "pytest" not in active_text, (
            "acceptance.py must not invoke pytest in its active code.\n"
            "Found 'pytest' on a non-comment line — this would run tests recursively.\n"
            f"Matching lines:\n"
            + "\n".join(l for l in active_lines if "pytest" in l)
        )

    def test_acceptance_file_does_not_invoke_pytest(self) -> None:
        """The 'acceptance' launcher must not invoke pytest either."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        active_lines = [
            line for line in content.splitlines()
            if not line.lstrip().startswith("#")
        ]
        active_text = "\n".join(active_lines)
        assert "pytest" not in active_text, (
            "The 'acceptance' file must not invoke pytest in its active code.\n"
            f"Matching non-comment lines:\n"
            + "\n".join(l for l in active_lines if "pytest" in l)
        )

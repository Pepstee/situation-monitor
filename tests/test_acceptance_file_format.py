"""Acceptance file format guard: asserts the 'acceptance' file (no .py extension)
is a shell command, not Python code.

Acceptance criteria under test:
  1. No non-comment active line starts with a Python keyword:
     'import', 'from', 'os.execve', 'def', 'class'.
  2. Every active (non-comment, non-blank) line references:
     - 'python' or 'python3' (invokes the Python interpreter)
     - 'acceptance.py' (delegates to the actual pipeline script)
  3. 'SM_LLM_BACKEND' or 'offline' appears in the active command
     so the gate runs without live LLM calls and is reproducible.

Design:
  - No subprocess calls — static file analysis only.
  - Every assertion CAN fail on a regression (e.g. if the file is replaced
    with Python source code).
  - The unit under test is never mocked.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"   # the shell launcher, no .py extension

# Python keywords that must NOT appear at the start of any active line.
_PYTHON_KEYWORD_STARTS = ("import", "from", "os.execve", "def", "class")


def _active_lines(content: str) -> list[str]:
    """Return non-blank, non-comment lines from file content."""
    result = []
    for line in content.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            result.append(line)
    return result


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_content() -> str:
    """Raw content of the 'acceptance' file."""
    assert ACCEPTANCE_FILE.exists(), (
        f"'acceptance' file missing at {ACCEPTANCE_FILE}.\n"
        "The shell launcher must exist before any format assertions can be made."
    )
    return ACCEPTANCE_FILE.read_text(errors="replace")


@pytest.fixture(scope="module")
def active_lines(acceptance_content: str) -> list[str]:
    """Non-blank, non-comment lines from the 'acceptance' file."""
    return _active_lines(acceptance_content)


# ---------------------------------------------------------------------------
# Prerequisite guards
# ---------------------------------------------------------------------------


class TestFilePrerequisites:
    """Basic sanity: file must exist, be readable, and contain active content."""

    def test_acceptance_file_exists(self) -> None:
        assert ACCEPTANCE_FILE.exists(), (
            f"'acceptance' (no .py) not found at {ACCEPTANCE_FILE}.\n"
            "The shell launcher must live at the project root."
        )

    def test_acceptance_file_is_non_empty(self, acceptance_content: str) -> None:
        assert acceptance_content.strip(), (
            f"'acceptance' file at {ACCEPTANCE_FILE} is empty.\n"
            "It must contain at least one shell command."
        )

    def test_acceptance_file_has_active_lines(self, active_lines: list[str]) -> None:
        """At least one non-blank, non-comment line must be present."""
        assert active_lines, (
            "The 'acceptance' file contains no active (non-blank, non-comment) lines.\n"
            "Every format assertion below relies on there being at least one active line.\n"
            f"Full file content:\n{ACCEPTANCE_FILE.read_text(errors='replace')}"
        )

    def test_acceptance_file_no_extension(self) -> None:
        """The launcher must be named 'acceptance', not 'acceptance.sh' or 'acceptance.py'."""
        assert ACCEPTANCE_FILE.suffix == "", (
            f"'acceptance' file has unexpected suffix '{ACCEPTANCE_FILE.suffix}'.\n"
            "The shell launcher must have no file extension."
        )


# ---------------------------------------------------------------------------
# 1. No Python keywords at the start of any active line
# ---------------------------------------------------------------------------


class TestNoPythonKeywordsAtLineStart:
    """Guard: no active line may begin with a Python keyword.

    A line starting with 'import', 'from', 'def', or 'class' is Python source.
    'os.execve' at line start would be a bare Python expression call.
    None of these belong in a shell command file.
    """

    @pytest.mark.parametrize("keyword", _PYTHON_KEYWORD_STARTS)
    def test_keyword_not_at_start_of_any_active_line(
        self, keyword: str, active_lines: list[str]
    ) -> None:
        """No active line may start with the given Python keyword (case-sensitive)."""
        offending = [
            ln for ln in active_lines
            if ln.lstrip().startswith(keyword)
        ]
        assert not offending, (
            f"Active line(s) in 'acceptance' start with Python keyword '{keyword}':\n"
            + "\n".join(f"  {ln!r}" for ln in offending)
            + "\n\nThe 'acceptance' file must be a shell command, not Python code.\n"
            f"Python keyword '{keyword}' at line start indicates source code was written here."
        )

    def test_no_import_statement_at_line_start(self, active_lines: list[str]) -> None:
        """'import <module>' at line start is unambiguous Python — must be absent."""
        bad = [ln for ln in active_lines if re.match(r"^\s*import\s+\w", ln)]
        assert not bad, (
            f"'import' statement found at start of active line(s): {bad!r}\n"
            "Python import statements do not belong in a shell launcher."
        )

    def test_no_from_import_at_line_start(self, active_lines: list[str]) -> None:
        """'from <module> import ...' at line start is unambiguous Python."""
        bad = [ln for ln in active_lines if re.match(r"^\s*from\s+\w", ln)]
        assert not bad, (
            f"'from ... import' statement found at start of active line(s): {bad!r}\n"
            "Python from-import statements do not belong in a shell launcher."
        )

    def test_no_def_keyword_at_line_start(self, active_lines: list[str]) -> None:
        """'def ' at line start means a Python function definition."""
        bad = [ln for ln in active_lines if re.match(r"^\s*def\s+\w", ln)]
        assert not bad, (
            f"'def' keyword found at start of active line(s): {bad!r}\n"
            "Function definitions do not belong in a shell command file."
        )

    def test_no_class_keyword_at_line_start(self, active_lines: list[str]) -> None:
        """'class ' at line start means a Python class definition."""
        bad = [ln for ln in active_lines if re.match(r"^\s*class\s+\w", ln)]
        assert not bad, (
            f"'class' keyword found at start of active line(s): {bad!r}\n"
            "Class definitions do not belong in a shell command file."
        )

    def test_no_os_execve_call_at_line_start(self, active_lines: list[str]) -> None:
        """'os.execve(' at line start is a bare Python expression — not a shell command."""
        bad = [ln for ln in active_lines if re.match(r"^\s*os\.execve\s*\(", ln)]
        assert not bad, (
            f"'os.execve(' found at start of active line(s): {bad!r}\n"
            "os.execve is a Python API call; the shell launcher must use shell syntax."
        )

    def test_no_python_shebang_in_file(self, acceptance_content: str) -> None:
        """A Python shebang (#!/usr/bin/env python3) indicates the file IS a Python script."""
        first_line = acceptance_content.splitlines()[0] if acceptance_content.strip() else ""
        assert not re.match(r"^#!.*/python", first_line), (
            f"The 'acceptance' file starts with a Python shebang: {first_line!r}\n"
            "A Python shebang means the file is a Python script, not a shell command file.\n"
            "The acceptance launcher should be a plain shell command, not a Python executable."
        )

    def test_no_triple_quote_string_in_active_lines(self, active_lines: list[str]) -> None:
        """Triple-quoted strings are a Python construct — absent in shell commands."""
        bad = [ln for ln in active_lines if '"""' in ln or "'''" in ln]
        assert not bad, (
            f"Triple-quoted string(s) found in active line(s): {bad!r}\n"
            "Triple quotes are Python syntax; they have no place in a shell command."
        )

    def test_no_python_comment_style_in_active_lines(self, active_lines: list[str]) -> None:
        """'if __name__' is Python boilerplate — invalid shell syntax."""
        bad = [ln for ln in active_lines if "__name__" in ln]
        assert not bad, (
            f"'__name__' found in active line(s): {bad!r}\n"
            "Python dunder attributes do not belong in a shell command file."
        )


# ---------------------------------------------------------------------------
# 2. Every active line references 'python' (or 'python3') and 'acceptance.py'
# ---------------------------------------------------------------------------


class TestShellCommandReferences:
    """Every active line must invoke the Python interpreter and target acceptance.py.

    This ensures the shell launcher delegates to acceptance.py and cannot be
    accidentally changed to call a different script or a different runtime.
    """

    def test_every_active_line_references_python(self, active_lines: list[str]) -> None:
        """Each active line must contain 'python' or 'python3' (the interpreter invocation)."""
        bad = [
            ln for ln in active_lines
            if not re.search(r"\bpython3?\b", ln)
        ]
        assert not bad, (
            f"Active line(s) do NOT reference 'python' or 'python3':\n"
            + "\n".join(f"  {ln!r}" for ln in bad)
            + "\n\nEvery command in 'acceptance' must invoke the Python interpreter.\n"
            "If a line runs e.g. 'bash' or 'sh', it violates the format contract."
        )

    def test_every_active_line_references_acceptance_py(self, active_lines: list[str]) -> None:
        """Each active line must reference 'acceptance.py' (the pipeline script)."""
        bad = [ln for ln in active_lines if "acceptance.py" not in ln]
        assert not bad, (
            f"Active line(s) do NOT reference 'acceptance.py':\n"
            + "\n".join(f"  {ln!r}" for ln in bad)
            + "\n\nEvery command in 'acceptance' must delegate to acceptance.py.\n"
            "Referencing a different script breaks the acceptance pipeline."
        )

    def test_python_reference_is_in_active_not_comment_only(
        self, acceptance_content: str
    ) -> None:
        """'python' must appear in an active line, not only in a comment."""
        active_with_python = [
            ln for ln in _active_lines(acceptance_content)
            if re.search(r"\bpython3?\b", ln)
        ]
        assert active_with_python, (
            "All 'python'/'python3' references in the 'acceptance' file are in comments.\n"
            "The interpreter invocation must appear in active (non-comment) code.\n"
            f"Full content:\n{acceptance_content}"
        )

    def test_acceptance_py_reference_is_in_active_not_comment_only(
        self, acceptance_content: str
    ) -> None:
        """'acceptance.py' must appear on a non-comment line, not only in comments."""
        active_with_target = [
            ln for ln in _active_lines(acceptance_content)
            if "acceptance.py" in ln
        ]
        assert active_with_target, (
            "All 'acceptance.py' references in the 'acceptance' file are in comments.\n"
            "The script must be referenced in active (non-comment) code.\n"
            f"Full content:\n{acceptance_content}"
        )

    def test_python_and_acceptance_py_co_occur_on_same_line(
        self, active_lines: list[str]
    ) -> None:
        """Each active line must reference both the interpreter AND the script together.

        A line that has 'python3' but not 'acceptance.py', or vice versa, would
        split the invocation across lines — which is not how shell commands work here.
        """
        for ln in active_lines:
            has_python = bool(re.search(r"\bpython3?\b", ln))
            has_target = "acceptance.py" in ln
            assert has_python and has_target, (
                f"Active line has interpreter but no script, or script but no interpreter:\n"
                f"  {ln!r}\n"
                "Both 'python'/'python3' and 'acceptance.py' must co-occur on the same line."
            )

    def test_python_invocation_precedes_acceptance_py_on_each_line(
        self, active_lines: list[str]
    ) -> None:
        """The interpreter ('python'/'python3') must appear before 'acceptance.py'."""
        for ln in active_lines:
            py_match = re.search(r"\bpython3?\b", ln)
            script_pos = ln.find("acceptance.py")
            if py_match and script_pos >= 0:
                assert py_match.start() < script_pos, (
                    f"'python'/'python3' appears AFTER 'acceptance.py' on line:\n  {ln!r}\n"
                    "The shell invocation must be: python3 acceptance.py (interpreter first)."
                )


# ---------------------------------------------------------------------------
# 3. SM_LLM_BACKEND or 'offline' must appear for reproducibility
# ---------------------------------------------------------------------------


class TestReproducibilityGuard:
    """Gate reproducibility: the file must set SM_LLM_BACKEND or contain 'offline'.

    Without this, running './acceptance' would attempt live LLM API calls,
    making CI non-deterministic and potentially billable.
    """

    def test_sm_llm_backend_or_offline_present(self, acceptance_content: str) -> None:
        """'SM_LLM_BACKEND' or 'offline' must appear somewhere in the acceptance file."""
        has_key = "SM_LLM_BACKEND" in acceptance_content
        has_value = "offline" in acceptance_content
        assert has_key or has_value, (
            "The 'acceptance' file contains neither 'SM_LLM_BACKEND' nor 'offline'.\n"
            "At least one of these tokens must be present so the gate runs in offline mode.\n"
            f"Full content:\n{acceptance_content}"
        )

    def test_sm_llm_backend_key_in_active_line(self, acceptance_content: str) -> None:
        """'SM_LLM_BACKEND' must appear on an active (non-comment) line to have any effect."""
        content = acceptance_content
        if "SM_LLM_BACKEND" not in content:
            pytest.skip("SM_LLM_BACKEND not present — covered by other test")
        active_with_key = [
            ln for ln in _active_lines(content)
            if "SM_LLM_BACKEND" in ln
        ]
        assert active_with_key, (
            "All 'SM_LLM_BACKEND' references in 'acceptance' are in comments.\n"
            "The env var assignment must be in active code to take effect."
        )

    def test_offline_value_in_active_line(self, acceptance_content: str) -> None:
        """The literal 'offline' must appear on a non-comment line."""
        content = acceptance_content
        if "offline" not in content:
            pytest.skip("'offline' not present — covered by other test")
        active_with_offline = [
            ln for ln in _active_lines(content)
            if "offline" in ln
        ]
        assert active_with_offline, (
            "All 'offline' references in 'acceptance' are in comments.\n"
            "The 'offline' value must be set in active, executable code."
        )

    def test_sm_llm_backend_set_to_offline(self, acceptance_content: str) -> None:
        """The file should set SM_LLM_BACKEND=offline (or equivalent) on an active line."""
        content = acceptance_content
        if "SM_LLM_BACKEND" not in content or "offline" not in content:
            pytest.skip("prerequisite tokens missing — covered by other tests")
        for ln in _active_lines(content):
            if "SM_LLM_BACKEND" in ln and "offline" in ln:
                return  # found a line that sets the key to the value — good
        # If we get here, the key and value exist but not on the same active line
        # This is still acceptable (e.g. shell export + env command on separate lines)
        # so don't fail — only check that at minimum one of them is active
        active_key = any("SM_LLM_BACKEND" in ln for ln in _active_lines(content))
        active_val = any("offline" in ln for ln in _active_lines(content))
        assert active_key or active_val, (
            "'SM_LLM_BACKEND' and 'offline' both exist in the file, but only in comments.\n"
            "At least one of them must appear in active code so the backend is actually set."
        )

    def test_sm_llm_backend_offline_together_on_same_line(
        self, active_lines: list[str]
    ) -> None:
        """At least one active line must co-reference SM_LLM_BACKEND and offline together."""
        combined = [
            ln for ln in active_lines
            if "SM_LLM_BACKEND" in ln and "offline" in ln
        ]
        assert combined, (
            "No active line sets SM_LLM_BACKEND=offline in a single expression.\n"
            "Expected a shell prefix like 'SM_LLM_BACKEND=offline python3 acceptance.py'.\n"
            "Both tokens must appear together to guarantee the offline backend is used.\n"
            f"Active lines:\n" + "\n".join(f"  {ln!r}" for ln in active_lines)
        )


# ---------------------------------------------------------------------------
# Combined format snapshot — the canonical shell command shape
# ---------------------------------------------------------------------------


class TestCanonicalShellCommandShape:
    """The active content must match the expected shell-command format as a whole."""

    def test_active_lines_are_single_shell_commands(self, active_lines: list[str]) -> None:
        """Each active line must look like a shell assignment-prefix + command, not Python."""
        for ln in active_lines:
            stripped = ln.strip()
            # Shell env-prefix lines look like: KEY=VALUE python3 script.py
            # They must NOT look like Python statements (no colon at end, no '(' at start)
            assert not stripped.endswith(":"), (
                f"Active line ends with ':' — this is Python block syntax, not shell:\n  {ln!r}"
            )
            # Bare function/method calls at line start (e.g. 'run()' or 'main()') are Python
            assert not re.match(r"^\s*\w+\s*\(", stripped), (
                f"Active line starts with a callable — Python expression, not shell:\n  {ln!r}"
            )

    def test_no_python_indented_blocks(self, active_lines: list[str]) -> None:
        """Active lines must not be indented — shell commands run at column 0."""
        indented = [ln for ln in active_lines if ln != ln.lstrip()]
        assert not indented, (
            f"Indented active line(s) found: {indented!r}\n"
            "Python blocks (if/def/class bodies) use indentation; shell commands do not.\n"
            "Indented active lines indicate Python source code was written in this file."
        )

    def test_command_contains_env_assignment_prefix(self, active_lines: list[str]) -> None:
        """At least one active line uses the shell env-assignment prefix pattern: KEY=VALUE cmd."""
        prefix_lines = [
            ln for ln in active_lines
            if re.match(r"^\w+=\S+\s+\w", ln.strip())
        ]
        assert prefix_lines, (
            "No active line matches the shell env-assignment prefix pattern: KEY=VALUE command.\n"
            "Expected format: 'SM_LLM_BACKEND=offline python3 acceptance.py'.\n"
            f"Active lines:\n" + "\n".join(f"  {ln!r}" for ln in active_lines)
        )

    def test_no_assignment_operator_for_python_variable(
        self, active_lines: list[str]
    ) -> None:
        """Python variable assignments ('x = something') on standalone lines are forbidden."""
        for ln in active_lines:
            stripped = ln.strip()
            # Match: identifier <spaces> = <spaces> (not preceded by = and not KEY=VALUE prefix)
            # Shell KEY=VALUE has no spaces around '='; Python assignment does
            m = re.match(r"^([A-Za-z_]\w*)\s+=\s+", stripped)
            if m:
                pytest.fail(
                    f"Python-style variable assignment found in active line:\n  {ln!r}\n"
                    "Shell env-prefix assignments use 'KEY=VALUE' (no spaces around '=').\n"
                    "A spaced assignment is Python syntax."
                )


# ---------------------------------------------------------------------------
# Comment-stripping sanity: comments must not affect the active-line checks
# ---------------------------------------------------------------------------


class TestCommentStripping:
    """Verify that the comment-stripping logic used by active_lines() is correct.

    Python keywords appearing only in comments must not trigger failures.
    These tests use synthetic content to prove the helper works correctly
    before we rely on it for the real file.
    """

    def test_comment_lines_excluded_from_active_lines(self) -> None:
        """Lines starting with '#' are not active, even if they contain Python keywords."""
        synthetic = "# import os\n# def foo():\nSM_LLM_BACKEND=offline python3 acceptance.py\n"
        lines = _active_lines(synthetic)
        assert lines == ["SM_LLM_BACKEND=offline python3 acceptance.py"], (
            f"Comment lines were not excluded from active lines; got: {lines!r}"
        )

    def test_blank_lines_excluded_from_active_lines(self) -> None:
        """Blank and whitespace-only lines are not active."""
        synthetic = "\n   \nSM_LLM_BACKEND=offline python3 acceptance.py\n\n"
        lines = _active_lines(synthetic)
        assert lines == ["SM_LLM_BACKEND=offline python3 acceptance.py"], (
            f"Blank lines were not excluded from active lines; got: {lines!r}"
        )

    def test_inline_comment_does_not_make_line_inactive(self) -> None:
        """A line with trailing '# comment' is still active (the command prefix is active)."""
        synthetic = "SM_LLM_BACKEND=offline python3 acceptance.py  # run offline\n"
        lines = _active_lines(synthetic)
        assert len(lines) == 1, (
            f"Inline-comment line was incorrectly excluded; got: {lines!r}"
        )
        assert "python3" in lines[0], (
            "Active line content must be the full command including the inline comment suffix."
        )

    def test_python_keywords_in_comments_do_not_trigger_failures(self) -> None:
        """Synthetic file with Python keywords only in comments must pass the keyword guard."""
        synthetic = (
            "# import os\n"
            "# def run(): pass\n"
            "# class Foo: pass\n"
            "SM_LLM_BACKEND=offline python3 acceptance.py\n"
        )
        active = _active_lines(synthetic)
        for keyword in _PYTHON_KEYWORD_STARTS:
            bad = [ln for ln in active if ln.lstrip().startswith(keyword)]
            assert not bad, (
                f"Keyword '{keyword}' in comments incorrectly flagged as active: {bad!r}"
            )

    def test_acceptance_file_comment_lines_not_counted_as_active(
        self, acceptance_content: str, active_lines: list[str]
    ) -> None:
        """Verify the real acceptance file's comment/blank lines are excluded."""
        all_lines = acceptance_content.splitlines()
        comment_and_blank = [
            ln for ln in all_lines
            if not ln.strip() or ln.strip().startswith("#")
        ]
        for ln in comment_and_blank:
            assert ln not in active_lines, (
                f"Comment/blank line incorrectly included in active_lines(): {ln!r}"
            )


# ---------------------------------------------------------------------------
# No-recursive-pytest guard — this file must not spawn pytest
# ---------------------------------------------------------------------------


class TestNoRecursivePytestInThisFile:
    """This file must never invoke pytest as a subprocess — that hangs the suite."""

    def test_this_file_has_no_subprocess_pytest_invocation(self) -> None:
        content = Path(__file__).read_text(errors="replace")
        for lineno, line in enumerate(content.splitlines(), start=1):
            if line.strip().startswith("#"):
                continue
            has_pytest_str = re.search(r'["\']pytest["\']', line)
            has_subprocess = re.search(
                r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", line
            )
            if has_pytest_str and has_subprocess:
                pytest.fail(
                    f"Line {lineno} invokes pytest as a subprocess:\n  {line.rstrip()}\n"
                    "Recursive pytest calls hang the suite."
                )

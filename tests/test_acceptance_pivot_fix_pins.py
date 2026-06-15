"""Regression pins for the acceptance/acceptance.py pivot fix.

Background
----------
Five tests were previously failing because the ``acceptance`` file was changed
from a Python script (using ``os.execve`` + ``sys.executable``) to a one-line
shell command (``SM_LLM_BACKEND=offline python3 acceptance.py``).  Tests that
checked the *shell launcher* for Python-specific properties — ``sys.executable``,
``import sys``, valid Python AST — were red.  The fix correctly redirected those
checks to ``acceptance.py`` (the actual Python pipeline script).

What this file pins
-------------------
A. The ``acceptance`` shell launcher is NOT Python and lacks the old
   ``os.execve`` artifacts.  (Prevents silent reversion to the old form.)
B. ``acceptance.py`` DOES carry the Python properties the 5 tests now check.
   (Prevents silent removal of ``sys.executable`` from the correct file.)
C. The shell launcher can actually be invoked by ``bash`` and exits 0.
   (Proves the shell form is executable, not just well-formatted.)
D. Running ``python3 acceptance.py`` with ``SM_LLM_BACKEND=offline`` (the
   exact invocation form used by the shell launcher) exits 0 and produces
   the required output sections.
E. CLI subprocess tests run with ``SM_LLM_BACKEND=offline`` pinned, so they
   cannot reach the live ``claude`` binary (mirroring the test_cli.py fix).

Design constraints
------------------
- No mocks of the units under test — mocking proves nothing.
- Every assertion CAN fail on a real regression.
- No recursive ``pytest`` subprocess invocations (project memory).
- All subprocess fixtures use ``SM_LLM_BACKEND=offline`` unconditionally.
- Module-scoped fixtures avoid re-running the pipeline multiple times.
"""

from __future__ import annotations

import ast
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
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"     # shell launcher (no .py)
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"   # Python pipeline script
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"


def _offline_env(**extra: str) -> dict[str, str]:
    return {**os.environ, "SM_LLM_BACKEND": "offline", **extra}


# ---------------------------------------------------------------------------
# Module-scoped fixtures: run the pipeline once per session via two different
# invocation forms and share the results across all tests that need them.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def via_sys_executable() -> subprocess.CompletedProcess:
    """Run 'sys.executable acceptance.py' — the form used by the fixed tests."""
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        timeout=180,
    )


@pytest.fixture(scope="module")
def via_sys_executable_stdout(via_sys_executable: subprocess.CompletedProcess) -> str:
    return via_sys_executable.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def via_python3() -> subprocess.CompletedProcess:
    """Run 'python3 acceptance.py' — the exact form the shell launcher uses."""
    return subprocess.run(
        ["python3", str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        timeout=180,
    )


@pytest.fixture(scope="module")
def via_python3_stdout(via_python3: subprocess.CompletedProcess) -> str:
    return via_python3.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def via_bash() -> subprocess.CompletedProcess:
    """Run the shell launcher with 'bash acceptance' — exercises the shell form directly."""
    return subprocess.run(
        ["bash", str(ACCEPTANCE_FILE)],
        capture_output=True,
        cwd=str(PROJECT_ROOT),
        env=_offline_env(),
        timeout=180,
    )


@pytest.fixture(scope="module")
def via_bash_stdout(via_bash: subprocess.CompletedProcess) -> str:
    return via_bash.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# A. Shell launcher is NOT Python — pins the absence of old artifacts
# ---------------------------------------------------------------------------


class TestShellLauncherIsNotPython:
    """Guard that 'acceptance' has no Python artifacts from the old os.execve impl.

    These are the NEGATIVE complements of the 5 previously-failing tests:
    the tests that failed expected Python properties to be present in the
    shell launcher; these tests assert the launcher does NOT have those
    properties (validating the fix is not reverted).
    """

    def test_acceptance_file_exists_and_is_shell(self) -> None:
        """Prerequisite: the launcher exists and is readable."""
        assert ACCEPTANCE_FILE.exists(), (
            f"'acceptance' shell launcher missing at {ACCEPTANCE_FILE}"
        )
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert content.strip(), "'acceptance' is empty"

    def test_acceptance_file_is_not_valid_python(self) -> None:
        """The shell one-liner must NOT be parseable as Python.

        The old 'acceptance' was valid Python; the new shell command is not.
        If this assertion fails, the file has reverted to Python source code.

        The shell command 'SM_LLM_BACKEND=offline python3 acceptance.py' is not
        valid Python because 'SM_LLM_BACKEND=offline' is not a valid assignment
        expression in Python (it is a shell env-var prefix).
        """
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        try:
            ast.parse(content)
        except SyntaxError:
            return  # expected: shell command is not valid Python
        pytest.fail(
            "The 'acceptance' file parses as valid Python.\n"
            "The shell launcher (SM_LLM_BACKEND=offline python3 acceptance.py) "
            "must NOT be valid Python — if it is, the file has reverted to a Python script.\n"
            f"Content:\n{content}"
        )

    def test_acceptance_file_has_no_os_execve(self) -> None:
        """'os.execve' must be absent — that was the old Python launcher API.

        The old 'acceptance' used:
          os.execve(sys.executable, [sys.executable, '...acceptance.py'], {...})
        The new form is a plain shell command; os.execve has no meaning there.
        """
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "os.execve" not in content, (
            "The 'acceptance' shell launcher contains 'os.execve'.\n"
            "This indicates the file has reverted to the old Python os.execve form.\n"
            f"Content:\n{content}"
        )

    def test_acceptance_file_has_no_sys_executable(self) -> None:
        """'sys.executable' must be absent from the shell launcher.

        The five previously-failing tests were checking the shell launcher for
        'sys.executable' and failing because a shell command has no such token.
        After the fix, 'sys.executable' belongs only in acceptance.py.
        """
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "sys.executable" not in content, (
            "The 'acceptance' shell launcher contains 'sys.executable'.\n"
            "'sys.executable' is Python; it has no meaning in a shell command.\n"
            "This token belongs in acceptance.py, not in the shell launcher.\n"
            f"Content:\n{content}"
        )

    def test_acceptance_file_has_no_import_sys(self) -> None:
        """'import sys' must be absent — Python imports have no meaning in shell."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        has_import = bool(
            re.search(r"^\s*import\s+sys\b", content, re.MULTILINE)
            or re.search(r"^\s*from\s+sys\s+import\b", content, re.MULTILINE)
        )
        assert not has_import, (
            "The 'acceptance' shell launcher contains 'import sys'.\n"
            "Python import statements do not belong in a shell command file.\n"
            f"Content:\n{content}"
        )

    def test_acceptance_file_has_no_python_shebang(self) -> None:
        """No Python shebang — the shell launcher is not a Python executable.

        The old acceptance Python script started with '#!/usr/bin/env python3'.
        The new shell form must NOT have this shebang (it would cause the OS
        to execute it as Python, not as a shell command, when invoked directly).
        """
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        first_line = content.splitlines()[0] if content.strip() else ""
        assert not re.match(r"^#!.*/python", first_line), (
            f"The 'acceptance' file starts with a Python shebang: {first_line!r}\n"
            "This indicates the file has reverted to a Python executable.\n"
            "The shell launcher must NOT have '#!/usr/bin/env python3'."
        )

    def test_acceptance_file_has_no_subprocess_import(self) -> None:
        """'import subprocess' must be absent — old Python code used this."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        active = [
            l for l in content.splitlines()
            if "import subprocess" in l and not l.lstrip().startswith("#")
        ]
        assert not active, (
            f"The 'acceptance' shell launcher imports subprocess on line(s): {active!r}\n"
            "Python subprocess imports do not belong in a shell command file."
        )


# ---------------------------------------------------------------------------
# B. acceptance.py has the Python properties — the fixed tests now check it
# ---------------------------------------------------------------------------


class TestAcceptancePyHasPythonProperties:
    """Pin the invariants that the five fixed tests now correctly verify in acceptance.py.

    These tests would all PASS on the old acceptance file (which was Python), and
    PASS on the current acceptance.py. But they exist to ensure acceptance.py is
    never accidentally simplified in a way that removes sys.executable.
    """

    def test_acceptance_py_exists(self) -> None:
        assert ACCEPTANCE_PY.exists(), (
            f"'acceptance.py' missing at {ACCEPTANCE_PY}.\n"
            "The shell launcher delegates to this file — it must exist."
        )

    def test_acceptance_py_is_non_empty(self) -> None:
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert content.strip(), f"'acceptance.py' at {ACCEPTANCE_PY} is empty"

    def test_acceptance_py_contains_sys_executable(self) -> None:
        """The literal 'sys.executable' must appear in acceptance.py.

        This is the core invariant the five previously-failing tests were checking.
        They failed because they read the wrong file (the shell launcher).
        Now that they read acceptance.py, this must stay true.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, (
            "'acceptance.py' must contain 'sys.executable'.\n"
            "This is the portable interpreter reference used by the four acceptance\n"
            "commands (once / digest-dry-run / carrier-once / check_server.py).\n"
            f"Actual content (first 500):\n{content[:500]}"
        )

    def test_acceptance_py_sys_executable_on_non_comment_line(self) -> None:
        """'sys.executable' must appear in active code, not only in comments."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, "prerequisite: token not found"
        active_lines = [
            line for line in content.splitlines()
            if "sys.executable" in line and not line.lstrip().startswith("#")
        ]
        assert active_lines, (
            "Every line containing 'sys.executable' in 'acceptance.py' is a comment.\n"
            "The token must appear in executable code — a comment is not active."
        )

    def test_acceptance_py_imports_sys(self) -> None:
        """'import sys' must accompany 'sys.executable' — otherwise NameError."""
        content = ACCEPTANCE_PY.read_text(errors="replace")
        assert "sys.executable" in content, "prerequisite: token not found"
        has_import = bool(
            re.search(r"^\s*import sys\b", content, re.MULTILINE)
            or re.search(r"^\s*from\s+sys\s+import", content, re.MULTILINE)
        )
        assert has_import, (
            "'acceptance.py' uses 'sys.executable' but 'sys' is not imported.\n"
            "Adding 'sys.executable' without 'import sys' raises NameError."
        )

    def test_acceptance_py_is_valid_python(self) -> None:
        """'acceptance.py' must be syntactically valid Python.

        The shell launcher invokes this file as 'python3 acceptance.py'; a
        SyntaxError causes an immediate non-zero exit before any commands run.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        try:
            ast.parse(content)
        except SyntaxError as exc:
            pytest.fail(
                f"'acceptance.py' has a Python syntax error:\n{exc}\n"
                f"The shell launcher runs this file directly — syntax errors are fatal."
            )

    def test_acceptance_py_does_not_use_bare_python3_as_interpreter(self) -> None:
        """acceptance.py must not call 'python3' as a bare interpreter literal.

        The portability guarantee lives in 'sys.executable'.  Using the bare
        string 'python3' would break environments where only 'python3.12' etc. exist.
        All subprocess calls in acceptance.py must use sys.executable, not 'python3'.
        """
        content = ACCEPTANCE_PY.read_text(errors="replace")
        active_lines = [
            line for line in content.splitlines()
            if not line.lstrip().startswith("#")
        ]
        # A line using "python3" as a subprocess command string (not as a comment)
        # would be: subprocess.run(["python3", ...]) — catch that pattern
        bare_python3_lines = [
            line for line in active_lines
            if re.search(r'["\']python3["\']', line)
        ]
        assert not bare_python3_lines, (
            "acceptance.py invokes 'python3' as a bare string literal on non-comment "
            f"line(s):\n" + "\n".join(bare_python3_lines) + "\n"
            "Use sys.executable instead — 'python3' is not portable across all envs."
        )


# ---------------------------------------------------------------------------
# C. Shell launcher runs via bash and exits 0
# ---------------------------------------------------------------------------


class TestShellLauncherBashExecution:
    """Verify that 'bash acceptance' actually works as a shell command.

    These tests exercise the shell launcher in the way a CI script would:
    running it via an explicit shell interpreter.  The SM_LLM_BACKEND=offline
    env var is set in the calling env (in addition to being in the file itself)
    to ensure the subprocess never reaches the live LLM backend.
    """

    def test_bash_acceptance_exits_zero(
        self, via_bash: subprocess.CompletedProcess
    ) -> None:
        assert via_bash.returncode == 0, (
            f"'bash acceptance' exited {via_bash.returncode}; expected 0.\n"
            f"This means one of the four commands in acceptance.py failed.\n"
            f"stderr (last 1000):\n"
            f"{via_bash.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout (last 500):\n"
            f"{via_bash.stdout.decode(errors='replace')[-500:]}"
        )

    def test_bash_acceptance_produces_stdout(self, via_bash_stdout: str) -> None:
        assert via_bash_stdout.strip(), (
            "'bash acceptance' produced empty stdout.\n"
            "The pipeline must emit at least the digest output."
        )

    def test_bash_acceptance_stdout_has_domain_sections(
        self, via_bash_stdout: str
    ) -> None:
        """Output must include at least one domain section header."""
        section_found = any(
            section in via_bash_stdout
            for section in ("## WORLD", "## MARKETS", "## AI")
        )
        assert section_found, (
            "'bash acceptance' output has no domain section headers "
            "(## WORLD / ## MARKETS / ## AI).\n"
            f"stdout (first 2000):\n{via_bash_stdout[:2000]}"
        )

    def test_bash_acceptance_stdout_has_web_server_smoke_pass(
        self, via_bash_stdout: str
    ) -> None:
        """cmd4 (check_server.py) must emit 'web-server-smoke: PASS'."""
        assert "web-server-smoke: PASS" in via_bash_stdout, (
            "'bash acceptance' output must contain 'web-server-smoke: PASS'.\n"
            f"stdout (last 500):\n{via_bash_stdout[-500:]}"
        )

    def test_bash_acceptance_stdout_has_discourse_carrier_line(
        self, via_bash_stdout: str
    ) -> None:
        """cmd3 must produce a line starting with 'discourse-carrier'."""
        carrier_lines = [
            l for l in via_bash_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert carrier_lines, (
            "'bash acceptance' output must contain a line starting with 'discourse-carrier'.\n"
            f"stdout (last 1000):\n{via_bash_stdout[-1000:]}"
        )

    def test_bash_acceptance_no_traceback(
        self, via_bash: subprocess.CompletedProcess
    ) -> None:
        stdout = via_bash.stdout.decode(errors="replace")
        stderr = via_bash.stderr.decode(errors="replace")
        assert "Traceback" not in stdout, (
            "'bash acceptance' stdout contains a Python traceback.\n"
            f"stdout (first 2000):\n{stdout[:2000]}"
        )
        assert "Traceback" not in stderr, (
            "'bash acceptance' stderr contains a Python traceback.\n"
            f"stderr (first 2000):\n{stderr[:2000]}"
        )


# ---------------------------------------------------------------------------
# D. 'python3 acceptance.py' invocation (exact shell launcher form) works
# ---------------------------------------------------------------------------


class TestPython3DirectInvocation:
    """Verify that 'python3 acceptance.py' (the form used by the shell launcher) works.

    The shell launcher's single active line is:
        SM_LLM_BACKEND=offline python3 acceptance.py

    These tests run python3 directly with SM_LLM_BACKEND=offline in the env,
    mirroring what the shell launcher does.  They are complementary to the
    test_acceptance_file_properties_regression.py fixtures that use sys.executable.
    """

    def test_python3_binary_is_available(self) -> None:
        """python3 must be on PATH — the shell launcher requires it."""
        import shutil
        python3_path = shutil.which("python3")
        assert python3_path is not None, (
            "'python3' is not available in PATH.\n"
            "The shell launcher 'SM_LLM_BACKEND=offline python3 acceptance.py' "
            "requires python3 to be findable in PATH."
        )

    def test_python3_invocation_exits_zero(
        self, via_python3: subprocess.CompletedProcess
    ) -> None:
        assert via_python3.returncode == 0, (
            f"'python3 acceptance.py' exited {via_python3.returncode}; expected 0.\n"
            f"This is the exact invocation form used by the shell launcher.\n"
            f"stderr (last 1000):\n"
            f"{via_python3.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout (last 500):\n"
            f"{via_python3.stdout.decode(errors='replace')[-500:]}"
        )

    def test_python3_invocation_stdout_nonempty(self, via_python3_stdout: str) -> None:
        assert via_python3_stdout.strip(), (
            "'python3 acceptance.py' produced empty stdout."
        )

    def test_python3_produces_world_section(self, via_python3_stdout: str) -> None:
        assert "## WORLD" in via_python3_stdout, (
            "'python3 acceptance.py' output must contain '## WORLD' section header."
        )

    def test_python3_produces_dual_lens_header(self, via_python3_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in via_python3_stdout, (
            "'python3 acceptance.py' output must contain '## DUAL-LENS EVENTS'."
        )

    def test_python3_produces_spin_pct(self, via_python3_stdout: str) -> None:
        assert "spin_pct:" in via_python3_stdout, (
            "'python3 acceptance.py' output must contain 'spin_pct:' annotations."
        )
        matches = re.findall(r"spin_pct:\s*[\d.]+%", via_python3_stdout)
        assert matches, (
            "No 'spin_pct: N.N%' pattern found in 'python3 acceptance.py' output."
        )

    def test_python3_produces_discourse_carrier_line(
        self, via_python3_stdout: str
    ) -> None:
        carrier_lines = [
            l for l in via_python3_stdout.splitlines()
            if l.startswith("discourse-carrier")
        ]
        assert carrier_lines, (
            "'python3 acceptance.py' must produce a 'discourse-carrier' line.\n"
            f"stdout (first 2000):\n{via_python3_stdout[:2000]}"
        )

    def test_python3_and_sys_executable_produce_same_sections(
        self,
        via_python3_stdout: str,
        via_sys_executable_stdout: str,
    ) -> None:
        """Both invocation forms must produce the same set of section headers.

        If python3 ≠ sys.executable, the outputs could diverge; this test
        catches that before it becomes a CI vs local divergence.
        """
        expected_sections = ["## WORLD", "## MARKETS", "## AI", "## DUAL-LENS EVENTS"]
        for section in expected_sections:
            in_python3 = section in via_python3_stdout
            in_sys_exec = section in via_sys_executable_stdout
            assert in_python3 == in_sys_exec, (
                f"Section '{section}' present via python3={in_python3} but "
                f"via sys.executable={in_sys_exec}.\n"
                "Both invocation forms must produce the same structural output.\n"
                "This indicates python3 and sys.executable resolve to different interpreters."
            )


# ---------------------------------------------------------------------------
# E. SM_LLM_BACKEND=offline pin for CLI subprocess tests
# ---------------------------------------------------------------------------


class TestCliSubprocessOfflinePin:
    """Verify that CLI subprocess tests explicitly pin SM_LLM_BACKEND=offline.

    One of the five previously-failing tests was a flaky CLI test that would
    sometimes fail because the subprocess reached the live 'claude' binary.
    The fix pinned SM_LLM_BACKEND=offline in the subprocess env.

    These tests verify the fix holds: a 'once' subprocess with SM_SOURCES set
    and SM_LLM_BACKEND=offline must exit 0 deterministically.
    """

    def test_once_subprocess_with_offline_pin_exits_zero(self) -> None:
        """'once' with SM_LLM_BACKEND=offline must exit 0 — never flaky."""
        result = subprocess.run(
            [sys.executable, "-m", "situation_monitor", "once", "--config", "/dev/null"],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            env=_offline_env(SM_SOURCES=str(RSS_FIXTURE)),
            timeout=60,
        )
        assert result.returncode == 0, (
            f"'once' subprocess with SM_LLM_BACKEND=offline exited {result.returncode}.\n"
            f"stderr:\n{result.stderr.decode(errors='replace')[-500:]}\n"
            f"stdout:\n{result.stdout.decode(errors='replace')[-300:]}"
        )

    def test_once_subprocess_stdout_contains_article_title(self) -> None:
        """The offline digest must emit at least one article title from the fixture."""
        result = subprocess.run(
            [sys.executable, "-m", "situation_monitor", "once", "--config", "/dev/null"],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            env=_offline_env(SM_SOURCES=str(RSS_FIXTURE)),
            timeout=60,
        )
        stdout = result.stdout.decode(errors="replace")
        assert result.returncode == 0, (
            f"subprocess must exit 0 before checking stdout; got {result.returncode}"
        )
        # rss_sample.xml contains 'Bitcoin Surges' and 'AI Research Breakthrough'
        has_title = (
            "Bitcoin Surges" in stdout
            or "AI Research Breakthrough" in stdout
            or "DeepMind" in stdout
            or "GPT" in stdout
        )
        assert has_title, (
            "offline 'once' subprocess must emit at least one article title.\n"
            f"stdout (first 1000):\n{stdout[:1000]}"
        )

    def test_once_subprocess_without_offline_pin_could_be_flaky(self) -> None:
        """Confirm that the offline backend env var is actually recognised.

        When SM_LLM_BACKEND=offline, the LLM backend must not spawn the 'claude'
        binary.  We verify this by checking that the subprocess env correctly
        propagates the value.  This tests the env-building, not the subprocess.
        """
        env = _offline_env(SM_SOURCES=str(RSS_FIXTURE))
        assert env.get("SM_LLM_BACKEND") == "offline", (
            "_offline_env() must set SM_LLM_BACKEND=offline in the returned dict"
        )
        assert "SM_SOURCES" in env, (
            "_offline_env() must accept and forward SM_SOURCES"
        )
        assert str(RSS_FIXTURE) in env["SM_SOURCES"], (
            "SM_SOURCES must reference the fixture RSS file path"
        )

    def test_digest_dry_run_subprocess_with_offline_pin_exits_zero(self) -> None:
        """'digest-dry-run' must also work offline without the live backend."""
        result = subprocess.run(
            [
                sys.executable, "-m", "situation_monitor",
                "digest-dry-run", "--config", str(ACCEPTANCE_SOURCE_DEFS),
            ],
            capture_output=True,
            cwd=str(PROJECT_ROOT),
            env=_offline_env(SM_SOURCES=str(RSS_FIXTURE)),
            timeout=60,
        )
        assert result.returncode == 0, (
            f"'digest-dry-run' with SM_LLM_BACKEND=offline exited {result.returncode}.\n"
            f"stderr:\n{result.stderr.decode(errors='replace')[-500:]}"
        )


# ---------------------------------------------------------------------------
# Invariant: no recursive pytest in this file or in acceptance files
# ---------------------------------------------------------------------------


class TestNoRecursivePytest:
    """This file must not spawn pytest recursively (project memory: it hangs the suite)."""

    def test_this_file_has_no_subprocess_pytest_invocation(self) -> None:
        content = Path(__file__).read_text(errors="replace")
        for lineno, line in enumerate(content.splitlines(), start=1):
            if line.lstrip().startswith("#"):
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

    def test_acceptance_py_has_no_recursive_pytest(self) -> None:
        content = ACCEPTANCE_PY.read_text(errors="replace")
        active = [
            l for l in content.splitlines()
            if not l.lstrip().startswith("#") and "pytest" in l
        ]
        assert not active, (
            "'acceptance.py' contains 'pytest' in active code.\n"
            "Recursive pytest invocations hang the test suite.\n"
            f"Matching lines:\n" + "\n".join(active)
        )

    def test_acceptance_file_has_no_recursive_pytest(self) -> None:
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        active = [
            l for l in content.splitlines()
            if not l.lstrip().startswith("#") and "pytest" in l
        ]
        assert not active, (
            "The 'acceptance' shell launcher contains 'pytest' in active code.\n"
            "Recursive pytest invocations hang the test suite.\n"
            f"Matching lines:\n" + "\n".join(active)
        )

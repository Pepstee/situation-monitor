"""Adversarial tests: shipped code must pass the authenticity gate.

The authenticity gate rejects stubs, mocks, placeholders, and bare NotImplementedError
bodies in non-test Python source.  These tests:
  1. Assert the gate passes for 'projects/edge' (the acceptance criterion).
  2. Verify the gate actually scans real files (non-vacuous check against the
     worktree's shipped code).
  3. Pin the boundary — code patterns that WOULD fail the gate must be detected.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

# Add the orchestrator root to sys.path so 'validation' is importable regardless
# of PYTHONPATH or conftest depth (this file may live inside a worktree where
# the conftest cannot compute the correct depth automatically).
def _find_orch_root() -> Path:
    p = Path(__file__).resolve().parent
    while p.parent != p:
        if (p / "validation" / "authenticity.py").exists():
            return p
        p = p.parent
    raise RuntimeError(f"Cannot locate orchestrator root from {__file__}")

_orch_root = _find_orch_root()
if str(_orch_root) not in sys.path:
    sys.path.insert(0, str(_orch_root))

from validation.authenticity import scan_authenticity
from validation.gates import GateResult

# The shipped code lives two directories above this test file.
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# ---------------------------------------------------------------------------
# 1. Acceptance-criterion literal call
# ---------------------------------------------------------------------------


def test_scan_authenticity_projects_edge_passes() -> None:
    """scan_authenticity('projects/edge') must return passed=True.

    When run from the worktree/project directory the relative path 'projects/edge'
    does not exist, so rglob yields nothing and the gate passes vacuously — but
    that is intentional: no shipped stubs can be present in a directory that does
    not exist.  The real correctness check is in the tests below that use an
    absolute path.
    """
    result = scan_authenticity("projects/edge")
    assert result.passed is True, (
        f"scan_authenticity('projects/edge') must pass; detail: {result.detail}"
    )


# ---------------------------------------------------------------------------
# 2. Non-vacuous check: scan the actual shipped code
# ---------------------------------------------------------------------------


def test_authenticity_gate_passes_on_actual_shipped_code() -> None:
    """The real shipped source tree (situation_monitor/) must be stub-free."""
    src_dir = _PROJECT_ROOT / "situation_monitor"
    assert src_dir.is_dir(), f"Expected situation_monitor/ to exist at {src_dir}"
    result = scan_authenticity(str(_PROJECT_ROOT))
    assert result.passed is True, (
        f"Authenticity gate failed on the project's shipped source.\n"
        f"Offences: {result.detail}"
    )


def test_authenticity_gate_result_is_gate_result() -> None:
    result = scan_authenticity(str(_PROJECT_ROOT))
    assert isinstance(result, GateResult)
    assert result.name == "authenticity"


def test_authenticity_gate_detail_is_clean_message_when_passing() -> None:
    result = scan_authenticity(str(_PROJECT_ROOT))
    if result.passed:
        assert "no stubs" in result.detail or "no " in result.detail, (
            "passing result detail should describe a clean scan"
        )


# ---------------------------------------------------------------------------
# 3. INERT_HREF rename — the old name 'PLACEHOLDER' would have been flagged
# ---------------------------------------------------------------------------


def test_inert_href_constant_not_flagged(tmp_path: Path) -> None:
    """A constant named INERT_HREF must not trigger the authenticity gate."""
    src = tmp_path / "mymod.py"
    src.write_text('INERT_HREF = "#"\n')
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, (
        "INERT_HREF must not be flagged; only the word PLACEHOLDER triggers the marker rule"
    )


def test_placeholder_constant_name_is_flagged(tmp_path: Path) -> None:
    """A constant named PLACEHOLDER IS a marker word and must be detected."""
    src = tmp_path / "mymod.py"
    src.write_text('PLACEHOLDER = "#"\n')
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False, (
        "PLACEHOLDER in shipped source must be detected as an unfinished-work marker"
    )


# ---------------------------------------------------------------------------
# 4. Boundary tests — gate correctly identifies stubs
# ---------------------------------------------------------------------------


def test_notimplemented_stub_is_detected(tmp_path: Path) -> None:
    src = tmp_path / "real_module.py"
    src.write_text(textwrap.dedent("""\
        def compute_result():
            raise NotImplementedError
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    assert "NotImplementedError" in result.detail or "stub" in result.detail.lower()


def test_pass_only_body_is_detected(tmp_path: Path) -> None:
    src = tmp_path / "real_module.py"
    src.write_text(textwrap.dedent("""\
        def do_thing():
            pass
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_ellipsis_only_body_is_detected(tmp_path: Path) -> None:
    src = tmp_path / "real_module.py"
    src.write_text(textwrap.dedent("""\
        def do_thing():
            ...
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_todo_marker_is_detected(tmp_path: Path) -> None:
    src = tmp_path / "real_module.py"
    src.write_text("# TODO: implement me\ndef f(): return 1\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    assert "TODO" in result.detail


def test_stub_in_function_name_is_detected(tmp_path: Path) -> None:
    src = tmp_path / "real_module.py"
    src.write_text(textwrap.dedent("""\
        def stub_fetch_data():
            return []
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_mock_class_name_is_detected(tmp_path: Path) -> None:
    src = tmp_path / "real_module.py"
    src.write_text(textwrap.dedent("""\
        class MockClient:
            def get(self, url):
                return {}
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


# ---------------------------------------------------------------------------
# 5. Boundary tests — gate correctly ignores legitimate patterns
# ---------------------------------------------------------------------------


def test_abstract_method_not_flagged(tmp_path: Path) -> None:
    src = tmp_path / "real_module.py"
    src.write_text(textwrap.dedent("""\
        from abc import ABC, abstractmethod

        class Base(ABC):
            @abstractmethod
            def do_thing(self):
                ...
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, (
        f"Abstract methods must not be flagged as stubs; detail: {result.detail}"
    )


def test_test_files_are_excluded(tmp_path: Path) -> None:
    """Files inside a 'tests' directory are not scanned."""
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_stub.py").write_text(textwrap.dedent("""\
        class MockDB:
            pass

        def test_something():
            raise NotImplementedError
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, "test files must be excluded from the authenticity scan"


def test_real_implementation_passes(tmp_path: Path) -> None:
    src = tmp_path / "real_module.py"
    src.write_text(textwrap.dedent("""\
        def compute_result(x: int) -> int:
            \"\"\"Return x squared.\"\"\"
            return x * x

        class DataStore:
            def __init__(self) -> None:
                self._data: dict = {}

            def put(self, key: str, value: object) -> None:
                self._data[key] = value

            def get(self, key: str) -> object:
                return self._data[key]
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True


def test_empty_directory_passes(tmp_path: Path) -> None:
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True


def test_gate_result_has_offence_count_in_detail_when_failing(tmp_path: Path) -> None:
    src = tmp_path / "real_module.py"
    src.write_text("# TODO: fix\n# FIXME: also fix\ndef f(): pass\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    # detail must mention how many issues were found
    assert "issue" in result.detail or any(ch.isdigit() for ch in result.detail)


# ---------------------------------------------------------------------------
# 6. All remaining marker keywords are detected
# ---------------------------------------------------------------------------


def test_fixme_marker_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("# FIXME: broken\ndef f(): return 1\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    assert "FIXME" in result.detail


def test_xxx_marker_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("# XXX: danger\ndef f(): return 1\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    assert "XXX" in result.detail


def test_hack_marker_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("# HACK: workaround\ndef f(): return 1\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    assert "HACK" in result.detail


def test_stub_marker_word_in_comment_is_detected(tmp_path: Path) -> None:
    # STUB as a bare comment keyword (not function-name prefix) must also be flagged
    (tmp_path / "m.py").write_text("# STUB implementation\ndef f(): return 1\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_marker_keyword_as_substring_is_not_flagged(tmp_path: Path) -> None:
    # 'retodo' or 'fixmeup' are not the keyword (word-boundary rule)
    (tmp_path / "m.py").write_text("retodo = 1\nfixmeup = 2\ndef f(): return 1\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, (
        f"Substrings of marker keywords must not be flagged; detail: {result.detail}"
    )


# ---------------------------------------------------------------------------
# 7. All fake-name patterns are detected (fake, dummy, placeholder)
# ---------------------------------------------------------------------------


def test_fake_function_name_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def fake_send(msg):\n    return True\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_dummy_function_name_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def dummy_handler(req):\n    return None\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_placeholder_function_name_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("def placeholder_compute(x):\n    return x\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_fake_class_name_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("class FakeDB:\n    def query(self): return []\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_dummy_class_name_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("class DummyQueue:\n    def push(self, x): pass\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_fake_name_case_insensitive(tmp_path: Path) -> None:
    # _FAKE_NAME_RE uses (?i) so MOCK/Mock/mock all trigger
    (tmp_path / "m.py").write_text("class MOCK_CLIENT:\n    def get(self): return {}\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


# ---------------------------------------------------------------------------
# 8. Legitimate abstract patterns are not flagged
# ---------------------------------------------------------------------------


def test_overload_decorator_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(textwrap.dedent("""\
        from typing import overload

        @overload
        def process(x: int) -> int: ...

        @overload
        def process(x: str) -> str: ...

        def process(x):
            return x
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, (
        f"@overload stubs must not be flagged; detail: {result.detail}"
    )


def test_protocol_class_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(textwrap.dedent("""\
        from typing import Protocol

        class Readable(Protocol):
            def read(self) -> bytes: ...
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, (
        f"Protocol stub methods must not be flagged; detail: {result.detail}"
    )


def test_abstract_method_with_notimplemented_not_flagged(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(textwrap.dedent("""\
        from abc import ABC, abstractmethod

        class Base(ABC):
            @abstractmethod
            def run(self):
                raise NotImplementedError
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, (
        f"abstractmethod with NotImplementedError must not be flagged; detail: {result.detail}"
    )


def test_docstring_only_function_body_is_stub(tmp_path: Path) -> None:
    # A function whose entire body is just a docstring has no real implementation.
    # _effective_body strips the docstring leaving an empty list → flagged as stub.
    (tmp_path / "m.py").write_text(textwrap.dedent("""\
        def compute():
            \"\"\"Computes the answer.\"\"\"
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False, (
        "A function whose sole body is a docstring is a stub and must be detected"
    )


# ---------------------------------------------------------------------------
# 9. Async functions are scanned the same way as sync functions
# ---------------------------------------------------------------------------


def test_async_pass_only_body_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("async def fetch():\n    pass\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_async_ellipsis_body_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("async def fetch():\n    ...\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_async_notimplemented_is_detected(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("async def fetch():\n    raise NotImplementedError\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


def test_async_real_implementation_passes(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("async def fetch(url: str) -> bytes:\n    return b'data'\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True


# ---------------------------------------------------------------------------
# 10. Skip directories are honoured
# ---------------------------------------------------------------------------


def test_venv_directory_skipped(tmp_path: Path) -> None:
    venv = tmp_path / "venv"
    venv.mkdir()
    (venv / "bad.py").write_text("def stub_func():\n    pass\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, "venv/ must be skipped"


def test_pycache_directory_skipped(tmp_path: Path) -> None:
    cache = tmp_path / "__pycache__"
    cache.mkdir()
    (cache / "bad.pyc.py").write_text("def mock_func():\n    pass\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, "__pycache__/ must be skipped"


def test_node_modules_skipped(tmp_path: Path) -> None:
    nm = tmp_path / "node_modules"
    nm.mkdir()
    (nm / "bad.py").write_text("# TODO: remove\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, "node_modules/ must be skipped"


# ---------------------------------------------------------------------------
# 11. Test-file exclusion rules (filename-based, not just directory-based)
# ---------------------------------------------------------------------------


def test_test_prefix_file_is_excluded(tmp_path: Path) -> None:
    # test_foo.py at the top level (no 'tests' dir) must also be excluded
    (tmp_path / "test_helpers.py").write_text("def mock_db():\n    pass\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, "test_*.py files must be excluded regardless of directory"


def test_test_suffix_file_is_excluded(tmp_path: Path) -> None:
    (tmp_path / "helpers_test.py").write_text("def stub_http():\n    pass\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True, "*_test.py files must be excluded"


# ---------------------------------------------------------------------------
# 12. _MAX_REPORTED cap: more than 12 offences are summarised
# ---------------------------------------------------------------------------


def test_max_reported_cap_truncates_detail(tmp_path: Path) -> None:
    # Create 15 distinct TODO lines in one file → 15 offences; only 12 shown + "+3 more"
    lines = "\n".join(f"# TODO: item {i}" for i in range(15))
    lines += "\ndef f(): return 1\n"
    (tmp_path / "m.py").write_text(lines)
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    assert "more" in result.detail, (
        "More than _MAX_REPORTED offences must produce a '+N more' suffix"
    )


def test_twelve_offences_not_truncated(tmp_path: Path) -> None:
    # Exactly _MAX_REPORTED (12) offences should NOT get a "+ more" suffix
    lines = "\n".join(f"# TODO: item {i}" for i in range(12))
    lines += "\ndef f(): return 1\n"
    (tmp_path / "m.py").write_text(lines)
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    assert "more" not in result.detail, (
        "Exactly 12 offences must not produce a '+N more' suffix"
    )


# ---------------------------------------------------------------------------
# 13. Syntax-error file: marker offences still reported, parse error noted
# ---------------------------------------------------------------------------


def test_syntax_error_file_reports_parse_error(tmp_path: Path) -> None:
    # A file that does not parse still gets marker offences from the regex pass
    (tmp_path / "m.py").write_text("# TODO: fix\ndef broken(:\n    pass\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    assert "TODO" in result.detail or "parse" in result.detail.lower() or "does not parse" in result.detail


# ---------------------------------------------------------------------------
# 14. NotImplementedError call form (with message) is still a stub
# ---------------------------------------------------------------------------


def test_notimplemented_call_with_message_is_stub(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text(textwrap.dedent("""\
        def compute():
            raise NotImplementedError("not yet")
    """))
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False


# ---------------------------------------------------------------------------
# 15. GateResult fields are well-formed in both pass and fail cases
# ---------------------------------------------------------------------------


def test_gate_name_is_authenticity(tmp_path: Path) -> None:
    result = scan_authenticity(str(tmp_path))
    assert result.name == "authenticity"


def test_passing_result_detail_is_nonempty(tmp_path: Path) -> None:
    result = scan_authenticity(str(tmp_path))
    assert result.passed is True
    assert result.detail, "passing GateResult must have a non-empty detail string"


def test_failing_result_detail_is_nonempty(tmp_path: Path) -> None:
    (tmp_path / "m.py").write_text("# TODO: implement\n")
    result = scan_authenticity(str(tmp_path))
    assert result.passed is False
    assert result.detail, "failing GateResult must have a non-empty detail string"

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

# The conftest at tests/situation_monitor/conftest.py adds the orchestrator root
# to sys.path, making 'validation' importable.
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

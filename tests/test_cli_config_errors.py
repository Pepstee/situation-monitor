"""Real-CLI regressions for malformed watch configuration handling.

Exercises ``python -B -m monitor watch --config PATH --state PATH --cycles 1``
in subprocesses and asserts:

- JSON ``poll_interval_s`` of ``null`` or a list, plus malformed INI text,
  each exit 1 with a concise ``Watch failed`` diagnostic (no Traceback) and
  never create the SQLite state file;
- valid JSON and INI configurations still run one fixture cycle to
  completion and create the state file.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RUN_TIMEOUT = 300


def _run_watch(config_path: Path, state_path: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    argv = [
        sys.executable,
        "-B",
        "-m",
        "monitor",
        "watch",
        "--config",
        str(config_path),
        "--state",
        str(state_path),
        "--cycles",
        "1",
    ]
    return subprocess.run(
        argv,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=RUN_TIMEOUT,
    )


def _assert_clean_failure(result: subprocess.CompletedProcess, state_path: Path) -> None:
    assert result.returncode == 1, (result.stdout, result.stderr)
    assert "Watch failed" in result.stderr, result.stderr
    assert "Traceback" not in result.stderr, result.stderr
    assert result.stderr.count("Watch failed") == 1, result.stderr
    assert not state_path.exists(), f"state file created despite failure: {state_path}"


def test_watch_json_null_poll_interval_fails_without_state(tmp_path):
    config = tmp_path / "null_interval.json"
    config.write_text('{"poll_interval_s": null}\n', encoding="utf-8")
    state = tmp_path / "state" / "watch.db"
    state.parent.mkdir()
    result = _run_watch(config, state)
    _assert_clean_failure(result, state)


def test_watch_json_list_poll_interval_fails_without_state(tmp_path):
    config = tmp_path / "list_interval.json"
    config.write_text('{"poll_interval_s": [30]}\n', encoding="utf-8")
    state = tmp_path / "state" / "watch.db"
    state.parent.mkdir()
    result = _run_watch(config, state)
    _assert_clean_failure(result, state)


def test_watch_malformed_ini_fails_without_state(tmp_path):
    config = tmp_path / "malformed.ini"
    config.write_text(
        "poll_interval_s = 10\n\tindented junk without any section header\n",
        encoding="utf-8",
    )
    state = tmp_path / "state" / "watch.db"
    state.parent.mkdir()
    result = _run_watch(config, state)
    _assert_clean_failure(result, state)


def test_watch_valid_json_control_runs_and_creates_state(tmp_path):
    config = tmp_path / "valid.json"
    config.write_text(
        '{"poll_interval_s": 5, "sources": ["hackernews"]}\n',
        encoding="utf-8",
    )
    state = tmp_path / "state" / "watch.db"
    state.parent.mkdir()
    result = _run_watch(config, state)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "fixture-watch" in result.stdout, result.stdout
    assert state.is_file(), "expected the control run to create the state file"


def test_watch_valid_ini_control_runs_and_creates_state(tmp_path):
    config = tmp_path / "valid.ini"
    config.write_text(
        "[monitor]\npoll_interval_s = 5\nsources = hackernews\n",
        encoding="utf-8",
    )
    state = tmp_path / "state" / "watch.db"
    state.parent.mkdir()
    result = _run_watch(config, state)
    assert result.returncode == 0, (result.stdout, result.stderr)
    assert "fixture-watch" in result.stdout, result.stdout
    assert state.is_file(), "expected the control run to create the state file"

"""Real-process stderr-failure coverage for the watch alert delivery path.

Each test drives an actual ``python -m monitor watch`` subprocess. Stderr
write and flush failures are induced in the child interpreter through a
``sitecustomize`` module injected via ``PYTHONPATH`` so the observed delivery
path is the production one. A failure must append no receipt and leave the
persisted firing unresolved and retryable; a later real process must deliver
the pending alerts, and a third process must emit and append no duplicates.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

from monitor.storage import StateStore

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WATCH_TIMEOUT = 240

_SITECUSTOMIZE = """\
import sys


class _BrokenStderr:
    \"\"\"Fail delivery-path stderr writes/flushes, but never the interpreter's
    own bare shutdown flush, which contains no wrapper-mediated write. Failing
    that would turn the process's real exit status into Python's cleanup
    code 120 and mask the CLI's actual failure signal.\"\"\"

    def __init__(self, inner, fail):
        self._inner = inner
        self._fail = fail
        self._wrote = False

    def write(self, data):
        self._wrote = True
        if self._fail == "write":
            raise OSError("simulated stderr write failure")
        return self._inner.write(data)

    def flush(self):
        wrote = self._wrote
        self._wrote = False
        if self._fail == "flush" and wrote:
            raise OSError("simulated stderr flush failure")
        return self._inner.flush()

    def __getattr__(self, name):
        return getattr(self._inner, name)


sys.stderr = _BrokenStderr(sys.stderr, {fail!r})
"""


def _break_stderr_dir(tmp_path, fail):
    directory = tmp_path / f"break-{fail}"
    directory.mkdir()
    (directory / "sitecustomize.py").write_text(
        _SITECUSTOMIZE.format(fail=fail), encoding="utf-8"
    )
    return directory


def _run_watch(state, alert_log, *, stderr_breaker=None):
    command = [
        sys.executable,
        "-m",
        "monitor",
        "watch",
        "--state",
        str(state),
        "--cycles",
        "1",
        "--interval-seconds",
        "1",
        "--alert-threshold",
        "0",
        "--alert-log",
        str(alert_log),
    ]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    if stderr_breaker is not None:
        env["PYTHONPATH"] = str(stderr_breaker)
    return subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=WATCH_TIMEOUT,
    )


def _cycle_records(proc):
    records = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict) and "delivery_errors" in record:
            records.append(record)
    return records


def _receipts(alert_log):
    if not alert_log.exists():
        return []
    text = alert_log.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def _unresolved(state):
    with StateStore(state, read_only=True) as store:
        return store.list_alert_events(unresolved_only=True, limit=1_000_000)


def _pending_is_retryable(state, alert_log, proc):
    pending = _unresolved(state)
    assert pending, "failed delivery must leave the persisted firing unresolved"
    assert all(event.rule_name == "watch-high-score" for event in pending)
    assert _receipts(alert_log) == []
    assert proc.returncode == 1
    records = _cycle_records(proc)
    assert records and records[-1]["delivery_errors"], records


def test_stderr_write_failure_appends_no_receipt_and_keeps_firing_retryable(tmp_path):
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    breaker = _break_stderr_dir(tmp_path, "write")
    proc = _run_watch(state, alert_log, stderr_breaker=breaker)
    assert proc.returncode == 1, proc.stderr
    _pending_is_retryable(state, alert_log, proc)
    assert any(
        "simulated stderr write failure" in str(error.get("error"))
        for record in _cycle_records(proc)
        for error in record["delivery_errors"]
    )


def test_stderr_flush_failure_appends_no_receipt_and_keeps_firing_retryable(tmp_path):
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    breaker = _break_stderr_dir(tmp_path, "flush")
    proc = _run_watch(state, alert_log, stderr_breaker=breaker)
    assert proc.returncode == 1, proc.stderr
    _pending_is_retryable(state, alert_log, proc)
    assert any(
        "simulated stderr flush failure" in str(error.get("error"))
        for record in _cycle_records(proc)
        for error in record["delivery_errors"]
    )


def test_restart_delivers_pending_then_third_process_appends_no_duplicates(tmp_path):
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"

    breaker = _break_stderr_dir(tmp_path, "write")
    failed = _run_watch(state, alert_log, stderr_breaker=breaker)
    assert failed.returncode == 1, failed.stderr
    pending = _unresolved(state)
    assert pending and _receipts(alert_log) == []
    pending_ids = {event.alert_id for event in pending}

    restarted = _run_watch(state, alert_log)
    assert restarted.returncode == 0, restarted.stderr
    delivered = _receipts(alert_log)
    assert {receipt["alert_id"] for receipt in delivered} == pending_ids
    assert len(delivered) == len(pending_ids)
    assert _unresolved(state) == []
    assert restarted.stderr.count("[ALERT]") == len(pending_ids)

    before = alert_log.read_text(encoding="utf-8")
    third = _run_watch(state, alert_log)
    assert third.returncode == 0, third.stderr
    assert alert_log.read_text(encoding="utf-8") == before
    assert "[ALERT]" not in third.stderr
    records = _cycle_records(third)
    assert records and records[-1]["delivery_errors"] == []
    assert records[-1]["created_alerts"] == 0
    assert _unresolved(state) == []

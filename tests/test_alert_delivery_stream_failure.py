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

import pytest

from monitor.storage import StateStore
from schemas import Article

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WATCH_TIMEOUT = 240
BULK_ALERT_COUNT = 120
PAGE_SIZE = 100

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


def _seed_cross_page_alerts(state):
    """Persist 120 same-rule firings plus unrelated-rule interleavings."""
    with StateStore(state) as store:
        for index in range(BULK_ALERT_COUNT):
            store.save_article(
                Article(
                    url=f"https://example.com/bulk/{index}",
                    title=f"Bulk {index}",
                    source="rss",
                ),
                seen_at=1_000.0 + index,
            )
        store.conn.execute(
            "UPDATE articles SET score = 80 "
            "WHERE url LIKE 'https://example.com/bulk/%'"
        )
        store.conn.commit()
        store.evaluate_alert_rule("watch-high-score", 0, fired_at=2_000.0)
        store.conn.execute(
            "UPDATE articles SET score = 95 WHERE url IN "
            "('https://example.com/bulk/0', 'https://example.com/bulk/1', "
            "'https://example.com/bulk/2')"
        )
        store.conn.commit()
        store.evaluate_alert_rule("unrelated-rule", 90, fired_at=2_001.0)


def _unresolved_identities(state):
    return {
        event.alert_id: (event.rule_name, event.fingerprint, event.resolved)
        for event in _unresolved(state)
    }


def _watch_pending_ids(identities):
    return {
        alert_id
        for alert_id, identity in identities.items()
        if identity[0] == "watch-high-score"
    }


def _unrelated_ids(identities):
    return {
        alert_id
        for alert_id, identity in identities.items()
        if identity[0] == "unrelated-rule"
    }


def test_stderr_write_failure_commits_no_receipt_and_preserves_firings(tmp_path):
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    _seed_cross_page_alerts(state)
    breaker = _break_stderr_dir(tmp_path, "write")
    proc = _run_watch(state, alert_log, stderr_breaker=breaker)
    assert proc.returncode == 1, proc.stderr
    assert _receipts(alert_log) == []
    identities = _unresolved_identities(state)
    watch_pending = _watch_pending_ids(identities)
    unrelated = _unrelated_ids(identities)
    assert len(watch_pending) > PAGE_SIZE
    assert unrelated
    assert all(identity[2] is False for identity in identities.values())
    records = _cycle_records(proc)
    assert records and records[-1]["delivery_errors"], records
    errored = {error["alert_id"] for error in records[-1]["delivery_errors"]}
    assert errored == watch_pending
    assert unrelated.isdisjoint(errored)
    assert any(
        "simulated stderr write failure" in str(error.get("error"))
        for error in records[-1]["delivery_errors"]
    )


def test_stderr_flush_failure_commits_no_receipt_and_preserves_firings(tmp_path):
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    _seed_cross_page_alerts(state)
    breaker = _break_stderr_dir(tmp_path, "flush")
    proc = _run_watch(state, alert_log, stderr_breaker=breaker)
    assert proc.returncode == 1, proc.stderr
    assert _receipts(alert_log) == []
    identities = _unresolved_identities(state)
    watch_pending = _watch_pending_ids(identities)
    unrelated = _unrelated_ids(identities)
    assert len(watch_pending) > PAGE_SIZE
    assert unrelated
    assert all(identity[2] is False for identity in identities.values())
    records = _cycle_records(proc)
    assert records and records[-1]["delivery_errors"], records
    errored = {error["alert_id"] for error in records[-1]["delivery_errors"]}
    assert errored == watch_pending
    assert unrelated.isdisjoint(errored)
    assert any(
        "simulated stderr flush failure" in str(error.get("error"))
        for error in records[-1]["delivery_errors"]
    )


@pytest.mark.parametrize("fail", ["write", "flush"])
def test_retry_delivers_across_pages_once_and_never_resolves_firings(tmp_path, fail):
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    _seed_cross_page_alerts(state)

    breaker = _break_stderr_dir(tmp_path, fail)
    failed = _run_watch(state, alert_log, stderr_breaker=breaker)
    assert failed.returncode == 1, failed.stderr
    assert _receipts(alert_log) == []
    before = _unresolved_identities(state)
    watch_pending = _watch_pending_ids(before)
    unrelated = _unrelated_ids(before)
    assert len(watch_pending) > PAGE_SIZE
    assert unrelated

    restarted = _run_watch(state, alert_log)
    assert restarted.returncode == 0, restarted.stderr
    delivered = _receipts(alert_log)
    delivered_ids = [receipt["alert_id"] for receipt in delivered]
    assert sorted(delivered_ids) == sorted(watch_pending)
    assert len(set(delivered_ids)) == len(delivered_ids)
    assert all(receipt["rule_name"] == "watch-high-score" for receipt in delivered)
    assert unrelated.isdisjoint(delivered_ids)
    assert restarted.stderr.count("[ALERT]") == len(watch_pending)

    # Successful delivery must not resolve firings: identical unresolved
    # identities and resolution flags persist after the retry.
    after_retry = _unresolved_identities(state)
    assert after_retry == before
    assert _unresolved(state)

    log_before_third = alert_log.read_text(encoding="utf-8")
    third = _run_watch(state, alert_log)
    assert third.returncode == 0, third.stderr
    assert alert_log.read_text(encoding="utf-8") == log_before_third
    assert _receipts(alert_log) == delivered
    assert "[ALERT]" not in third.stderr
    records = _cycle_records(third)
    assert records and records[-1]["delivery_errors"] == []
    assert records[-1]["created_alerts"] == 0
    assert _unresolved_identities(state) == before

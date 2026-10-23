"""Real-process stderr-failure coverage for the watch alert delivery path.

Each test drives an actual ``python -m monitor watch`` subprocess. Stderr
write and flush failures are induced in the child interpreter through a
``sitecustomize`` module injected via ``PYTHONPATH`` so the observed delivery
path is the production one. A failure must append no receipt and leave the
persisted firing unresolved and retryable; a later real process must deliver
the pending alerts, and a third process must emit and append no duplicates.
"""
import io
import json
import os
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from monitor.alerts import TextAlertDelivery
from monitor.storage import AlertEvent, StateStore
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


_SITECUSTOMIZE_SHORT_WRITE = """\
import sys


class _ShortWriteStderr:
    \"\"\"Report a short write (fewer characters than requested) for the
    alert delivery line only, so the interpreter's own stderr output and
    bare shutdown flush are untouched. A length-checked delivery must treat
    the truncated report as a failure without flushing or emitting a
    receipt.\"\"\"

    def __init__(self, inner):
        self._inner = inner

    def write(self, data):
        if "[ALERT]" in data:
            return len(data) - 1
        return self._inner.write(data)

    def flush(self):
        return self._inner.flush()

    def __getattr__(self, name):
        return getattr(self._inner, name)


sys.stderr = _ShortWriteStderr(sys.stderr)
"""


def _break_stderr_dir(tmp_path, fail):
    directory = tmp_path / f"break-{fail}"
    directory.mkdir()
    (directory / "sitecustomize.py").write_text(
        _SITECUSTOMIZE.format(fail=fail), encoding="utf-8"
    )
    return directory


_SITECUSTOMIZE_FSYNC = """\
import os

# Fail os.fsync only for the alert receipt log's inode (identified via
# ALERT_LOG_FSYNC_TARGET), so the failure lands after append+flush in the
# delivery commit boundary while every other fsync user is untouched.
_target = os.environ.get("ALERT_LOG_FSYNC_TARGET")
_target_stat = None
if _target:
    try:
        _fd = os.open(_target, os.O_RDONLY)
        try:
            _target_stat = os.fstat(_fd)
        finally:
            os.close(_fd)
    except OSError:
        _target_stat = None

_real_fsync = os.fsync


def _fsync(fd):
    if _target_stat is not None:
        try:
            matched = os.path.samestat(os.fstat(fd), _target_stat)
        except OSError:
            matched = False
        if matched:
            raise OSError("simulated fsync failure")
    return _real_fsync(fd)


os.fsync = _fsync
"""


def _break_fsync_dir(tmp_path):
    directory = tmp_path / "break-fsync"
    directory.mkdir()
    (directory / "sitecustomize.py").write_text(
        _SITECUSTOMIZE_FSYNC, encoding="utf-8"
    )
    return directory


def _run_watch(state, alert_log, *, stderr_breaker=None, extra_env=None):
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
    ]
    # alert_log=None omits --alert-log so the production default applies:
    # the alert receipt log is derived from the SQLite state path as
    # <state>.alerts.jsonl next to the durable state file.
    if alert_log is not None:
        command += ["--alert-log", str(alert_log)]
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    if stderr_breaker is not None:
        env["PYTHONPATH"] = str(stderr_breaker)
    if extra_env:
        env.update(extra_env)
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
    """Persist 120 same-rule firings plus three unrelated-rule firings."""
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
            "UPDATE articles SET score = 95 "
            "WHERE url IN ('https://example.com/bulk/0', "
            "'https://example.com/bulk/1', 'https://example.com/bulk/2')"
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

    # Restart omitting --alert-log: pending firings must be retried from
    # durable SQLite state through the default state-derived alert log
    # (<state>.alerts.jsonl next to the durable state file).
    default_alert_log = Path(str(state) + ".alerts.jsonl")
    restarted = _run_watch(state, None)
    assert restarted.returncode == 0, restarted.stderr
    alert_log = default_alert_log
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


def test_fsync_failure_after_append_rolls_back_and_restart_retries_then_dedups(tmp_path):
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    _seed_cross_page_alerts(state)

    # Pre-existing receipt bytes: deliver exactly one of the three
    # unrelated-rule firings through the production delivery path before
    # any subprocess runs.
    unrelated_events = [
        event for event in _unresolved(state) if event.rule_name == "unrelated-rule"
    ]
    assert len(unrelated_events) == 3
    preexisting_delivery = TextAlertDelivery(
        receipt_path=alert_log, stream=io.StringIO()
    )
    assert preexisting_delivery(unrelated_events[0]) is True
    preexisting_bytes = alert_log.read_bytes()
    assert preexisting_bytes.endswith(b"\n")

    # First fresh subprocess: fsync fails after append+flush for every
    # watch-high-score delivery, so each staged receipt must be rolled back.
    breaker = _break_fsync_dir(tmp_path)
    failed = _run_watch(
        state,
        alert_log,
        stderr_breaker=breaker,
        extra_env={"ALERT_LOG_FSYNC_TARGET": str(alert_log)},
    )
    assert failed.returncode == 1, failed.stderr
    assert alert_log.read_bytes() == preexisting_bytes
    before = _unresolved_identities(state)
    watch_pending = _watch_pending_ids(before)
    assert len(watch_pending) > PAGE_SIZE
    records = _cycle_records(failed)
    assert records and records[-1]["delivery_errors"], records
    errored = {error["alert_id"] for error in records[-1]["delivery_errors"]}
    assert errored == watch_pending
    assert any(
        "simulated fsync failure" in str(error.get("error"))
        for error in records[-1]["delivery_errors"]
    )
    # The failed deliveries leave the firings unresolved and retryable.
    assert _unresolved_identities(state) == before

    # Second fresh subprocess: the same receipts are retried and delivered
    # exactly once, and the pre-existing receipt bytes survive intact.
    retried = _run_watch(state, alert_log)
    assert retried.returncode == 0, retried.stderr
    delivered = _receipts(alert_log)
    delivered_ids = [receipt["alert_id"] for receipt in delivered]
    assert sorted(delivered_ids) == sorted(
        watch_pending | {unrelated_events[0].alert_id}
    )
    assert len(set(delivered_ids)) == len(delivered_ids)
    assert retried.stderr.count("[ALERT]") == len(watch_pending)
    assert _unresolved_identities(state) == before

    # Third fresh subprocess: pure deduplication, no new bytes or stderr.
    log_before_third = alert_log.read_bytes()
    third = _run_watch(state, alert_log)
    assert third.returncode == 0, third.stderr
    assert alert_log.read_bytes() == log_before_third
    assert _receipts(alert_log) == delivered
    assert "[ALERT]" not in third.stderr
    records_third = _cycle_records(third)
    assert records_third and records_third[-1]["delivery_errors"] == []
    assert records_third[-1]["created_alerts"] == 0
    assert _unresolved_identities(state) == before


_SITECUSTOMIZE_APPEND = """\
import os
import pathlib

_target = os.environ.get("ALERT_LOG_APPEND_TARGET")
_real_open = pathlib.Path.open


class _BrokenAppend:
    # Forward everything but write; write fails, so the receipt append
    # itself raises after stderr delivery already happened.
    def __init__(self, inner):
        self._inner = inner

    def write(self, data):
        raise OSError("simulated receipt append failure")

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _open(self, mode="r", *args, **kwargs):
    handle = _real_open(self, mode, *args, **kwargs)
    if _target and "a" in mode and str(self) == _target:
        return _BrokenAppend(handle)
    return handle


pathlib.Path.open = _open
"""


def test_receipt_append_failure_after_stderr_delivery_retries_then_dedups(tmp_path):
    """The receipt log append (write) fails in a real subprocess after the
    stderr line was already delivered. The firing must stay unresolved and
    retryable with zero receipt lines; the first restart retries and records
    every firing exactly once; a third process emits no duplicate stderr and
    adds no receipt line."""

    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    _seed_cross_page_alerts(state)

    breaker_dir = tmp_path / "break-append"
    breaker_dir.mkdir()
    (breaker_dir / "sitecustomize.py").write_text(
        _SITECUSTOMIZE_APPEND, encoding="utf-8"
    )
    failed = _run_watch(
        state,
        alert_log,
        stderr_breaker=breaker_dir,
        extra_env={"ALERT_LOG_APPEND_TARGET": str(alert_log)},
    )
    assert failed.returncode == 1, failed.stderr
    # stderr delivery happened before the append failed; no receipt was kept.
    assert "[ALERT]" in failed.stderr
    assert _receipts(alert_log) == []
    assert not alert_log.exists() or alert_log.read_text(encoding="utf-8") == ""

    before = _unresolved_identities(state)
    watch_pending = _watch_pending_ids(before)
    assert watch_pending
    assert all(identity[2] is False for identity in before.values())
    records = _cycle_records(failed)
    assert records and records[-1]["delivery_errors"], records
    errored = {error["alert_id"] for error in records[-1]["delivery_errors"]}
    assert errored == watch_pending
    assert any(
        "simulated receipt append failure" in str(error.get("error"))
        for error in records[-1]["delivery_errors"]
    )

    # First restart retries the pending firings and records each exactly once.
    restarted = _run_watch(state, alert_log)
    assert restarted.returncode == 0, restarted.stderr
    delivered = _receipts(alert_log)
    delivered_ids = [receipt["alert_id"] for receipt in delivered]
    assert sorted(delivered_ids) == sorted(watch_pending)
    assert len(set(delivered_ids)) == len(delivered_ids)
    assert restarted.stderr.count("[ALERT]") == len(watch_pending)
    assert _unresolved_identities(state) == before

    # Third process: pure dedup, no duplicate stderr and no new receipt line.
    log_before_third = alert_log.read_bytes()
    third = _run_watch(state, alert_log)
    assert third.returncode == 0, third.stderr
    assert alert_log.read_bytes() == log_before_third
    assert _receipts(alert_log) == delivered
    assert "[ALERT]" not in third.stderr
    records_third = _cycle_records(third)
    assert records_third and records_third[-1]["delivery_errors"] == []
    assert records_third[-1]["created_alerts"] == 0
    assert _unresolved_identities(state) == before


def _short_write_stderr_dir(tmp_path):
    directory = tmp_path / "break-short-write"
    directory.mkdir()
    (directory / "sitecustomize.py").write_text(
        _SITECUSTOMIZE_SHORT_WRITE, encoding="utf-8"
    )
    return directory


def test_stderr_short_write_commits_no_receipt_and_preserves_firings(tmp_path):
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    _seed_cross_page_alerts(state)
    breaker = _short_write_stderr_dir(tmp_path)
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
        "short write to alert stderr stream" in str(error.get("error"))
        for error in records[-1]["delivery_errors"]
    )


_SITECUSTOMIZE_RECEIPT_SHORT_WRITE = """\
import os
import pathlib

_target = os.environ.get("ALERT_LOG_SHORTWRITE_TARGET")
_real_open = pathlib.Path.open


class _ShortWriteAppend:
    \"\"\"Write a real prefix of the receipt line through the actual append
    handle, then report a short count without raising, so the length-checked
    receipt commit must treat the truncated append as a delivery failure and
    roll the log back to its pre-commit size.\"\"\"

    def __init__(self, inner):
        self._inner = inner

    def write(self, data):
        if not data:
            return 0
        return self._inner.write(data[:-1])

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _open(self, mode="r", *args, **kwargs):
    handle = _real_open(self, mode, *args, **kwargs)
    if _target and "a" in mode and str(self) == _target:
        return _ShortWriteAppend(handle)
    return handle


pathlib.Path.open = _open
"""


def test_receipt_log_short_write_in_subprocess_preserves_bytes_and_firing(tmp_path):
    """The receipt-file short-count branch runs in a real subprocess: the
    shim writes a real prefix through the actual append handle and returns a
    short count without raising. Delivery must fail, the pre-existing
    receipt bytes must survive exactly, no new receipt may be committed and
    the firing must stay unresolved."""
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    _seed_cross_page_alerts(state)

    unrelated_events = [
        event for event in _unresolved(state) if event.rule_name == "unrelated-rule"
    ]
    assert len(unrelated_events) == 3
    preexisting_delivery = TextAlertDelivery(
        receipt_path=alert_log, stream=io.StringIO()
    )
    assert preexisting_delivery(unrelated_events[0]) is True
    preexisting_bytes = alert_log.read_bytes()
    assert preexisting_bytes.endswith(b"\n")

    breaker_dir = tmp_path / "break-receipt-short-write"
    breaker_dir.mkdir()
    (breaker_dir / "sitecustomize.py").write_text(
        _SITECUSTOMIZE_RECEIPT_SHORT_WRITE, encoding="utf-8"
    )
    failed = _run_watch(
        state,
        alert_log,
        stderr_breaker=breaker_dir,
        extra_env={"ALERT_LOG_SHORTWRITE_TARGET": str(alert_log)},
    )
    assert failed.returncode == 1, failed.stderr
    assert "[ALERT]" in failed.stderr
    assert alert_log.read_bytes() == preexisting_bytes
    delivered = _receipts(alert_log)
    assert [receipt["alert_id"] for receipt in delivered] == [
        unrelated_events[0].alert_id
    ]

    before = _unresolved_identities(state)
    watch_pending = _watch_pending_ids(before)
    assert len(watch_pending) > PAGE_SIZE
    records = _cycle_records(failed)
    assert records and records[-1]["delivery_errors"], records
    errored = {error["alert_id"] for error in records[-1]["delivery_errors"]}
    assert errored == watch_pending
    assert any(
        "short write to alert receipt log" in str(error.get("error"))
        for error in records[-1]["delivery_errors"]
    )
    after = _unresolved_identities(state)
    assert after == before
    assert all(identity[2] is False for identity in after.values())


_SITECUSTOMIZE_CLOSE_FAIL = """\
import os
import pathlib

_target = os.environ.get("ALERT_LOG_CLOSEFAIL_TARGET")
_real_open = pathlib.Path.open


class _CloseFailAppend:
    \"\"\"Close the real append handle (so the fsynced receipt stays durable)
    and then raise, so the commit handshake fails after durability: the
    firing stays retryable while a valid durable receipt remains in the
    log for a revalidating recovery load.\"\"\"

    def __init__(self, inner):
        self._inner = inner

    def close(self):
        self._inner.close()
        raise OSError("simulated receipt close failure")

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _open(self, mode="r", *args, **kwargs):
    handle = _real_open(self, mode, *args, **kwargs)
    if _target and "a" in mode and str(self) == _target:
        return _CloseFailAppend(handle)
    return handle


pathlib.Path.open = _open
"""


def test_close_failure_after_fsync_keeps_durable_receipt_without_duplicates(tmp_path):
    """fsync succeeds and then close raises in a real subprocess: the
    durable receipt stays valid in the log while the delivery errors. A
    real process restart must recover it by full-log revalidation and a
    third process must dedup again without emitting stderr or appending."""
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    _seed_cross_page_alerts(state)

    breaker_dir = tmp_path / "break-close-fail"
    breaker_dir.mkdir()
    (breaker_dir / "sitecustomize.py").write_text(
        _SITECUSTOMIZE_CLOSE_FAIL, encoding="utf-8"
    )
    failed = _run_watch(
        state,
        alert_log,
        stderr_breaker=breaker_dir,
        extra_env={"ALERT_LOG_CLOSEFAIL_TARGET": str(alert_log)},
    )
    assert failed.returncode == 1, failed.stderr
    before = _unresolved_identities(state)
    watch_pending = _watch_pending_ids(before)
    assert len(watch_pending) > PAGE_SIZE
    durable = _receipts(alert_log)
    durable_ids = [receipt["alert_id"] for receipt in durable]
    assert sorted(durable_ids) == sorted(watch_pending)
    assert len(set(durable_ids)) == len(durable_ids)
    assert failed.stderr.count("[ALERT]") == len(watch_pending)
    records = _cycle_records(failed)
    assert records and records[-1]["delivery_errors"], records
    errored = {error["alert_id"] for error in records[-1]["delivery_errors"]}
    assert errored == watch_pending
    assert any(
        "simulated receipt close failure" in str(error.get("error"))
        for error in records[-1]["delivery_errors"]
    )
    assert _unresolved_identities(state) == before

    # Real process restart: the durable receipts are recovered, so nothing
    # is re-emitted on stderr and no receipt line is appended twice.
    log_before_restart = alert_log.read_bytes()
    restarted = _run_watch(state, alert_log)
    assert restarted.returncode == 0, restarted.stderr
    assert alert_log.read_bytes() == log_before_restart
    assert _receipts(alert_log) == durable
    assert "[ALERT]" not in restarted.stderr
    records_restart = _cycle_records(restarted)
    assert records_restart and records_restart[-1]["delivery_errors"] == []
    assert records_restart[-1]["created_alerts"] == 0
    assert _unresolved_identities(state) == before

    # Third process: pure dedup again, still no duplicates.
    third = _run_watch(state, alert_log)
    assert third.returncode == 0, third.stderr
    assert alert_log.read_bytes() == log_before_restart
    assert _receipts(alert_log) == durable
    assert "[ALERT]" not in third.stderr
    records_third = _cycle_records(third)
    assert records_third and records_third[-1]["delivery_errors"] == []
    assert records_third[-1]["created_alerts"] == 0
    assert _unresolved_identities(state) == before


def _receipt_event(alert_id=901, **overrides):
    values = dict(
        alert_id=alert_id,
        rule_name="watch-high-score",
        threshold=0,
        severity="warning",
        fingerprint="fp-receipt",
        url="https://example.com/receipt",
        title="Receipt",
        source="rss",
        score=90,
        fired_at=2_500.0,
        resolved=False,
    )
    values.update(overrides)
    return AlertEvent(**values)


def _receipt_line(event):
    return json.dumps(asdict(event), ensure_ascii=False, sort_keys=True)


def _write_log(alert_log, *lines):
    alert_log.write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.mark.parametrize(
    "corruption",
    [
        "truncated-final-newline",
        "malformed-json",
        "schema-incomplete",
        "conflicting-duplicate",
        "valid-prefix-then-conflicting",
        "valid-prefix-then-malformed",
    ],
)
def test_malformed_receipt_log_refuses_loading_across_repeated_retries(
    tmp_path, corruption
):
    """A receipt log with an incomplete terminal newline, a malformed or
    schema-incomplete entry, a conflicting duplicate alert identity, or a
    valid matching prefix followed by a conflicting or malformed later
    entry must refuse to load. Repeated retries keep refusing and never
    reuse a partially cached valid prefix, and the log bytes stay intact."""
    alert_log = tmp_path / "alerts.jsonl"
    event = _receipt_event(901)
    conflict = _receipt_event(901, severity="critical")
    if corruption == "truncated-final-newline":
        alert_log.write_text(_receipt_line(event), encoding="utf-8")
    elif corruption == "malformed-json":
        _write_log(alert_log, "{not json")
    elif corruption == "schema-incomplete":
        incomplete = {
            key: value for key, value in asdict(event).items() if key != "severity"
        }
        _write_log(alert_log, json.dumps(incomplete))
    elif corruption == "conflicting-duplicate":
        _write_log(alert_log, _receipt_line(event), _receipt_line(conflict))
    elif corruption == "valid-prefix-then-conflicting":
        _write_log(alert_log, _receipt_line(event), _receipt_line(conflict))
    else:
        _write_log(alert_log, _receipt_line(event), "{not json")
    original = alert_log.read_bytes()

    for _ in range(3):
        with pytest.raises(ValueError):
            TextAlertDelivery(receipt_path=alert_log)
    assert alert_log.read_bytes() == original


def test_receipt_resolved_flag_alone_is_not_a_delivery_identity_conflict(tmp_path):
    """Records that differ only in the resolved flag share one
    _receipt_identity, so a resolved receipt dedups its unresolved firing
    without stderr emission or a second receipt line."""
    alert_log = tmp_path / "alerts.jsonl"
    event = _receipt_event(901)
    resolved_variant = _receipt_event(901, resolved=True)
    _write_log(alert_log, _receipt_line(resolved_variant))
    original = alert_log.read_bytes()
    stream = io.StringIO()
    delivery = TextAlertDelivery(receipt_path=alert_log, stream=stream)
    assert delivery(event) is False
    assert stream.getvalue() == ""
    assert alert_log.read_bytes() == original


def test_conflicting_delivery_identity_in_log_is_rejected_on_every_retry(tmp_path):
    """A receipt whose delivery identity differs from the firing's (here:
    severity) must raise on every retry, before any stderr delivery, and
    must never append a second receipt line."""
    alert_log = tmp_path / "alerts.jsonl"
    event = _receipt_event(901)
    _write_log(alert_log, _receipt_line(_receipt_event(901, severity="critical")))
    original = alert_log.read_bytes()
    stream = io.StringIO()
    delivery = TextAlertDelivery(receipt_path=alert_log, stream=stream)
    for _ in range(3):
        with pytest.raises(ValueError):
            delivery(event)
    assert stream.getvalue() == ""
    assert alert_log.read_bytes() == original


@pytest.mark.parametrize(
    "suffix_lines",
    [
        pytest.param(["{not json"], id="malformed-suffix"),
        pytest.param(
            [
                _receipt_line(_receipt_event(902, severity="critical")),
            ],
            id="conflicting-suffix",
        ),
    ],
)
def test_same_instance_pending_recovery_revalidates_full_log_before_cached_dedup(
    tmp_path, monkeypatch, suffix_lines
):
    """Same-instance pending-recovery regression.

    On one TextAlertDelivery instance: deliver and cache A, then deliver B
    with a successful fsync and an injected close error. B's receipt stays
    durable while in-memory state lags, leaving recovery pending. After a
    malformed or conflicting suffix is appended, two retries of the cached
    A must each rerun full-log validation and refuse delivery (raising,
    emitting no stderr, appending nothing, keeping the recovery marker set)
    instead of returning from the cached dedup fast path. Restoring a valid
    receipt log lets the same instance recover by revalidation and dedup
    both A and B without stderr or new bytes, while a fresh firing still
    delivers."""
    alert_log = tmp_path / "alerts.jsonl"
    stream = io.StringIO()
    delivery = TextAlertDelivery(receipt_path=alert_log, stream=stream)

    event_a = _receipt_event(901)
    event_b = _receipt_event(902)
    event_c = _receipt_event(903)

    assert delivery(event_a) is True
    assert delivery._receipts.keys() == {event_a.alert_id}
    valid_bytes = alert_log.read_bytes()
    assert valid_bytes.endswith(b"\n")
    assert stream.getvalue().count("[ALERT]") == 1

    class _CloseFailOnceHandle:
        """Real per-instance wrapper around the actual receipt append handle.

        Every write/flush/truncate/fileno call delegates to the real file
        object (so the real fsync and fstat in the commit boundary run on
        the real descriptor), and close closes the real handle first; after
        that successful underlying close it raises the injected close error
        exactly once, so the fsynced receipt stays durable while the commit
        handshake reports failure. The built-in io.TextIOWrapper.close is
        never patched: built-in types are immutable and the failure must be
        scoped to this one real receipt handle."""

        def __init__(self, inner):
            self._inner = inner
            self._raise_once = True

        def write(self, data):
            return self._inner.write(data)

        def flush(self):
            return self._inner.flush()

        def truncate(self, size):
            return self._inner.truncate(size)

        def fileno(self):
            return self._inner.fileno()

        def close(self):
            self._inner.close()
            if self._raise_once:
                self._raise_once = False
                raise OSError("simulated receipt close failure")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    real_path_open = Path.open

    def open_receipt_with_close_failure(path, *args, **kwargs):
        handle = real_path_open(path, *args, **kwargs)
        mode = args[0] if args else kwargs.get("mode", "r")
        if "a" in mode and path == alert_log:
            return _CloseFailOnceHandle(handle)
        return handle

    monkeypatch.setattr(Path, "open", open_receipt_with_close_failure)
    with pytest.raises(OSError, match="simulated receipt close failure"):
        delivery(event_b)
    monkeypatch.undo()

    # fsync succeeded before the close error: B is durable on disk but the
    # in-memory cache never advanced, so recovery is pending on this
    # instance for the next attempt.
    pending_bytes = alert_log.read_bytes()
    pending_receipts = _receipts(alert_log)
    assert [receipt["alert_id"] for receipt in pending_receipts] == [901, 902]
    assert delivery._receipts.keys() == {event_a.alert_id}
    assert delivery._durable_unacknowledged is True
    stderr_so_far = stream.getvalue()
    # B's stderr line was fully written and flushed before the injected
    # close error, so the distinct-event stream count rose from 1 to 2.
    assert stderr_so_far.count("[ALERT]") == 2

    # A malformed or conflicting suffix poisons the whole log: two retries
    # of the cached A must each rerun full-log validation and refuse
    # delivery rather than hit the cached dedup fast path.
    with alert_log.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(suffix_lines) + "\n")
    corrupted_bytes = alert_log.read_bytes()

    for _ in range(2):
        with pytest.raises(ValueError):
            delivery(event_a)
        assert delivery._durable_unacknowledged is True
        assert delivery._receipts.keys() == {event_a.alert_id}
        assert alert_log.read_bytes() == corrupted_bytes
        assert stream.getvalue() == stderr_so_far

    # Restore a valid receipt log: the same instance recovers through a
    # full revalidating load and deduplicates both the cached A and the
    # durable-but-unacknowledged B without stderr or new bytes.
    alert_log.write_bytes(pending_bytes)
    assert delivery(event_a) is False
    assert delivery(event_b) is False
    assert delivery._durable_unacknowledged is False
    assert delivery._receipts.keys() == {901, 902}
    assert alert_log.read_bytes() == pending_bytes
    assert stream.getvalue() == stderr_so_far

    # Same-instance delivery stays live after recovery: a fresh firing is
    # still delivered exactly once with one stderr line and one receipt.
    assert delivery(event_c) is True
    # Exact +1 transitions across distinct events: A emitted the first
    # alert, B's durable append emitted the second before the injected
    # close error, and fresh C emits the third, for an isolated total of 3.
    assert stream.getvalue().count("[ALERT]") == stderr_so_far.count("[ALERT]") + 1
    assert stream.getvalue().count("[ALERT]") == 3
    assert "id=903" in stream.getvalue()
    recovered = _receipts(alert_log)
    assert [receipt["alert_id"] for receipt in recovered] == [901, 902, 903]


_SITECUSTOMIZE_ORDER_TRACE = '''\
import os
import pathlib
import sys

_trace_path = os.environ.get("ALERT_ORDER_TRACE")
_target = os.environ.get("ALERT_LOG_ORDER_TARGET")
_real_open = pathlib.Path.open


def _record(marker):
    if _trace_path:
        with open(_trace_path, "a", encoding="utf-8") as handle:
            handle.write(marker + "\\n")


class _TracedAppend:
    def __init__(self, inner):
        self._inner = inner

    def write(self, data):
        _record("receipt-append-write")
        return self._inner.write(data)

    def flush(self):
        _record("receipt-flush")
        return self._inner.flush()

    def close(self):
        _record("receipt-close")
        return self._inner.close()

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _open(self, mode="r", *args, **kwargs):
    handle = _real_open(self, mode, *args, **kwargs)
    if "a" in mode and _target and str(self) == _target:
        _record("receipt-open")
        return _TracedAppend(handle)
    return handle


pathlib.Path.open = _open

_real_stderr_write = sys.stderr.write
_real_stderr_flush = sys.stderr.flush


_pending_alert_write = False


def _stderr_write(data):
    global _pending_alert_write
    if "[ALERT]" in data:
        _record("stderr-write")
        _pending_alert_write = True
    return _real_stderr_write(data)


def _stderr_flush():
    global _pending_alert_write
    # Only the alert delivery path's own flush is part of the traced commit
    # ordering; the interpreter's and logging's unrelated stderr flushes
    # carry no pending alert write and would otherwise desynchronize the
    # per-delivery marker cycle.
    if _pending_alert_write:
        _record("stderr-flush")
        _pending_alert_write = False
    return _real_stderr_flush()


sys.stderr.write = _stderr_write
sys.stderr.flush = _stderr_flush
'''

_ORDER_CYCLE = [
    "receipt-open",
    "stderr-write",
    "stderr-flush",
    "receipt-append-write",
    "receipt-flush",
    "receipt-close",
]


def _run_traced_watch_cycles(state, alert_log, cycles, *, stderr_breaker=None, extra_env=None):
    """Run a real ``python -m monitor watch`` subprocess for N cycles so a
    single delivery instance (one process, one TextAlertDelivery) spans
    several watch cycles for same-instance commit-boundary evidence."""

    command = [
        sys.executable,
        "-m",
        "monitor",
        "watch",
        "--state",
        str(state),
        "--cycles",
        str(cycles),
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
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=WATCH_TIMEOUT,
    )


def test_production_delivery_order_traced_in_real_process(tmp_path):
    """A real watch subprocess must follow the strict production ordering:
    open the receipt log, write and flush stderr, append the receipt (with
    its flush inside the traced transaction), close the receipt log, then
    advance in-memory delivery state.

    The seeded watch identities are captured before the first real watch;
    the first-cycle fixture-created watch IDs are derived from the actual
    post-cycle persisted state (never hardcoded), and every seeded identity
    plus every derived first-cycle identity must be receipted exactly once
    while unrelated-rule IDs are excluded. Stage 5 is proven inside the same
    delivery instance: a second cycle of the same traced process must dedup
    entirely from in-memory state (zero created alerts, zero deliveries,
    zero new trace markers), which is only possible because that state
    advanced strictly after the closed receipt commit. An independent third
    real process then deduplicates with no new receipts or stderr."""

    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    trace = tmp_path / "order.trace"
    _seed_cross_page_alerts(state)

    # Capture the initially seeded watch identities before any cycle runs.
    before = _unresolved_identities(state)
    seeded_watch_ids = _watch_pending_ids(before)
    seeded_unrelated_ids = _unrelated_ids(before)
    assert seeded_watch_ids
    assert seeded_unrelated_ids
    assert seeded_watch_ids.isdisjoint(seeded_unrelated_ids)

    breaker_dir = tmp_path / "trace-order"
    breaker_dir.mkdir()
    (breaker_dir / "sitecustomize.py").write_text(
        _SITECUSTOMIZE_ORDER_TRACE, encoding="utf-8"
    )
    # Two cycles, one process: the delivery instance is shared, so the
    # second cycle's zero-delivery behaviour evidences the same-instance
    # state transition (stage 5) without any in-process simulation.
    traced = _run_traced_watch_cycles(
        state,
        alert_log,
        2,
        stderr_breaker=breaker_dir,
        extra_env={
            "ALERT_LOG_ORDER_TARGET": str(alert_log),
            "ALERT_ORDER_TRACE": str(trace),
        },
    )
    assert traced.returncode == 0, traced.stderr

    # Derive the watch identities from actual post-cycle state: seeded
    # firings plus the first-cycle fixture-created firings (delivery never
    # resolves firings, so every delivered firing stays unresolved here).
    after = _unresolved_identities(state)
    post_watch_ids = _watch_pending_ids(after)
    post_unrelated_ids = _unrelated_ids(after)
    fixture_created_ids = post_watch_ids - seeded_watch_ids
    assert post_watch_ids == seeded_watch_ids | fixture_created_ids
    assert seeded_watch_ids <= post_watch_ids
    assert post_unrelated_ids == seeded_unrelated_ids
    assert all(identity[2] is False for identity in after.values())

    cycle_records = _cycle_records(traced)
    assert len(cycle_records) == 2, cycle_records
    first_cycle, second_cycle = cycle_records
    assert first_cycle["created_alerts"] == len(fixture_created_ids)
    assert first_cycle["delivery_errors"] == []
    # Same-instance proof: the second cycle of the same delivery instance
    # created nothing and delivered nothing, so in-memory state had already
    # advanced only after the successful receipt closes of cycle one.
    assert second_cycle["created_alerts"] == 0
    assert second_cycle["delivery_errors"] == []

    # Every watch identity (seeded and derived) exactly once; unrelated IDs
    # never appear; no duplicate receipts at all.
    receipts = _receipts(alert_log)
    receipt_ids = [receipt["alert_id"] for receipt in receipts]
    assert sorted(receipt_ids) == sorted(post_watch_ids)
    assert len(set(receipt_ids)) == len(receipt_ids)
    for seeded_id in seeded_watch_ids:
        assert receipt_ids.count(seeded_id) == 1
    for created_id in fixture_created_ids:
        assert receipt_ids.count(created_id) == 1
    assert post_unrelated_ids.isdisjoint(receipt_ids)
    assert all(receipt["rule_name"] == "watch-high-score" for receipt in receipts)
    assert traced.stderr.count("[ALERT]") == len(post_watch_ids)

    # The traced markers expose stages 1-4 of the commit boundary for every
    # delivery, each cycle strictly: open, stderr write, stderr flush,
    # receipt append write, receipt flush, receipt close.
    markers = [
        line for line in trace.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    assert markers, "order trace must capture the delivery path"
    assert len(markers) == len(post_watch_ids) * len(_ORDER_CYCLE)
    for start in range(0, len(markers), len(_ORDER_CYCLE)):
        assert markers[start : start + len(_ORDER_CYCLE)] == _ORDER_CYCLE

    # Independent real process: pure deduplication, no new bytes or stderr.
    log_before_third = alert_log.read_bytes()
    third = _run_traced_watch_cycles(state, alert_log, 1)
    assert third.returncode == 0, third.stderr
    assert alert_log.read_bytes() == log_before_third
    assert _receipts(alert_log) == receipts
    assert "[ALERT]" not in third.stderr
    records_third = _cycle_records(third)
    assert records_third and records_third[-1]["delivery_errors"] == []
    assert records_third[-1]["created_alerts"] == 0
    after_third = _unresolved_identities(state)
    assert _watch_pending_ids(after_third) == post_watch_ids
    assert _unrelated_ids(after_third) == seeded_unrelated_ids
    assert all(identity[2] is False for identity in after_third.values())


_SITECUSTOMIZE_BUFFERED_PARTIAL = """\
import os
import pathlib

_target = os.environ.get("ALERT_LOG_BUFFERED_TARGET")
_real_open = pathlib.Path.open


class _BufferedFailAppend:
    \"\"\"Stage a real partial prefix of the receipt line into a private
    buffer and then fail the write. The handle's own truncate always fails,
    and close performs a late real flush that writes the buffered partial
    bytes through to the underlying file before closing it. Only an
    fd-level rollback that duplicates the descriptor before close, lets
    close flush what it will and then forces the file back to its
    pre-commit size can keep the prior receipt bytes exactly unchanged.\"\"\"

    def __init__(self, inner):
        self._inner = inner
        self._buffered = ""
        self._flushed = False

    def write(self, data):
        if data:
            self._buffered = data[: len(data) // 2]
        raise OSError("simulated buffered receipt write failure")

    def flush(self):
        return self._inner.flush()

    def truncate(self, size):
        raise OSError("simulated receipt truncate failure")

    def close(self):
        if not self._flushed:
            self._flushed = True
            if self._buffered:
                self._inner.write(self._buffered)
                self._inner.flush()
        return self._inner.close()

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _open(self, mode="r", *args, **kwargs):
    handle = _real_open(self, mode, *args, **kwargs)
    if _target and "a" in mode and str(self) == _target:
        return _BufferedFailAppend(handle)
    return handle


pathlib.Path.open = _open
"""


def test_buffered_partial_write_failed_truncate_late_close_flush_preserves_bytes(
    tmp_path,
):
    """Real-subprocess rollback regression for the buffered partial append.

    A real ``python -m monitor watch`` child appends receipts through a
    handle that buffers a real partial prefix of the receipt line and fails
    the write; the handle's own truncate is injected to fail, and its close
    performs a late real flush of the buffered partial bytes back into the
    file. The fd-level rollback must still leave the prior receipt bytes
    exactly unchanged, commit no successful durable delivery receipt and
    keep the persisted SQLite firing rows present, unresolved and
    retryable. A subsequent real process must retry and deliver every
    pending firing exactly once, and a third real process must deduplicate
    with no new receipt bytes and no stderr emission."""
    state = tmp_path / "state.sqlite3"
    alert_log = tmp_path / "alerts.jsonl"
    _seed_cross_page_alerts(state)

    # Pre-existing receipt bytes: deliver exactly one of the three
    # unrelated-rule firings through the production delivery path before
    # any subprocess runs, so the rollback must provably preserve them.
    unrelated_events = [
        event for event in _unresolved(state) if event.rule_name == "unrelated-rule"
    ]
    assert len(unrelated_events) == 3
    preexisting_delivery = TextAlertDelivery(
        receipt_path=alert_log, stream=io.StringIO()
    )
    assert preexisting_delivery(unrelated_events[0]) is True
    preexisting_bytes = alert_log.read_bytes()
    assert preexisting_bytes.endswith(b"\n")

    breaker_dir = tmp_path / "break-buffered-partial"
    breaker_dir.mkdir()
    (breaker_dir / "sitecustomize.py").write_text(
        _SITECUSTOMIZE_BUFFERED_PARTIAL, encoding="utf-8"
    )
    failed = _run_watch(
        state,
        alert_log,
        stderr_breaker=breaker_dir,
        extra_env={"ALERT_LOG_BUFFERED_TARGET": str(alert_log)},
    )
    assert failed.returncode == 1, failed.stderr
    # stderr delivery happened before the failed buffered append; the late
    # close flush and failed handle truncate left no partial durable tail.
    assert "[ALERT]" in failed.stderr
    assert alert_log.read_bytes() == preexisting_bytes
    delivered_before = _receipts(alert_log)
    assert [receipt["alert_id"] for receipt in delivered_before] == [
        unrelated_events[0].alert_id
    ]

    before = _unresolved_identities(state)
    watch_pending = _watch_pending_ids(before)
    assert len(watch_pending) > PAGE_SIZE
    records = _cycle_records(failed)
    assert records and records[-1]["delivery_errors"], records
    errored = {error["alert_id"] for error in records[-1]["delivery_errors"]}
    assert errored == watch_pending
    assert any(
        "simulated buffered receipt write failure" in str(error.get("error"))
        for error in records[-1]["delivery_errors"]
    )
    # The failed deliveries leave every firing unresolved and retryable.
    assert _unresolved_identities(state) == before
    assert all(identity[2] is False for identity in before.values())

    # Second fresh subprocess: the pending firings are retried and delivered
    # exactly once, and the pre-existing receipt bytes survive intact as the
    # log's leading line.
    retried = _run_watch(state, alert_log)
    assert retried.returncode == 0, retried.stderr
    delivered = _receipts(alert_log)
    delivered_ids = [receipt["alert_id"] for receipt in delivered]
    assert sorted(delivered_ids) == sorted(
        watch_pending | {unrelated_events[0].alert_id}
    )
    assert len(set(delivered_ids)) == len(delivered_ids)
    assert delivered[0]["alert_id"] == unrelated_events[0].alert_id
    assert retried.stderr.count("[ALERT]") == len(watch_pending)
    assert _unresolved_identities(state) == before

    # Third fresh subprocess: pure deduplication, no new bytes or stderr.
    log_before_third = alert_log.read_bytes()
    third = _run_watch(state, alert_log)
    assert third.returncode == 0, third.stderr
    assert alert_log.read_bytes() == log_before_third
    assert _receipts(alert_log) == delivered
    assert "[ALERT]" not in third.stderr
    records_third = _cycle_records(third)
    assert records_third and records_third[-1]["delivery_errors"] == []
    assert records_third[-1]["created_alerts"] == 0
    assert _unresolved_identities(state) == before

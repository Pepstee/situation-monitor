"""Restart and declaration-path checks for alert delivery."""

import io
import json
from dataclasses import asdict, replace

from monitor.alerts import TextAlertDelivery
from monitor.storage import AlertEvent


def event(alert_id: int = 7) -> AlertEvent:
    return AlertEvent(
        alert_id,
        "urgent",
        70,
        "warning",
        f"fingerprint-{alert_id}",
        "https://example.test/story",
        "Story",
        "hn",
        80,
        123.0,
        False,
    )


def test_first_delivery_emits_stderr_and_writes_receipt(tmp_path, capsys):
    log_path = tmp_path / "alerts.jsonl"
    sink = TextAlertDelivery(log_path)
    assert sink(event()) is True
    err = capsys.readouterr().err
    assert len(err.splitlines()) == 1
    assert "[ALERT] id=7" in err and "rule='urgent'" in err
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert records == [asdict(event())]


def test_reopening_same_state_suppresses_unchanged_active_alert(tmp_path, capsys):
    log_path = tmp_path / "alerts.jsonl"
    first = TextAlertDelivery(log_path)
    assert first(event()) is True
    capsys.readouterr()

    reopened = TextAlertDelivery(log_path)
    assert reopened(event()) is False
    assert reopened(event()) is False
    assert capsys.readouterr().err == ""
    assert len(log_path.read_text().splitlines()) == 1


def test_previously_emitted_active_alert_is_suppressed_across_restart(tmp_path, capsys):
    log_path = tmp_path / "alerts.jsonl"
    delivered = TextAlertDelivery(log_path)
    assert delivered(event()) is True
    capsys.readouterr()

    # A fresh instance loaded from the persisted receipt log (the restart
    # path) suppresses the unchanged active firing without stderr output.
    restarted = TextAlertDelivery(log_path)
    assert restarted(event()) is False
    assert restarted(replace(event(), resolved=True)) is False
    assert capsys.readouterr().err == ""
    assert len(log_path.read_text().splitlines()) == 1


def test_delivery_resumes_after_alert_resolves_and_fires_again(tmp_path, capsys):
    log_path = tmp_path / "alerts.jsonl"
    resolved = type(event())(
        7,
        "urgent",
        70,
        "warning",
        "fingerprint-7",
        "https://example.test/story",
        "Story",
        "hn",
        80,
        123.0,
        True,
    )
    sink = TextAlertDelivery(log_path)
    assert sink(event()) is True
    assert sink(resolved) is False
    capsys.readouterr()

    assert sink(event(alert_id=8)) is True
    err = capsys.readouterr().err
    assert "[ALERT] id=8" in err
    assert len(err.splitlines()) == 1
    records = [json.loads(line) for line in log_path.read_text().splitlines()]
    assert [r["alert_id"] for r in records] == [7, 8]
    assert records[0]["resolved"] is False


def test_restart_with_only_stream_repeats_without_state():
    stream = io.StringIO()
    assert TextAlertDelivery(stream=stream)(event()) is True
    stream2 = io.StringIO()
    assert TextAlertDelivery(stream=stream2)(event()) is True
    assert "[ALERT] id=7" in stream2.getvalue()

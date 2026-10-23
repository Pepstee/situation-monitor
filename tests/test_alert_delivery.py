import io
import json
import pathlib
import re
from dataclasses import asdict, replace

import pytest

from monitor.alerts import AlertManager, AlertRule, TextAlertDelivery
from monitor.storage import AlertEvent


def event():
    return AlertEvent(7, "urgent", 70, "warning", "fingerprint", "https://example.test/a\nspoof", "Story\nspoof", "hn", 80, 123.0, False)


def _wrapped_event(alert_id, title="Story"):
    return replace(event(), alert_id=alert_id, title=title)


def test_callbacks_threshold_dedup_reset_and_removal():
    seen = []
    manager = AlertManager()
    rule = AlertRule("urgent", 70, lambda item, score: seen.append((item, score)))
    manager.add_rule(rule)
    item = {"url": "https://example.test/story", "title": "Story"}
    assert manager.evaluate(item, 20) == []
    assert manager.evaluate(item, 70) == ["urgent"]
    assert manager.evaluate(dict(item), 90) == []
    manager.reset_all()
    assert manager.evaluate(item, 80) == ["urgent"]
    manager.remove_rule("urgent")
    assert manager.evaluate({"url": "other"}, 99) == []
    assert len(seen) == 2


def test_failed_callback_retries_while_other_rules_continue(caplog):
    attempts = []

    def flaky(item, score):
        attempts.append(score)
        if len(attempts) == 1:
            raise OSError("delivery unavailable")

    manager = AlertManager()
    manager.add_rule(AlertRule("flaky", 70, flaky))
    manager.add_rule(AlertRule("other", 70, lambda item, score: None))
    item = {"url": "https://example.test/story"}
    assert manager.evaluate(item, 70) == ["other"]
    assert "remains retryable" in caplog.text
    assert manager.evaluate(item, 70) == ["flaky"]
    assert manager.evaluate(item, 70) == []
    assert attempts == [70, 70]


def test_invalid_batches_fail_before_callbacks_and_duplicate_names_rejected():
    calls = []
    manager = AlertManager()
    rule = AlertRule("a", 0, lambda *args: calls.append(args))
    manager.add_rule(rule)
    with pytest.raises(ValueError, match="duplicate"):
        manager.add_rule(rule)
    with pytest.raises(ValueError, match="equal lengths"):
        manager.evaluate_batch([{}, {}], [70])
    with pytest.raises(ValueError, match="finite"):
        manager.evaluate_batch([{}, {}], [70, float("nan")])
    assert calls == []
    assert manager.evaluate_batch([{"url": "a"}, {"url": "b"}], [0, 100]) == {0: ["a"], 1: ["a"]}
    for threshold in (-1, 101, float("nan"), True):
        with pytest.raises(ValueError):
            AlertRule("bad", threshold, lambda *args: None)


def test_text_delivery_appends_and_emits_stable_single_line(tmp_path, capsys):
    path = tmp_path / "alerts.log"
    delivery = TextAlertDelivery(path)
    assert delivery(event()) is True
    assert delivery(event()) is False
    output = capsys.readouterr().err
    assert json.loads(path.read_text()) == asdict(event())
    assert len(output.splitlines()) == 1
    assert TextAlertDelivery(path)(event()) is False
    assert capsys.readouterr().err == ""
    assert "id=7" in output and "score=80.00" in output
    assert "\\nspoof" in output
    assert event().resolved is False


def test_text_delivery_failure_is_reported_without_false_success(tmp_path):
    stream = io.StringIO()
    with pytest.raises(OSError):
        TextAlertDelivery(tmp_path / "missing" / "alerts.log", stream=stream)(event())
    assert stream.getvalue() == ""

    class BrokenStream(io.StringIO):
        def write(self, value):
            raise OSError("stream unavailable")

    with pytest.raises(OSError, match="stream unavailable"):
        TextAlertDelivery(stream=BrokenStream())(event())


def test_log_validation_conflicts_and_stream_retry(tmp_path):
    path = tmp_path / "alerts.jsonl"
    path.write_text('{"alert_id": 7}\n')
    with pytest.raises(ValueError, match="complete"):
        TextAlertDelivery(path)
    path.write_text(json.dumps(asdict(event())))
    with pytest.raises(ValueError, match="incomplete"):
        TextAlertDelivery(path)
    path.write_text(json.dumps(asdict(event())) + "\n")
    sink = TextAlertDelivery(path, stream=io.StringIO())
    conflicting = replace(event(), title="different firing")
    baseline = path.read_bytes()
    stderr_baseline = sink.stream.getvalue()
    for _ in range(2):
        with pytest.raises(ValueError, match=r"^conflicting receipt for alert id 7$"):
            sink(conflicting)
        assert sink._durable_unacknowledged is False
        assert path.read_bytes() == baseline
        assert sink.stream.getvalue() == stderr_baseline
    assert sink(replace(event(), resolved=True)) is False
    assert path.read_bytes() == baseline
    assert sink.stream.getvalue() == stderr_baseline

    class BrokenStream(io.StringIO):
        def write(self, value):
            raise OSError("stream unavailable")

    retry_path = tmp_path / "retry.jsonl"
    sink = TextAlertDelivery(retry_path, stream=BrokenStream())
    with pytest.raises(OSError):
        sink(event())
    sink.stream = io.StringIO()
    assert sink(event()) is True
    assert len(retry_path.read_text().splitlines()) == 1
    assert "id=7" in sink.stream.getvalue()


def test_close_failure_recovery_revalidates_full_log_and_refuses(tmp_path, monkeypatch):
    path = tmp_path / "alerts.jsonl"
    sink = TextAlertDelivery(path, stream=io.StringIO())
    real_open = pathlib.Path.open

    class CloseFails:
        def __init__(self, handle):
            self._handle = handle

        def __getattr__(self, name):
            return getattr(self._handle, name)

        def close(self):
            raise OSError("simulated staged-log close failure")

    def open_with_failing_close(file, mode="r", **kwargs):
        return CloseFails(real_open(file, mode, **kwargs))

    monkeypatch.setattr(pathlib.Path, "open", open_with_failing_close)
    with pytest.raises(OSError, match="close failure"):
        sink(event())
    monkeypatch.undo()
    assert sink._durable_unacknowledged is True

    valid_line = json.dumps(asdict(event()), ensure_ascii=False, sort_keys=True)
    conflicting = replace(event(), title="conflicting firing")
    conflicting_line = json.dumps(asdict(conflicting), ensure_ascii=False, sort_keys=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(conflicting_line + "\n")

    baseline = path.read_bytes()
    stderr_baseline = sink.stream.getvalue()
    for _ in range(2):
        with pytest.raises(
            ValueError, match=re.escape(f"conflicting receipts for alert id 7 in {path}")
        ):
            sink(event())
        assert sink._durable_unacknowledged is True
        assert path.read_bytes() == baseline
        assert sink.stream.getvalue() == stderr_baseline
        assert json.loads(baseline.splitlines()[0]) == asdict(event())
        assert json.loads(baseline.splitlines()[1]) == asdict(conflicting)

import io
import json
from dataclasses import asdict, replace

import pytest

from monitor.alerts import AlertManager, AlertRule, TextAlertDelivery
from monitor.storage import AlertEvent


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


def event():
    return AlertEvent(7, "urgent", 70, "warning", "fingerprint", "https://example.test/a\nspoof", "Story\nspoof", "hn", 80, 123.0, False)


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
    with pytest.raises(ValueError, match="conflicting"):
        sink(replace(event(), title="different firing"))
    assert sink(replace(event(), resolved=True)) is False

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

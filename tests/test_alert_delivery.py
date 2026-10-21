import io
import json
import pathlib
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


def test_production_delivery_sequence_is_open_stderr_append_close_then_state(
    tmp_path, monkeypatch
):
    """Receipt-log open -> stderr write+flush -> append+flush+close -> state update."""

    events = []
    real_open = pathlib.Path.open
    delivery_holder = {}

    class RecordingReceiptFile:
        """Real append-mode file with ordered-event recording (fileno works)."""

        def __init__(self, inner):
            self._inner = inner

        def write(self, text):
            events.append("receipt-append")
            return self._inner.write(text)

        def flush(self):
            events.append("receipt-flush")
            return self._inner.flush()

        def close(self):
            # In-memory delivery state must still be unadvanced at close time.
            assert delivery_holder["delivery"]._receipts == {}
            events.append("receipt-close")
            return self._inner.close()

        def fileno(self):
            return self._inner.fileno()

        def truncate(self, *args):
            return self._inner.truncate(*args)

    def fake_open(self, mode="r", *args, **kwargs):
        assert mode == "a"
        events.append("receipt-open")
        return RecordingReceiptFile(real_open(self, mode, *args, **kwargs))

    class OrderedStderr(io.StringIO):
        def write(self, text):
            events.append("stderr-write")
            return super().write(text)

        def flush(self):
            events.append("stderr-flush")
            return super().flush()

    monkeypatch.setattr(pathlib.Path, "open", fake_open)
    receipt_path = tmp_path / "alerts.jsonl"
    delivery = TextAlertDelivery(receipt_path, stream=OrderedStderr())
    delivery_holder["delivery"] = delivery

    assert delivery(event()) is True
    assert events == [
        "receipt-open",
        "stderr-write",
        "stderr-flush",
        "receipt-append",
        "receipt-flush",
        "receipt-close",
    ]
    # The in-memory state update is the final step, after the log is closed.
    assert delivery._receipts and delivery(event()) is False

    # A stderr write failure inside the open boundary leaves no receipt behind.
    class BrokenWrite(io.StringIO):
        def write(self, text):
            events.append("stderr-write")
            raise OSError("stderr stream gone")

    events.clear()
    broken = TextAlertDelivery(tmp_path / "broken.jsonl", stream=BrokenWrite())
    delivery_holder["delivery"] = broken
    with pytest.raises(OSError, match="stderr stream gone"):
        broken(event())
    assert events == ["receipt-open", "stderr-write", "receipt-close"]
    assert broken._receipts == {}
    # Restore the real Path.open before reading the receipt log below:
    # open("a") creates the staged file, and Path.read_text internally
    # calls open(mode="r"), which would trip the recording fake's
    # append-only mode assertion.
    monkeypatch.setattr(pathlib.Path, "open", real_open)
    assert not (tmp_path / "broken.jsonl").exists() or (
        tmp_path / "broken.jsonl"
    ).read_text(encoding="utf-8") == ""

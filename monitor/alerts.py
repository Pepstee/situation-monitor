"""Alert delivery and the legacy, process-local callback lifecycle.

StateStore remains the sole persisted event and rule-firing owner. This separate
module restores delivery without putting arbitrary callbacks or output streams
inside SQLite transactions. AlertRule deduplication lasts only until reset or
process exit and must not be used as persisted delivery acknowledgement.
"""
from __future__ import annotations

import json
import logging
import math
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TextIO

from .storage import AlertEvent

log = logging.getLogger(__name__)


def _validate_score(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("score and threshold must be finite numbers in [0, 100]")


@dataclass
class AlertRule:
    """Inclusive 0–100 threshold with deduplication after callback success only."""

    name: str
    threshold: float
    on_alert: Callable[[Mapping[str, Any], float], None]
    severity: str = "warning"
    _fired_ids: set[object] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("rule name must not be empty")
        _validate_score(self.threshold)
        if not callable(self.on_alert):
            raise ValueError("on_alert must be callable")

    def check(self, item: Mapping[str, Any], score: float) -> bool:
        _validate_score(score)
        _validate_score(self.threshold)
        if score < self.threshold:
            return False
        key = item.get("url") or item.get("title") or id(item)
        if key in self._fired_ids:
            return False
        try:
            self.on_alert(item, score)
        except Exception:
            log.exception("alert rule %r callback failed; item remains retryable", self.name)
            return False
        self._fired_ids.add(key)
        return True

    def reset(self) -> None:
        self._fired_ids.clear()


class AlertManager:
    """Independent callback rules; one failed callback does not stop other rules."""

    def __init__(self) -> None:
        self._rules: dict[str, AlertRule] = {}

    def add_rule(self, rule: AlertRule) -> None:
        if rule.name in self._rules:
            raise ValueError(f"duplicate alert rule: {rule.name}")
        self._rules[rule.name] = rule

    def remove_rule(self, name: str) -> None:
        self._rules.pop(name, None)

    def evaluate(self, item: Mapping[str, Any], score: float) -> list[str]:
        _validate_score(score)
        return [rule.name for rule in tuple(self._rules.values()) if rule.check(item, score)]

    def evaluate_batch(self, items: Sequence[Mapping[str, Any]], scores: Sequence[float]) -> dict[int, list[str]]:
        if len(items) != len(scores):
            raise ValueError("items and scores must have equal lengths")
        for score in scores:
            _validate_score(score)
        return {index: self.evaluate(item, score) for index, (item, score) in enumerate(zip(items, scores))}

    def reset_all(self) -> None:
        for rule in self._rules.values():
            rule.reset()


class TextAlertDelivery:
    """Deliver persisted events to a JSONL log and a text stream.

    The append-only JSONL file is the durable delivery receipt. Existing complete
    records are validated on construction and their IDs are not emitted again.
    A malformed or truncated log fails visibly, never silently discarding it.
    With no log, deduplication is process-local and restarts may repeat stderr.
    One writer owns the log. This sink does not resolve StateStore events.
    """

    def __init__(self, log_path: str | Path | None = None, *, stream: TextIO | None = None) -> None:
        self.log_path = Path(log_path) if log_path is not None else None
        self.stream = stream
        self._logged: dict[int, dict[str, Any]] = {}
        self._emitted: set[int] = set()
        if self.log_path is not None and self.log_path.exists():
            with self.log_path.open(encoding="utf-8") as source:
                for line_number, line in enumerate(source, 1):
                    try:
                        if not line.endswith("\n"):
                            raise ValueError("incomplete line")
                        record = json.loads(line)
                        self._validate_record(record)
                        previous = self._logged.get(record["alert_id"])
                        if previous is not None and previous != record:
                            raise ValueError("conflicting alert ID")
                    except (ValueError, TypeError, KeyError) as exc:
                        raise ValueError(f"invalid alert log line {line_number}: {exc}") from exc
                    self._logged[record["alert_id"]] = record
                    self._emitted.add(record["alert_id"])

    @staticmethod
    def _validate_record(record: Any) -> None:
        if not isinstance(record, dict) or set(record) != {item.name for item in fields(AlertEvent)}:
            raise ValueError("expected complete AlertEvent fields")
        for key in ("alert_id", "threshold", "score"):
            if type(record[key]) is not int:
                raise ValueError(f"{key} must be an integer")
        if record["alert_id"] <= 0:
            raise ValueError("alert_id must be positive")
        _validate_score(record["score"])
        _validate_score(record["threshold"])
        if isinstance(record["fired_at"], bool) or not isinstance(record["fired_at"], (int, float)) or not math.isfinite(record["fired_at"]):
            raise ValueError("fired_at must be finite")
        if type(record["resolved"]) is not bool:
            raise ValueError("resolved must be boolean")
        for key in ("rule_name", "severity", "fingerprint", "url", "title", "source"):
            if not isinstance(record[key], str):
                raise ValueError(f"{key} must be a string")

    def __call__(self, event: AlertEvent) -> bool:
        """Return true for newly emitted output, false when already delivered.

        Output errors propagate. A file write followed by a stream failure may
        leave a durable log receipt. In-process retry then retries the stream
        only. On restart, the complete log receipt prevents duplicate emission.
        """
        record = asdict(event)
        self._validate_record(record)
        previous = self._logged.get(event.alert_id)
        if previous is not None:
            # Resolution is a lifecycle change, not a different firing.
            if {k: v for k, v in previous.items() if k != "resolved"} != {k: v for k, v in record.items() if k != "resolved"}:
                raise ValueError(f"conflicting alert ID: {event.alert_id}")
        if event.alert_id in self._emitted:
            return False
        if self.log_path is not None and previous is None:
            line = json.dumps(record, sort_keys=True, allow_nan=False) + "\n"
            with self.log_path.open("a", encoding="utf-8") as target:
                if target.write(line) != len(line):
                    raise OSError("incomplete alert log write")
            self._logged[event.alert_id] = record
        line = (f"[ALERT] id={event.alert_id} rule={event.rule_name!r} "
                f"severity={event.severity!r} score={event.score:.2f} "
                f"title={event.title!r} url={event.url!r}\n")
        target = self.stream if self.stream is not None else sys.stderr
        if target.write(line) != len(line):
            raise OSError("incomplete alert stream write")
        target.flush()
        self._emitted.add(event.alert_id)
        return True

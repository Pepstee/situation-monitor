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
import os
import sys
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence, TextIO

from .storage import AlertEvent

log = logging.getLogger(__name__)


def _validate_score(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("score and threshold must be finite numbers in [0, 100]")


@dataclass
class AlertRule:
    """Inclusive 0-100 threshold with deduplication after callback success only."""

    name: str
    threshold: float
    on_alert: Callable[[Mapping[str, Any], float], None]
    severity: str = "warning"
    _fired_ids: set[object] = field(default_factory=set, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or self.name.strip() == "":
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


_ALERT_EVENT_FIELDS = frozenset(field.name for field in fields(AlertEvent))


def _receipt_identity(receipt: Mapping[str, Any]) -> dict[str, Any]:
    """Comparable firing identity: every persisted field except resolution."""

    return {key: value for key, value in receipt.items() if key != "resolved"}


class TextAlertDelivery:
    """Deliver one alert firing as a staged JSON-lines receipt commit.

    Consolidated contract covering ordering, retry, and deduplication:

    - Ordering: open the receipt log, write and flush stderr, append the
      receipt, close the receipt log, then update in-memory delivery state.
      In-memory state is never advanced outside the receipt stream's full
      completion boundary, so an incomplete delivery is never committed.
    - Retry: a stderr write or flush failure appends no receipt (the staged
      log is closed empty) and raises, leaving the persisted SQLite firing
      unresolved so the watch loop retries it on the next evaluation. A
      receipt append, flush or fsync failure after successful stderr
      delivery is equally retryable: the appended line is rolled back so no
      successful receipt is committed, in-memory delivery state stays
      unadvanced, and the delivery error surfaces to the caller, which keeps
      the persisted SQLite firing unresolved for a later evaluation. A close
      failure after successful stderr delivery also surfaces and leaves the
      firing retryable, but it does not roll the record back when the fsync
      already succeeded: a valid durable receipt may remain in the log, and
      a later attempt recovers it by revalidating the entire receipt log
      (terminal newline, per-line schema, alert-id and duplicate-conflict
      checks) and deduplicating on receipt identity, without re-emitting
      stderr or appending a duplicate line.
    - Deduplication: an already-delivered firing returns False without
      touching stderr or the receipt log; a conflicting receipt identity for
      the same alert id raises instead of double-committing.
    """

    def __init__(self, receipt_path: str | Path | None = None, *, stream: TextIO | None = None) -> None:
        if receipt_path is not None and not str(receipt_path).strip():
            raise ValueError("receipt path must not be empty")
        # None means "the process stderr at delivery time", so the default
        # watch path honours stderr redirection that happens after
        # construction and propagates its write/flush failures.
        self.stream = stream
        self._receipt_path = None if receipt_path is None else Path(receipt_path)
        self._receipts: dict[int, dict[str, Any]] = {}
        # Set when a close error follows a successful fsync: the appended
        # receipt may already be durable while in-memory state lags, so the
        # next attempt must revalidate the whole log before deduplicating.
        self._durable_unacknowledged = False
        if self._receipt_path is not None:
            self._load_existing_receipts()

    def _load_existing_receipts(self) -> None:
        assert self._receipt_path is not None
        if not self._receipt_path.exists():
            # A missing log confirms zero receipts. This matters during a
            # _durable_unacknowledged recovery after the log was rotated or
            # removed: returning without clearing would keep stale cached
            # entries alive, and cached dedup would then suppress redelivery
            # of firings the revalidated (empty) log no longer confirms. An
            # early return on a fresh __init__ is unaffected: _receipts is
            # already empty there.
            self._receipts.clear()
            return
        text = self._receipt_path.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            raise ValueError(f"incomplete receipt line at end of {self._receipt_path}")
        # Validate every line, including the terminal newline, JSON/object/
        # required-field and alert-id checks plus duplicate-id conflict
        # checks, into a staging mapping first: a malformed or conflicting
        # later line must leave no partial parsed prefix cached in
        # _receipts, so repeated retries stay fail-closed.
        loaded: dict[int, dict[str, Any]] = {}
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                receipt = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"incomplete receipt line in {self._receipt_path}") from exc
            if not isinstance(receipt, dict) or not _ALERT_EVENT_FIELDS <= set(receipt):
                raise ValueError(f"incomplete receipt line in {self._receipt_path}")
            alert_id = receipt["alert_id"]
            if not isinstance(alert_id, int) or isinstance(alert_id, bool):
                raise ValueError(f"incomplete receipt line in {self._receipt_path}")
            existing = loaded.get(alert_id)
            if existing is not None and _receipt_identity(existing) != _receipt_identity(receipt):
                raise ValueError(f"conflicting receipts for alert id {alert_id} in {self._receipt_path}")
            loaded[alert_id] = dict(receipt)
        # Replace the cache with exactly the revalidated set. During a
        # _durable_unacknowledged recovery this matters: merging via update()
        # would keep cached entries that the just-revalidated log does not
        # contain (e.g. an externally truncated or rotated log), so a
        # missing receipt could still suppress redelivery. A receipt not
        # confirmed by the full revalidation must not count as delivered.
        self._receipts.clear()
        self._receipts.update(loaded)

    def _stderr_message(self, event: AlertEvent) -> str:
        return (
            f"[ALERT] id={event.alert_id} severity={event.severity} "
            f"rule={event.rule_name!r} title={event.title!r} "
            f"url={event.url!r} source={event.source!r} "
            f"score={event.score:.2f} threshold={event.threshold:.2f}\n"
        )

    def _deliver_stderr(self, message: str) -> None:
        """Write and fully flush one stderr alert line, raising on any failure."""

        stream = sys.stderr if self.stream is None else self.stream
        if stream.write(message) != len(message):
            raise OSError("short write to alert stderr stream")
        stream.flush()

    def _commit_receipt_into(self, log_file: TextIO, line: str) -> None:
        """Append one complete receipt line and close the staged log.

        Any write or flush failure rolls the log back to its pre-commit size
        before closing, so no partial receipt is ever left persisted. On
        success the staged handle is closed exactly once, completing the
        commit boundary; a close error still propagates so the firing stays
        retryable, but after a successful fsync it does not roll the record
        back: a valid durable receipt may remain, and the error marks the
        log for a fully revalidated recovery load on the next attempt.
        """

        # O_APPEND positions the fd at 0 until the first write on some
        # platforms, so stage the rollback offset from the file's real
        # size; otherwise a failure could truncate prior receipts.
        committed_at = os.fstat(log_file.fileno()).st_size
        try:
            # A short write here would flush, fsync and commit a truncated
            # receipt line as a delivered receipt, so it must be treated as
            # a commit failure (aborting delivery before flush) exactly like
            # the length-checked stderr write in _deliver_stderr.
            if log_file.write(line + "\n") != len(line) + 1:
                raise OSError("short write to alert receipt log")
            log_file.flush()
            # Durability is part of the commit: a receipt whose fsync fails
            # has NOT been delivered. Roll the appended line back below so a
            # fresh process never observes the failed attempt as a
            # persisted, delivered receipt.
            os.fsync(log_file.fileno())
        except BaseException:
            # Roll back at the file-descriptor level. Truncating (or closing)
            # the buffered text handle would first re-flush its buffer: a
            # failed append can leave the partial line buffered, and a
            # swallowed re-flush would let close() write those bytes back
            # after the truncation, re-creating exactly the malformed JSONL
            # tail a restart retry cannot recover from. Duplicate the fd
            # first, let close() flush whatever it will, then force the file
            # back to its pre-commit size so only bytes from the current
            # incomplete append are discarded and prior receipts survive.
            try:
                rollback_fd = os.dup(log_file.fileno())
            except (OSError, ValueError):
                rollback_fd = None
            try:
                log_file.close()
            except (OSError, ValueError):
                pass
            if rollback_fd is not None:
                try:
                    os.ftruncate(rollback_fd, committed_at)
                    os.fsync(rollback_fd)
                except OSError:
                    pass
                finally:
                    try:
                        os.close(rollback_fd)
                    except OSError:
                        pass
            raise
        # Stage 4 of the commit boundary: only a successful close completes
        # the receipt commit handshake. Surface a close failure instead of
        # swallowing it so in-memory delivery state is never advanced, but a
        # close error after a successful fsync does not roll the durable
        # record back: mark the log for a revalidating recovery load so a
        # retry recognises the durable receipt instead of duplicating it.
        try:
            log_file.close()
        except BaseException:
            self._durable_unacknowledged = True
            raise

    def _discard_empty_staged_log(self, log_file: TextIO) -> None:
        """Abort a staged delivery whose stderr step failed.

        The staged log received no receipt, so closing it leaves an empty
        file; an empty staged log is removed so no stray artifact survives
        a retryable failure. A receipt-append failure may have closed the
        handle during rollback, in which case the staged path is stat'ed
        directly so the rolled-back empty log is still removed. The original
        delivery exception is never masked by cleanup, and in-memory
        delivery state is untouched.
        """

        try:
            empty = os.fstat(log_file.fileno()).st_size == 0
        except (OSError, ValueError):
            empty = False
        try:
            log_file.close()
        except (OSError, ValueError):
            pass
        if self._receipt_path is not None:
            if empty:
                try:
                    self._receipt_path.unlink()
                except OSError:
                    pass
            else:
                # Handle already closed by the rollback: fall back to stat.
                try:
                    if self._receipt_path.stat().st_size == 0:
                        self._receipt_path.unlink()
                except OSError:
                    pass

    def __call__(self, event: AlertEvent) -> bool:
        receipt = asdict(event)
        alert_id = receipt["alert_id"]
        # Recovery for the close-failure window: a prior attempt whose fsync
        # succeeded but whose close raised may have left this receipt
        # durably appended while in-memory state stayed unadvanced. Reload
        # and revalidate the entire receipt log (terminal newline, JSON/
        # object/required-field, alert-id and duplicate-conflict checks)
        # before trusting any parsed prefix of it, then deduplicate on
        # _receipt_identity semantics. A malformed, incomplete or
        # conflicting log raises here rather than becoming a success, so
        # repeated retries stay fail-closed; a valid durable receipt is
        # recovered without re-emitting stderr or appending a duplicate.
        # This pending recovery must run before any cached-event fast path:
        # otherwise an alert id already present in _receipts would return
        # from the cached dedup check without the log ever being
        # revalidated, and the marker would stay set forever.
        if self._durable_unacknowledged and self._receipt_path is not None:
            # Clear the recovery marker only after the revalidating reload
            # succeeds: a malformed or conflicting log raises here and keeps
            # the marker set, so the next retry revalidates the whole log
            # again instead of blindly appending after it (fail-closed).
            self._load_existing_receipts()
            self._durable_unacknowledged = False
        existing = self._receipts.get(alert_id)
        if existing is not None:
            if _receipt_identity(existing) != _receipt_identity(receipt):
                raise ValueError(f"conflicting receipt for alert id {alert_id}")
            return False
        line = json.dumps(receipt, ensure_ascii=False, sort_keys=True)
        # Strict delivery ordering: (1) open the receipt log, (2) write and
        # flush stderr, (3) append the receipt, (4) close the receipt log,
        # and only then (5) advance in-memory delivery state. A stderr write
        # or flush failure aborts while the staged log is still empty and is
        # closed before the exception propagates, so no receipt is appended
        # and the persisted SQLite firing stays unresolved and retryable on a
        # later watch evaluation. In-memory state is never advanced outside
        # the receipt stream's full completion boundary.
        if self._receipt_path is None:
            self._deliver_stderr(self._stderr_message(event))
        else:
            assert self._receipt_path is not None
            log_file = self._receipt_path.open("a", encoding="utf-8")
            try:
                # Stage 2 happens strictly inside the open receipt-log
                # boundary while the log is still empty; failure here leaves
                # the log empty and the firing retryable.
                self._deliver_stderr(self._stderr_message(event))
                # Stages 3 and 4: append the complete receipt and close the
                # log before any state is acknowledged.
                self._commit_receipt_into(log_file, line)
            except BaseException:
                # Abort without a receipt: close (and, if still empty,
                # remove) the staged log, preserve the original delivery
                # exception, and leave in-memory state unadvanced so the
                # persisted SQLite firing stays retryable.
                self._discard_empty_staged_log(log_file)
                raise
        self._receipts[alert_id] = receipt
        return True

    def reset(self) -> None:
        self._receipts.clear()
        # Forget the pending recovery marker too: keeping it would force a
        # revalidating reload on the next call that repopulates _receipts
        # from the log, so reset() would never actually reset delivery
        # deduplication state.
        self._durable_unacknowledged = False

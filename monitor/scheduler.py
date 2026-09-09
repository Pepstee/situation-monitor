"""Deterministic one-shot lifecycle for registered fixture sources."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
import math
import threading
import time

from monitor.storage import StateStore
from schemas import Article


FixtureCollector = Callable[[str], list[Article]]


@dataclass(frozen=True)
class SourceCheckResult:
    """Inspectable terminal state for one due source check."""

    source: str
    fixture_source: str
    checked_at: float
    run_id: int
    item_count: int
    error: str | None

    @property
    def status(self) -> str:
        return "succeeded" if self.error is None else "failed"


def run_due_source_checks(
    store: StateStore,
    collect: FixtureCollector,
    *,
    checked_at: float,
    source_names: Iterable[str] | None = None,
    elapsed_clock: Callable[[], float] | None = None,
) -> list[SourceCheckResult]:
    """Collect every due source once, recording failures without stopping the tick."""

    results: list[SourceCheckResult] = []
    admitted = None if source_names is None else set(source_names)
    for due in store.due_sources(now=checked_at):
        source = due.source
        if admitted is not None and source.name not in admitted:
            continue
        started = elapsed_clock() if elapsed_clock else 0
        try:
            articles = collect(source.fixture_source)
            if not isinstance(articles, list) or not all(
                isinstance(article, Article) for article in articles
            ):
                raise TypeError("fixture collector must return list[Article]")
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            run_id = store.record_source_check(
                source.name,
                checked_at,
                error=error,
                finished_at=checked_at + max(0, elapsed_clock() - started) if elapsed_clock else None,
            )
            item_count = 0
        else:
            error = None
            run_id = store.record_source_check(
                source.name,
                checked_at,
                articles=articles,
                finished_at=checked_at + max(0, elapsed_clock() - started) if elapsed_clock else None,
            )
            item_count = len(articles)
        results.append(
            SourceCheckResult(
                source=source.name,
                fixture_source=source.fixture_source,
                checked_at=checked_at,
                run_id=run_id,
                item_count=item_count,
                error=error,
            )
        )
    return results


def run_source_loop(
    store: StateStore, collect: FixtureCollector, *, poll_interval_s: float,
    max_cycles: int | None = None, stop_event: threading.Event | None = None,
    clock: Callable[[], float] = time.time,
    source_names: Iterable[str] | None = None,
    elapsed_clock: Callable[[], float] | None = None,
):
    """Repeat the canonical due-source operation with bounded or interruptible lifetime."""
    if not math.isfinite(poll_interval_s) or poll_interval_s <= 0:
        raise ValueError("poll interval must be positive and finite")
    if max_cycles is not None and max_cycles < 1:
        raise ValueError("max_cycles must be positive")
    stop = stop_event if stop_event is not None else threading.Event()
    cycles = 0
    admitted = None if source_names is None else tuple(source_names)
    while not stop.is_set():
        checked_at = clock()
        yield checked_at, run_due_source_checks(
            store, collect, checked_at=checked_at, source_names=admitted, elapsed_clock=elapsed_clock,
        )
        cycles += 1
        if max_cycles is not None and cycles >= max_cycles:
            break
        stop.wait(poll_interval_s)

"""Deterministic one-shot lifecycle for registered fixture sources."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
) -> list[SourceCheckResult]:
    """Collect every due source once, recording failures without stopping the tick."""

    results: list[SourceCheckResult] = []
    for due in store.due_sources(now=checked_at):
        source = due.source
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
            )
            item_count = 0
        else:
            error = None
            run_id = store.record_source_check(
                source.name,
                checked_at,
                articles=articles,
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

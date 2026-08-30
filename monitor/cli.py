"""Command-line interface for local summaries and fixture-only source inspection."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from monitor.analysis import analyze_articles, build_digest
from monitor.ingest import article_record, fetch_fixture_articles, load_events
from monitor.scheduler import SourceCheckResult, run_due_source_checks
from monitor.storage import AlertEvent, RunRecord, StateStore, StoredArticle
from monitor.summarize import summarize


PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_EVENTS = PROJECT_ROOT / "data" / "sample_events.json"
DEFAULT_FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_CHOICES = ("hackernews", "github_trending", "rss")
CHECK_FAILURE_EXIT_CODE = 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="situation-monitor")
    subcommands = parser.add_subparsers(dest="command")

    summary_parser = subcommands.add_parser(
        "summary", help="summarize a local JSON event list"
    )
    summary_parser.add_argument("input", nargs="?", default=str(DEFAULT_EVENTS))

    fetch_parser = subcommands.add_parser(
        "fetch", help="inspect fixture-backed source parsing without network access"
    )
    fetch_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="required safety flag; only local fixture bytes are read",
    )
    fetch_parser.add_argument(
        "--fixture-dir",
        default=str(DEFAULT_FIXTURES),
        help="directory containing the three admitted fixture files",
    )
    fetch_parser.add_argument(
        "--source",
        action="append",
        choices=SOURCE_CHOICES,
        dest="sources",
        help="source parser to exercise; repeat to select multiple (default: all)",
    )
    fetch_parser.add_argument(
        "--digest",
        action="store_true",
        help="run deterministic scoring, deduplication, clustering, and Markdown digesting",
    )

    tick_parser = subcommands.add_parser(
        "tick", help="run one due fixture-source check cycle into explicit local state"
    )
    tick_parser.add_argument(
        "--state",
        required=True,
        help="explicit SQLite state path; no default state file is used",
    )
    tick_parser.add_argument(
        "--at",
        required=True,
        type=float,
        help="deterministic check timestamp as Unix seconds",
    )
    tick_parser.add_argument(
        "--fixture-dir",
        default=str(DEFAULT_FIXTURES),
        help="directory containing the three admitted fixture files",
    )
    tick_parser.add_argument(
        "--source",
        action="append",
        choices=SOURCE_CHOICES,
        dest="sources",
        help="fixture source to register and check; repeat to select multiple",
    )
    tick_parser.add_argument(
        "--interval-seconds",
        type=int,
        default=3600,
        help="positive fixed interval for the selected source registrations",
    )

    dashboard_parser = subcommands.add_parser(
        "dashboard", help="inspect a deterministic read-only local state snapshot"
    )
    dashboard_parser.add_argument(
        "--state",
        required=True,
        help="explicit existing SQLite state path; the snapshot never creates state",
    )
    dashboard_parser.add_argument(
        "--at",
        required=True,
        type=float,
        help="deterministic snapshot timestamp as Unix seconds",
    )
    dashboard_parser.add_argument(
        "--window-hours",
        type=float,
        default=24.0,
        help="non-negative recent-article window (default: 24)",
    )
    dashboard_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="positive maximum rows shown per collection (default: 20)",
    )

    alerts_parser = subcommands.add_parser(
        "alerts", help="evaluate and inspect local persisted threshold alerts"
    )
    alert_actions = alerts_parser.add_subparsers(dest="alert_action", required=True)

    evaluate_parser = alert_actions.add_parser(
        "evaluate", help="analyze local fixtures and persist newly fired alerts"
    )
    evaluate_parser.add_argument("--state", required=True)
    evaluate_parser.add_argument("--at", required=True, type=float)
    evaluate_parser.add_argument("--rule", default="high-score")
    evaluate_parser.add_argument("--threshold", required=True, type=int)
    evaluate_parser.add_argument(
        "--severity", choices=("info", "warning", "critical"), default="warning"
    )
    evaluate_parser.add_argument("--fixture-dir", default=str(DEFAULT_FIXTURES))
    evaluate_parser.add_argument(
        "--source", action="append", choices=SOURCE_CHOICES, dest="sources"
    )

    list_parser = alert_actions.add_parser("list", help="list persisted alert events")
    list_parser.add_argument("--state", required=True)
    list_parser.add_argument("--unresolved", action="store_true")
    list_parser.add_argument("--limit", type=int, default=20)

    resolve_parser = alert_actions.add_parser(
        "resolve", help="mark one persisted alert event resolved"
    )
    resolve_parser.add_argument("alert_id", type=int)
    resolve_parser.add_argument("--state", required=True)
    return parser


def _run_summary(input_file: str) -> int:
    events, errors = load_events(input_file)
    for error in errors:
        print(f"Warning: {error}", file=sys.stderr)
    print(summarize(events))
    return 0


def _run_fixture_fetch(
    fixture_dir: str,
    sources: list[str] | None,
    *,
    digest: bool = False,
) -> int:
    articles = fetch_fixture_articles(fixture_dir, sources or SOURCE_CHOICES)
    if digest:
        print(build_digest(articles), end="")
        return 0
    source_counts = Counter(article.source for article in articles)
    result = {
        "articles": [article_record(article) for article in articles],
        "count": len(articles),
        "mode": "fixture-dry-run",
        "network_attempted": False,
        "source_counts": dict(sorted(source_counts.items())),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _check_record(result: SourceCheckResult) -> dict[str, object]:
    return {
        "checked_at": result.checked_at,
        "error": result.error,
        "fixture_source": result.fixture_source,
        "item_count": result.item_count,
        "run_id": result.run_id,
        "source": result.source,
        "status": result.status,
    }


def _alert_record(event: AlertEvent) -> dict[str, object]:
    return {
        "alert_id": event.alert_id,
        "fired_at": event.fired_at,
        "resolved": event.resolved,
        "rule": event.rule_name,
        "score": event.score,
        "severity": event.severity,
        "source": event.source,
        "threshold": event.threshold,
        "title": event.title,
        "url": event.url,
    }


def _dashboard_article_record(item: StoredArticle) -> dict[str, object]:
    scored = item.scored
    return {
        "cluster_id": item.cluster_id,
        "confidence_high": None if scored is None else scored.confidence_high,
        "confidence_low": None if scored is None else scored.confidence_low,
        "digest_rank": item.digest_rank,
        "reliability": item.article.reliability.value,
        "score": None if scored is None else scored.score,
        "seen_at": item.seen_at,
        "signals": [] if scored is None else list(scored.signals),
        "source": item.article.source,
        "title": item.article.title,
        "url": item.article.url,
    }


def _run_record(run: RunRecord) -> dict[str, object]:
    return {
        "error": run.error,
        "finished_at": run.finished_at,
        "item_count": run.item_count,
        "run_id": run.run_id,
        "source": run.source,
        "started_at": run.started_at,
        "status": "succeeded" if run.error is None else "failed",
    }


def _run_fixture_tick(
    state_path: str,
    fixture_dir: str,
    sources: list[str] | None,
    *,
    checked_at: float,
    interval_s: int,
) -> int:
    """Run one tick, returning 1 after emitting JSON if any due check failed."""

    if interval_s <= 0:
        raise ValueError("interval_seconds must be positive")
    selected_sources = sources or list(SOURCE_CHOICES)
    with StateStore(state_path) as store:
        for source in selected_sources:
            store.register_source(source, source, interval_s)
        results = run_due_source_checks(
            store,
            lambda source: fetch_fixture_articles(fixture_dir, [source]),
            checked_at=checked_at,
        )
    output = {
        "checked_at": checked_at,
        "due_count": len(results),
        "mode": "fixture-one-shot",
        "network_attempted": False,
        "results": [_check_record(result) for result in results],
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    if any(result.status == "failed" for result in results):
        return CHECK_FAILURE_EXIT_CODE
    return 0


def _run_fixture_alert_evaluation(
    state_path: str,
    fixture_dir: str,
    sources: list[str] | None,
    *,
    evaluated_at: float,
    rule_name: str,
    threshold: int,
    severity: str,
) -> int:
    """Analyze local fixtures and retain newly fired SQLite alerts."""

    articles = fetch_fixture_articles(fixture_dir, sources or SOURCE_CHOICES)
    clusters = analyze_articles(articles)
    with StateStore(state_path) as store:
        analyzed_count = store.save_clusters(clusters, seen_at=evaluated_at)
        created = store.evaluate_alert_rule(
            rule_name,
            threshold,
            severity=severity,
            fired_at=evaluated_at,
        )
    output = {
        "analyzed_count": analyzed_count,
        "created_count": len(created),
        "evaluated_at": evaluated_at,
        "events": [_alert_record(event) for event in created],
        "mode": "fixture-alert-evaluation",
        "network_attempted": False,
        "rule": rule_name.strip(),
        "severity": severity,
        "threshold": threshold,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_alert_list(state_path: str, *, unresolved_only: bool, limit: int) -> int:
    with StateStore(state_path) as store:
        events = store.list_alert_events(
            unresolved_only=unresolved_only,
            limit=limit,
        )
    output = {
        "count": len(events),
        "events": [_alert_record(event) for event in events],
        "mode": "local-alert-list",
        "network_attempted": False,
        "unresolved_only": unresolved_only,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _run_alert_resolution(state_path: str, alert_id: int) -> int:
    with StateStore(state_path) as store:
        resolved = store.resolve_alert_event(alert_id)
    output = {
        "alert_id": alert_id,
        "mode": "local-alert-resolution",
        "network_attempted": False,
        "resolved": resolved,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if resolved else 1


def _run_dashboard(
    state_path: str,
    *,
    snapshot_at: float,
    window_hours: float,
    limit: int,
) -> int:
    """Render one transactionally closed, read-only JSON state snapshot."""

    with StateStore(state_path, read_only=True) as store:
        store.conn.execute("BEGIN")
        try:
            articles = store.recent_articles(window_hours, now=snapshot_at)
            runs = store.list_runs()
            alerts = store.list_alert_events(limit=limit)
            alert_count, unresolved_count = store.alert_event_counts()
            sources = store.list_sources()
            due_names = {
                item.source.name for item in store.due_sources(now=snapshot_at)
            }
            reliability = {item.source: item for item in store.all_reliability()}
        finally:
            store.conn.rollback()

    last_runs: dict[str, RunRecord] = {}
    for run in runs:
        last_runs.setdefault(run.source, run)
    source_records: list[dict[str, object]] = []
    for source in sources:
        last_run = last_runs.get(source.name)
        stats = reliability.get(source.name)
        due_at = (
            None
            if not source.enabled
            else snapshot_at
            if last_run is None
            else last_run.finished_at + source.interval_s
        )
        source_records.append(
            {
                "due": source.name in due_names,
                "due_at": due_at,
                "enabled": source.enabled,
                "fixture_source": source.fixture_source,
                "hit_rate": None if stats is None else stats.hit_rate,
                "interval_seconds": source.interval_s,
                "last_finished_at": None if last_run is None else last_run.finished_at,
                "last_run_id": None if last_run is None else last_run.run_id,
                "last_status": None
                if last_run is None
                else "succeeded"
                if last_run.error is None
                else "failed",
                "name": source.name,
                "run_count": 0 if stats is None else stats.run_count,
                "success_count": 0 if stats is None else stats.success_count,
            }
        )

    output = {
        "alerts": {
            "items": [_alert_record(event) for event in alerts],
            "resolved_count": alert_count - unresolved_count,
            "shown_count": len(alerts),
            "total_count": alert_count,
            "unresolved_count": unresolved_count,
        },
        "articles": {
            "items": [_dashboard_article_record(item) for item in articles[:limit]],
            "shown_count": min(len(articles), limit),
            "total_count": len(articles),
            "window_hours": window_hours,
        },
        "generated_at": snapshot_at,
        "limit": limit,
        "mode": "local-dashboard-snapshot",
        "network_attempted": False,
        "run_receipts": {
            "failed_count": sum(run.error is not None for run in runs),
            "items": [_run_record(run) for run in runs[:limit]],
            "shown_count": min(len(runs), limit),
            "succeeded_count": sum(run.error is None for run in runs),
            "total_count": len(runs),
        },
        "schema": "situation-monitor.dashboard.v1",
        "sources": {
            "due_count": sum(item["due"] is True for item in source_records),
            "items": source_records[:limit],
            "shown_count": min(len(source_records), limit),
            "total_count": len(source_records),
        },
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    # Preserve the original no-argument local-summary behaviour.
    if arguments.command is None:
        return _run_summary(str(DEFAULT_EVENTS))
    if arguments.command == "summary":
        return _run_summary(arguments.input)
    if arguments.command == "fetch":
        if not arguments.dry_run:
            parser.error(
                "fetch currently requires --dry-run; live network ingestion is deferred"
            )
        return _run_fixture_fetch(
            arguments.fixture_dir,
            arguments.sources,
            digest=arguments.digest,
        )
    if arguments.command == "tick":
        if arguments.interval_seconds <= 0:
            parser.error("--interval-seconds must be positive")
        return _run_fixture_tick(
            arguments.state,
            arguments.fixture_dir,
            arguments.sources,
            checked_at=arguments.at,
            interval_s=arguments.interval_seconds,
        )
    if arguments.command == "dashboard":
        if not Path(arguments.state).is_file():
            parser.error("--state must name an existing SQLite file")
        if not math.isfinite(arguments.at):
            parser.error("--at must be finite")
        if not math.isfinite(arguments.window_hours) or arguments.window_hours < 0:
            parser.error("--window-hours must be finite and non-negative")
        if arguments.limit <= 0:
            parser.error("--limit must be positive")
        return _run_dashboard(
            arguments.state,
            snapshot_at=arguments.at,
            window_hours=arguments.window_hours,
            limit=arguments.limit,
        )
    if arguments.command == "alerts":
        if arguments.alert_action == "evaluate":
            if not 0 <= arguments.threshold <= 100:
                parser.error("--threshold must be between 0 and 100")
            if not arguments.rule.strip():
                parser.error("--rule must not be empty")
            return _run_fixture_alert_evaluation(
                arguments.state,
                arguments.fixture_dir,
                arguments.sources,
                evaluated_at=arguments.at,
                rule_name=arguments.rule,
                threshold=arguments.threshold,
                severity=arguments.severity,
            )
        if arguments.alert_action == "list":
            if arguments.limit <= 0:
                parser.error("--limit must be positive")
            return _run_alert_list(
                arguments.state,
                unresolved_only=arguments.unresolved,
                limit=arguments.limit,
            )
        if arguments.alert_action == "resolve":
            if arguments.alert_id <= 0:
                parser.error("alert_id must be positive")
            return _run_alert_resolution(arguments.state, arguments.alert_id)
    parser.error(f"unknown command: {arguments.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

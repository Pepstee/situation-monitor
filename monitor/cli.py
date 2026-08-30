"""Command-line interface for local summaries and fixture-only source inspection."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).parent.parent))

from monitor.analysis import build_digest
from monitor.ingest import article_record, fetch_fixture_articles, load_events
from monitor.scheduler import SourceCheckResult, run_due_source_checks
from monitor.storage import StateStore
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
    parser.error(f"unknown command: {arguments.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

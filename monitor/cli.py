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
from monitor.summarize import summarize


PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_EVENTS = PROJECT_ROOT / "data" / "sample_events.json"
DEFAULT_FIXTURES = Path(__file__).parent / "fixtures"
SOURCE_CHOICES = ("hackernews", "github_trending", "rss")


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
    parser.error(f"unknown command: {arguments.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

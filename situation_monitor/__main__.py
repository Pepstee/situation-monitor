"""CLI entry point for situation_monitor.

Subcommands:
  once   – ingest, enrich, print Markdown digest, exit
  serve  – start the web dashboard
  run    – loop 'once' every poll_interval_seconds
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from situation_monitor.bias import get_source_lean, get_source_reliability
from situation_monitor.config import Config
from situation_monitor.dashboard import make_app
from situation_monitor.dedup import deduplicate
from situation_monitor.ingestion.crypto import CryptoRSSFetcher
from situation_monitor.ingestion.github_trending import GitHubTrendingFetcher
from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.llm import get_llm_client
from situation_monitor.models import Article
from situation_monitor.polymarket import PolymarketMatcher
from situation_monitor.propaganda import flag_article
from situation_monitor.reliability import ReliabilityTracker


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------


def _load_config(config_path: str | None) -> Config:
    config = Config.from_defaults()
    if config_path:
        try:
            config = Config.from_file(config_path)
        except Exception:
            pass
    # Apply env-var overrides on top
    _apply_env(config)
    return config


def _apply_env(config: Config) -> None:
    if v := os.environ.get("SM_SOURCES"):
        config.sources = [s.strip() for s in v.split(",") if s.strip()]
    if v := os.environ.get("SM_POLL_INTERVAL"):
        config.poll_interval_seconds = int(v)
    if v := os.environ.get("SM_DASHBOARD_PORT"):
        config.dashboard_port = int(v)
    if v := os.environ.get("SM_LLM_BACKEND"):
        config.llm_backend = v
    if v := os.environ.get("SM_OLLAMA_URL"):
        config.ollama_url = v
    if v := os.environ.get("SM_OLLAMA_MODEL"):
        config.ollama_model = v
    if v := os.environ.get("SM_MAX_ARTICLES"):
        config.max_articles_per_digest = int(v)
    if v := os.environ.get("SM_FETCH_INTERVAL"):
        config.fetch_interval_seconds = int(v)
    if v := os.environ.get("SM_LOG_LEVEL"):
        config.log_level = v
    if v := os.environ.get("SM_POLYMARKET_MARKETS"):
        config.polymarket_markets = [s.strip() for s in v.split(",") if s.strip()]


# ---------------------------------------------------------------------------
# Local-file HTTP client (lets us read fixture files without network)
# ---------------------------------------------------------------------------


class _LocalFileClient:
    def get(self, url: str) -> bytes:
        return Path(url).read_bytes()


def _is_url(source: str) -> bool:
    return source.startswith("http://") or source.startswith("https://")


_HN_DEFAULT_URL = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"
_GITHUB_TRENDING_DEFAULT_URL = "https://github.com/trending"


def _resolve_source(source: str) -> str:
    """Map shorthand scheme URIs to real fetch URLs."""
    if source == "hn://":
        return _HN_DEFAULT_URL
    if source == "github_trending://":
        return _GITHUB_TRENDING_DEFAULT_URL
    return source


def _select_fetcher(source: str, client=None):
    if "hn.algolia.com" in source or source.startswith("hn://"):
        return HNFetcher(client=client)
    if "github.com/trending" in source or source.startswith("github_trending://"):
        return GitHubTrendingFetcher(client=client)
    if "coindesk" in source or "cointelegraph" in source:
        return CryptoRSSFetcher(client=client)
    return RSSFetcher(client=client)


# ---------------------------------------------------------------------------
# Polymarket markets loader
# ---------------------------------------------------------------------------


def _load_polymarket_markets(config: Config) -> list[dict]:
    markets: list[dict] = []
    for entry in config.polymarket_markets:
        if isinstance(entry, dict):
            markets.append(entry)
        elif isinstance(entry, str) and Path(entry).exists():
            try:
                markets.extend(json.loads(Path(entry).read_text()))
            except Exception:
                pass
    return markets


# ---------------------------------------------------------------------------
# Ingest + enrich pipeline
# ---------------------------------------------------------------------------


def _ingest_and_enrich(config: Config) -> list[Article]:
    articles: list[Article] = []
    tracker = ReliabilityTracker()
    state_path = config.state_file or "state/reliability.json"
    tracker.load(state_path)

    for source in config.sources:
        try:
            resolved = _resolve_source(source)
            client = None if _is_url(resolved) else _LocalFileClient()
            fetcher = _select_fetcher(resolved, client)
            fetched = fetcher.fetch(resolved)
            tracker.record_fetch(source, len(fetched))
            articles.extend(fetched)
        except Exception as exc:
            print(f"Warning: failed to fetch {source!r}: {exc}", file=sys.stderr)

    articles = deduplicate(articles)

    # Bias scoring
    for article in articles:
        article.source_lean = get_source_lean(article.source)
        article.source_reliability_label = get_source_reliability(article.source)
        article.relevance_score = 1.0

    # Override reliability label with tracker data when available
    for article in articles:
        tracked = tracker.get_tracked_reliability(article.source)
        if tracked is not None:
            article.source_reliability_label = tracked

    try:
        tracker.save(state_path)
    except Exception as exc:
        print(f"Warning: failed to save reliability state: {exc}", file=sys.stderr)

    # Simple keyword-based clustering (no LLM required)
    _assign_clusters(articles)

    # Polymarket matching
    markets = _load_polymarket_markets(config)
    matcher = PolymarketMatcher()
    for article in articles:
        article.polymarket_odds = matcher.match(article, markets)

    # Propaganda detection (best-effort; failures silently yield empty flags)
    try:
        llm = get_llm_client(config)
        for article in articles:
            article.propaganda_flags = flag_article(article, llm)
    except Exception as exc:
        print(f"Warning: propaganda detection skipped: {exc}", file=sys.stderr)

    return articles[: config.max_articles_per_digest]


def _assign_clusters(articles: list[Article]) -> None:
    """Group articles into clusters by shared significant title words."""
    clusters: dict[str, str] = {}
    counter = 0
    STOPWORDS = {"the", "a", "an", "in", "of", "to", "is", "by", "on", "for", "and", "or"}

    def _key(article: Article) -> str | None:
        words = [w.lower() for w in article.title.split() if w.lower() not in STOPWORDS]
        return words[0] if words else None

    for article in articles:
        key = _key(article)
        if key is None:
            article.cluster_id = "misc"
            continue
        if key not in clusters:
            clusters[key] = f"c{counter}"
            counter += 1
        article.cluster_id = clusters[key]


# ---------------------------------------------------------------------------
# Markdown output
# ---------------------------------------------------------------------------


def _print_markdown(articles: list[Article]) -> None:
    from datetime import datetime

    print(f"# Situation Monitor Digest — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n")
    if not articles:
        print("_No stories found._")
        return
    for art in articles:
        lean = art.source_lean or "—"
        rel = art.source_reliability_label or art.reliability.value
        relevance = f"{art.relevance_score:.2f}" if art.relevance_score is not None else "—"
        cluster = art.cluster_id or "—"
        flags = ", ".join(art.propaganda_flags) if art.propaganda_flags else "none"
        odds = f"{art.polymarket_odds:.2f}" if art.polymarket_odds is not None else "—"
        print(f"## {art.title}")
        print(f"<{art.url}>")
        print(
            f"Source: {art.source} | Lean: {lean} | Reliability: {rel} | "
            f"Relevance: {relevance} | Cluster: {cluster}"
        )
        print(f"Propaganda: {flags} | Polymarket: {odds}")
        print()


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _cmd_once(config: Config) -> None:
    articles = _ingest_and_enrich(config)
    _print_markdown(articles)


def _cmd_serve(config: Config) -> None:
    _store: list[Article] = []

    def _get_stories() -> list[Article]:
        return _store

    app = make_app(_get_stories)

    def _refresh() -> None:
        _store[:] = _ingest_and_enrich(config)

    _refresh()
    print(f"Dashboard running on http://0.0.0.0:{config.dashboard_port}", file=sys.stderr)
    app.run(host="0.0.0.0", port=config.dashboard_port)


def _cmd_run(config: Config) -> None:
    while True:
        _cmd_once(config)
        sys.stdout.flush()
        time.sleep(config.poll_interval_seconds)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = _ArgumentParser(prog="situation_monitor", description="Situation Monitor")
    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument(
        "--config",
        metavar="PATH",
        default=None,
        help="Path to JSON config file (defaults + env vars used if omitted or unparseable)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once", parents=[shared], help="Ingest, enrich, print Markdown digest, then exit")
    sub.add_parser("serve", parents=[shared], help="Start web dashboard")
    sub.add_parser("run", parents=[shared], help="Loop 'once' every poll_interval_seconds")
    sub.add_parser("show-config", parents=[shared], help="Print the resolved Config and exit")

    args = parser.parse_args(argv)

    if args.cmd == "show-config":
        config = _load_config(getattr(args, "config", None))
        print(repr(config))
        return

    config = _load_config(args.config)

    if args.cmd == "once":
        _cmd_once(config)
    elif args.cmd == "serve":
        _cmd_serve(config)
    elif args.cmd == "run":
        _cmd_run(config)


if __name__ == "__main__":
    main()

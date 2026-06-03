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
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.llm import get_llm_client
from situation_monitor.models import Article
from situation_monitor.polymarket import PolymarketMatcher
from situation_monitor.propaganda import flag_article


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

    for source in config.sources:
        try:
            client = None if _is_url(source) else _LocalFileClient()
            fetcher = RSSFetcher(client=client)
            articles.extend(fetcher.fetch(source))
        except Exception as exc:
            print(f"Warning: failed to fetch {source!r}: {exc}", file=sys.stderr)

    # Bias scoring
    for article in articles:
        article.source_lean = get_source_lean(article.source)
        article.source_reliability_label = get_source_reliability(article.source)
        article.relevance_score = 1.0

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


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="edge", description="Situation Monitor")
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

    args = parser.parse_args(argv)
    config = _load_config(args.config)

    if args.cmd == "once":
        _cmd_once(config)
    elif args.cmd == "serve":
        _cmd_serve(config)
    elif args.cmd == "run":
        _cmd_run(config)


if __name__ == "__main__":
    main()

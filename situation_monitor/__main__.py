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
from situation_monitor.domains import classify_domain
from situation_monitor.ingestion.crypto import CryptoRSSFetcher
from situation_monitor.ingestion.discourse_carrier import CarrierDef, DiscourseCarrierFetcher
from situation_monitor.ingestion.github_trending import GitHubTrendingFetcher
from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.llm import get_llm_client
from situation_monitor.models import Article, Domain
from situation_monitor.alerting import check_and_emit_alerts
from situation_monitor.polymarket import PolymarketClient, PolymarketMatcher
from situation_monitor.propaganda import enrich_article
from situation_monitor.relevance import score_relevance
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
    if v := os.environ.get("SM_POLYMARKET_SLUGS"):
        config.polymarket_slugs = [s.strip() for s in v.split(",") if s.strip()]


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


def _resolve_carrier_roster() -> list[CarrierDef]:
    """Parse SM_CARRIER_FEEDS (JSON array of {url,country,lean}) into a roster.

    Returns an empty list when the env var is unset, so existing pipelines and
    tests are unaffected unless carrier feeds are explicitly configured.
    """
    v = os.environ.get("SM_CARRIER_FEEDS")
    if not v:
        return []
    try:
        entries = json.loads(v)
        return [CarrierDef(url=e["url"], country=e["country"], lean=e["lean"]) for e in entries]
    except Exception:
        return []


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


def _default_state_path() -> str:
    """Per-user runtime state location (XDG). Kept OUT of the project tree so the
    deliverable stays a pure artefact — a writable `state/` dir inside it is scratch."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state"
    )
    return os.path.join(base, "situation_monitor", "reliability.json")


def _ingest_and_enrich(config: Config) -> list[Article]:
    articles: list[Article] = []
    tracker = ReliabilityTracker()
    state_path = config.state_file or _default_state_path()
    tracker.load(state_path)

    # Domain-tagged sources come first so they win URL-based deduplication.
    for source_def in config.source_defs:
        try:
            url = source_def.url
            client = None if _is_url(url) else _LocalFileClient()
            fetched = RSSFetcher(client=client).fetch(url, source_def=source_def)
            tracker.record_fetch(url, len(fetched))
            articles.extend(fetched)
        except Exception as exc:
            print(f"Warning: failed to fetch {source_def.url!r}: {exc}", file=sys.stderr)

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

    # Discourse carrier feeds — stamped with country + lean, merged before dedup
    for carrier in _resolve_carrier_roster():
        try:
            client = None if _is_url(carrier.url) else _LocalFileClient()
            fetcher = DiscourseCarrierFetcher(roster=[carrier], client=client)
            fetched = fetcher.fetch()
            tracker.record_fetch(carrier.url, len(fetched))
            articles.extend(fetched)
        except Exception as exc:
            print(f"Warning: carrier feed {carrier.url!r}: {exc}", file=sys.stderr)

    articles = deduplicate(articles)

    # Classify each surviving article into its section by CONTENT, not just by the
    # feed it arrived on. URL-dedup keeps one copy of a story shared across feeds;
    # content classification then files that survivor under the right domain
    # (a Bitcoin story → MARKETS, an AI story → AI) instead of inheriting whichever
    # feed happened to win dedup. Feed-declared domain remains the fallback.
    for article in articles:
        article.domain = classify_domain(article, default=article.domain)

    llm = get_llm_client(config)

    # Bias scoring + relevance (don't overwrite lean already set by a source_def)
    for article in articles:
        if article.source_lean is None:
            article.source_lean = get_source_lean(article.source)
        article.source_reliability_label = get_source_reliability(article.source)
        article.reliability_tier = get_source_reliability(article.source)
        article.relevance_score = score_relevance(article, config.topics, llm)

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

    # Polymarket matching: live API (slugs) → file-based API format → legacy keyword format
    if config.polymarket_slugs:
        _pm = PolymarketClient(slugs=config.polymarket_slugs)
        _pm_markets = _pm.fetch_markets()
        for article in articles:
            article.polymarket_odds = _pm.match(article, _pm_markets)
    else:
        _file_markets = _load_polymarket_markets(config)
        _api_markets = [m for m in _file_markets if "outcomePrices" in m]
        _legacy_markets = [m for m in _file_markets if "odds" in m]
        if _api_markets:
            _pm_client = PolymarketClient(slugs=[])
            for article in articles:
                article.polymarket_odds = _pm_client.match(article, _api_markets)
        elif _legacy_markets:
            _matcher = PolymarketMatcher()
            for article in articles:
                article.polymarket_odds = _matcher.match(article, _legacy_markets)

    # Propaganda detection (best-effort; failures silently leave fields at defaults)
    try:
        for article in articles:
            enrich_article(article, llm)
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


def _format_article(art: Article, heading: str = "##") -> None:
    lean = art.source_lean or "—"
    rel_tier = art.reliability_tier or "—"
    rel = art.source_reliability_label or art.reliability.value
    relevance = f"{art.relevance_score:.2f}" if art.relevance_score is not None else "—"
    cluster = art.cluster_id or "—"
    flags = ", ".join(art.propaganda_flags) if art.propaganda_flags else "none"
    odds = f"{art.polymarket_odds:.2f}" if art.polymarket_odds is not None else "—"
    print(f"{heading} {art.title}")
    print(f"<{art.url}>")
    print(
        f"Source: {art.source} | Lean: {lean} | Reliability tier: {rel_tier} | "
        f"Reliability: {rel} | Relevance: {relevance} | Cluster: {cluster}"
    )
    print(
        f"Propaganda: {flags} | Loaded language: {art.loaded_language} | "
        f"Propaganda flag: {art.propaganda_flag} | Polymarket: {odds}"
    )
    print()


def _print_markdown(articles: list[Article]) -> None:
    from collections import defaultdict
    from datetime import datetime

    print(f"# Situation Monitor Digest — {datetime.utcnow().strftime('%Y-%m-%d %H:%M')} UTC\n")
    if not articles:
        print("_No stories found._")
        return

    domain_articles = [a for a in articles if a.domain is not None]
    if domain_articles:
        by_domain: dict = defaultdict(list)
        undomain: list[Article] = []
        for art in articles:
            if art.domain is not None:
                by_domain[art.domain].append(art)
            else:
                undomain.append(art)
        for domain in [Domain.WORLD, Domain.MARKETS, Domain.AI]:
            if domain not in by_domain:
                continue
            print(f"## {domain.name}\n")
            for art in by_domain[domain]:
                _format_article(art, heading="###")
        for art in undomain:
            _format_article(art, heading="##")
    else:
        for art in articles:
            _format_article(art, heading="##")


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------


def _print_dual_lens(events: list) -> None:
    """Print dual-lens event blocks (only events with left or right articles)."""
    relevant = [e for e in events if e.left_articles or e.right_articles]
    if not relevant:
        return
    print("## DUAL-LENS EVENTS\n")
    for event in relevant:
        print(f"### {event.event_title}")
        print(f"spin_delta: {event.spin_delta:.1f}\n")
        if event.left_articles:
            count = len(event.left_articles)
            print(f"#### LEFT ({count} article{'s' if count != 1 else ''})")
            for aa in event.left_articles:
                print(f"- {aa.article.title} | spin_pct: {aa.spin.spin_pct:.1f}%")
                if aa.spin.receipts:
                    print(f"  rationale: {aa.spin.receipts}")
            print()
        if event.right_articles:
            count = len(event.right_articles)
            print(f"#### RIGHT ({count} article{'s' if count != 1 else ''})")
            for aa in event.right_articles:
                print(f"- {aa.article.title} | spin_pct: {aa.spin.spin_pct:.1f}%")
                if aa.spin.receipts:
                    print(f"  rationale: {aa.spin.receipts}")
            print()


def _cmd_once(config: Config) -> None:
    from situation_monitor.dual_lens import group_by_event
    articles = _ingest_and_enrich(config)
    carrier_count = sum(1 for a in articles if "carrier" in a.tags)
    if carrier_count:
        print(f"discourse-carrier articles: {carrier_count}")
    check_and_emit_alerts(articles, config.alert_threshold)
    _print_markdown(articles)
    _print_dual_lens(group_by_event(articles))


def _cmd_serve(config: Config) -> None:
    from situation_monitor.dual_lens import group_by_event
    from situation_monitor.practical import fetch_practical_movers

    _store: list = []
    _events: list = []
    _practical: list = []

    app = make_app(
        lambda: _store,
        lambda: _events,
        lambda: _practical,
    )

    def _refresh() -> None:
        articles = _ingest_and_enrich(config)
        _store[:] = articles
        _events[:] = group_by_event(articles)
        try:
            _practical[:] = fetch_practical_movers()
        except Exception:
            pass

    _refresh()
    print(f"Dashboard running on http://0.0.0.0:{config.dashboard_port}", file=sys.stderr)
    app.run(host="0.0.0.0", port=config.dashboard_port)


def _cmd_run(config: Config) -> None:
    while True:
        _cmd_once(config)
        sys.stdout.flush()
        time.sleep(config.poll_interval_seconds)


def _cmd_digest_dry_run(config: Config) -> None:
    """Assemble a Telegram digest from a fresh ingest and print it — never sends."""
    from situation_monitor.digest import daily_digest
    from situation_monitor.dual_lens import group_by_event
    from situation_monitor.practical import fetch_practical_movers

    articles = _ingest_and_enrich(config)
    events = group_by_event(articles)

    try:
        movers = fetch_practical_movers()
    except Exception:
        movers = []

    print(daily_digest(events, movers))


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
    sub.add_parser(
        "digest-dry-run",
        parents=[shared],
        help="Assemble a Telegram digest from recent events and print it — never sends",
    )

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
    elif args.cmd == "digest-dry-run":
        _cmd_digest_dry_run(config)


if __name__ == "__main__":
    main()

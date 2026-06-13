#!/usr/bin/env python3
"""End-to-end pipeline evidence runner — writes evidence.txt in the project root."""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

# Make the project importable when run as a script from the project root.
sys.path.insert(0, str(Path(__file__).parent))

from situation_monitor.config import Config, SourceDef
from situation_monitor.models import Domain
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.dual_lens import group_by_event
from situation_monitor.practical import fetch_practical_movers

# Representative sources from each lens — kept small so the run is fast.
_SOURCES = [
    ("https://www.theguardian.com/world/rss", "The Guardian World", Domain.WORLD, "left"),
    ("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera", Domain.WORLD, "left"),
    ("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC World", Domain.WORLD, "centre"),
    ("https://feeds.reuters.com/Reuters/worldNews", "Reuters World", Domain.WORLD, "centre"),
    ("https://feeds.foxnews.com/foxnews/world", "Fox News World", Domain.WORLD, "right"),
    ("https://www.washingtontimes.com/rss/headlines/news/world/", "Washington Times", Domain.WORLD, "right"),
]

_MAX_PER_SOURCE = 10


def _ollama_available(url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> None:
    cfg = Config()
    cfg.llm_backend = "ollama" if _ollama_available(cfg.ollama_url) else "stub"

    fetcher = RSSFetcher()
    articles = []
    live_sources = 0

    for url, name, domain, lens in _SOURCES:
        try:
            sd = SourceDef(url=url, name=name, domain=domain, lens=lens, description="")
            fetched = fetcher.fetch(url, source_def=sd)
            if fetched:
                articles.extend(fetched[:_MAX_PER_SOURCE])
                live_sources += 1
        except Exception:
            pass

    events = group_by_event(articles)

    # DUAL_LENS: PASS if at least one event has coverage from both left and right.
    dual_lens = "PASS" if any(ev.left_articles and ev.right_articles for ev in events) else "FAIL"

    # SPIN_PCT: average spin_pct across all annotated articles.
    all_spin = [
        aa.spin.spin_pct
        for ev in events
        for aa in (ev.left_articles + ev.right_articles + ev.center_articles)
    ]
    avg_spin = sum(all_spin) / len(all_spin) if all_spin else 0.0
    spin_pct = f"{int(avg_spin)}%"

    # MARKET: PASS if at least one practical mover was fetched.
    try:
        movers = fetch_practical_movers()
        market = "PASS" if movers else "FAIL"
    except Exception:
        market = "FAIL"

    # LENS_BALANCE: article counts per lean bucket.
    left_n = sum(len(ev.left_articles) for ev in events)
    right_n = sum(len(ev.right_articles) for ev in events)
    centre_n = sum(len(ev.center_articles) for ev in events)
    lens_balance = f"left={left_n} centre={centre_n} right={right_n}"

    lines = [
        f"DUAL_LENS: {dual_lens}",
        f"SPIN_PCT: {spin_pct}",
        f"MARKET: {market}",
        f"LIVE_SOURCES: {live_sources}",
        f"LENS_BALANCE: {lens_balance}",
    ]

    out = Path(__file__).parent / "evidence.txt"
    out.write_text("\n".join(lines) + "\n")
    print(f"Wrote {out}")
    for line in lines:
        print(line)


if __name__ == "__main__":
    main()

"""Practical market layer — FX/commodity movers and regulatory news."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Optional

from situation_monitor.ingestion.base import HttpClient

_DEFAULT_CLIENT: HttpClient | None = None


def _client(injectable: HttpClient | None) -> HttpClient:
    global _DEFAULT_CLIENT
    if injectable is not None:
        return injectable
    if _DEFAULT_CLIENT is None:
        from situation_monitor.ingestion.http_client import ScrapingClient
        _DEFAULT_CLIENT = ScrapingClient()
    return _DEFAULT_CLIENT


@dataclass
class PracticalMover:
    asset: str
    change_pct: float
    direction: str  # "up" | "down" | "neutral"
    who_it_affects: str
    what_to_watch: str
    source_url: str


# ECB reference rates RSS — daily XML (free, no key)
_ECB_FX_URL = (
    "https://www.ecb.europa.eu/rss/fxref-eurusd.html"
)

# Yahoo Finance RSS for commodities (oil, gold) and broad equity index (SPY)
_YAHOO_OIL_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=CL%3DF&region=US&lang=en-US"
_YAHOO_GOLD_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=GC%3DF&region=US&lang=en-US"
_YAHOO_SPY_URL = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=SPY&region=US&lang=en-US"

# Reuters / AP regulatory RSS
_REUTERS_GOV_URL = "https://feeds.reuters.com/reuters/politicsNews"
_AP_POLITICS_URL = "https://feeds.apnews.com/rss/apf-politics"


def _parse_rss_items(raw: bytes) -> list[tuple[str, str, Optional[str]]]:
    """Return list of (title, link, pub_date_str) from RSS bytes."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    items = []
    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        if title and link:
            items.append((title, link, pub))
    return items


def _direction(change: float) -> str:
    if change > 0:
        return "up"
    if change < 0:
        return "down"
    return "neutral"


def _extract_change_from_title(title: str) -> float:
    """Best-effort extraction of a percentage change from a headline string."""
    import re
    # Look for patterns like +1.2%, -0.5%, 1.20%
    match = re.search(r'([+-]?\d+\.?\d*)\s*%', title)
    if match:
        return float(match.group(1))
    return 0.0


def fetch_practical_movers(client: HttpClient | None = None) -> list[PracticalMover]:
    """Fetch live FX and commodity movers from free public RSS/JSON feeds."""
    http = _client(client)
    movers: list[PracticalMover] = []
    attempts = 0
    failures = 0
    last_error: Exception | None = None

    # --- ECB EUR/USD reference rate (XML) ---
    attempts += 1
    try:
        raw = http.get("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml")
        root = ET.fromstring(raw)
        ns = {"gesmes": "http://www.gesmes.org/xml/2002-08-01",
              "ecb": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}
        for cube_time in root.findall(".//ecb:Cube[@time]", ns):
            for cube in cube_time.findall("ecb:Cube", ns):
                currency = cube.get("currency", "")
                rate_str = cube.get("rate", "")
                if currency == "USD" and rate_str:
                    try:
                        rate = float(rate_str)
                        # ECB publishes rate vs EUR; express change as distance from 1.10 baseline
                        change = round((rate - 1.10) / 1.10 * 100, 2)
                        movers.append(PracticalMover(
                            asset="EUR/USD",
                            change_pct=change,
                            direction=_direction(change),
                            who_it_affects="Importers/exporters, travellers, EU-US trade",
                            what_to_watch="ECB rate decisions, US CPI, Fed speeches",
                            source_url="https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml",
                        ))
                    except ValueError:
                        pass
    except Exception as exc:
        failures += 1
        last_error = exc

    # --- Yahoo Finance RSS for oil, gold, and S&P 500 equity index ---
    for symbol, name, affects, watch, url in [
        ("CL%3DF", "WTI Crude Oil", "Energy costs, transport, petrol prices",
         "OPEC meetings, US rig count, geopolitical tension",
         _YAHOO_OIL_URL),
        ("GC%3DF", "Gold", "Safe-haven demand, jewellery, central bank reserves",
         "USD strength, inflation expectations, geopolitical risk",
         _YAHOO_GOLD_URL),
        ("SPY", "S&P 500 (SPY)", "Equity investors, pension funds, 401(k) holders",
         "Fed policy, earnings season, macro data releases",
         _YAHOO_SPY_URL),
    ]:
        attempts += 1
        try:
            raw = http.get(url)
            items = _parse_rss_items(raw)
            if items:
                title, link, _ = items[0]
                change = _extract_change_from_title(title)
                movers.append(PracticalMover(
                    asset=name,
                    change_pct=change,
                    direction=_direction(change),
                    who_it_affects=affects,
                    what_to_watch=watch,
                    source_url=link or url,
                ))
        except Exception as exc:
            failures += 1
            last_error = exc

    # A total outage (every source failed) must propagate, not masquerade as
    # "no movers"; a partial failure degrades gracefully.
    if attempts > 0 and failures == attempts and last_error is not None:
        raise last_error

    return movers


def fetch_regulatory_movers(client: HttpClient | None = None) -> list[PracticalMover]:
    """Fetch significant government/regulatory news from free RSS feeds."""
    http = _client(client)
    movers: list[PracticalMover] = []
    attempts = 0
    failures = 0
    last_error: Exception | None = None

    feeds = [
        (_REUTERS_GOV_URL, "Reuters Politics"),
        (_AP_POLITICS_URL, "AP Politics"),
    ]

    for url, source_name in feeds:
        attempts += 1
        try:
            raw = http.get(url)
            items = _parse_rss_items(raw)
            for title, link, _ in items[:5]:  # top 5 per feed
                change = _extract_change_from_title(title)
                movers.append(PracticalMover(
                    asset=f"[{source_name}] {title[:80]}",
                    change_pct=change,
                    direction=_direction(change),
                    who_it_affects="Citizens, businesses affected by new regulation/policy",
                    what_to_watch="Legislative calendar, agency announcements, court rulings",
                    source_url=link,
                ))
        except Exception as exc:
            failures += 1
            last_error = exc

    # A total outage (every feed failed) must propagate, not masquerade as
    # "no movers"; a partial failure degrades gracefully.
    if attempts > 0 and failures == attempts and last_error is not None:
        raise last_error

    return movers

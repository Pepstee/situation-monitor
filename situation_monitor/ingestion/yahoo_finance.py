"""Yahoo Finance HTML scraper for FX and commodities quotes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from situation_monitor.ingestion.base import HttpClient, ScrapingClient
from situation_monitor.models import Article, SourceReliability

_YF_BASE = "https://finance.yahoo.com/quote"

_SYMBOL_LABELS: dict[str, str] = {
    "CL=F": "WTI Crude Oil",
    "BZ=F": "Brent Crude Oil",
    "NG=F": "Natural Gas",
    "GC=F": "Gold",
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "JPYUSD=X": "JPY/USD",
}


class _QuoteParser(HTMLParser):
    """Extract price and change-percent from a Yahoo Finance quote page."""

    def __init__(self) -> None:
        super().__init__()
        self.price: str = ""
        self.change_pct: str = ""
        self._active_field: str = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "fin-streamer":
            return
        ad = dict(attrs)
        field = ad.get("data-field", "")
        if field not in ("regularMarketPrice", "regularMarketChangePercent"):
            self._active_field = ""
            return
        self._active_field = field
        # value attr already has the formatted number; text content may add '%' for pct
        val = (ad.get("value") or "").strip()
        if field == "regularMarketPrice" and not self.price and val:
            self.price = val
        elif field == "regularMarketChangePercent" and not self.change_pct and val:
            try:
                self.change_pct = f"{float(val) * 100:.2f}%"
            except ValueError:
                self.change_pct = val

    def handle_endtag(self, tag: str) -> None:
        if tag == "fin-streamer":
            self._active_field = ""

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text or not self._active_field:
            return
        if self._active_field == "regularMarketPrice" and not self.price:
            self.price = text
        elif self._active_field == "regularMarketChangePercent" and not self.change_pct:
            self.change_pct = text if "%" in text else text + "%"


def _parse_quote(html: str) -> tuple[str, str]:
    """Return (price, change_pct_string) extracted from page HTML."""
    parser = _QuoteParser()
    parser.feed(html)
    price = parser.price
    change_pct = parser.change_pct

    # JSON fallback for pages where fin-streamer is absent or JS-rendered
    if not price:
        m = re.search(r'"regularMarketPrice"\s*:\s*\{"raw"\s*:\s*([\d.]+)', html)
        if m:
            price = m.group(1)
    if not change_pct:
        m = re.search(r'"regularMarketChangePercent"\s*:\s*\{"raw"\s*:\s*(-?[\d.]+)', html)
        if m:
            try:
                change_pct = f"{float(m.group(1)) * 100:.2f}%"
            except ValueError:
                change_pct = m.group(1)

    return price, change_pct


class YahooFinanceScraper:
    """Scrapes Yahoo Finance quote pages for FX and commodity prices; no API key required."""

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client if client is not None else ScrapingClient()

    def fetch(self, symbols: list[str]) -> list[Article]:
        articles: list[Article] = []
        for symbol in symbols:
            url = f"{_YF_BASE}/{symbol}/"
            try:
                raw = self._client.get(url).decode("utf-8", errors="replace")
            except Exception:
                continue
            price, change_pct = _parse_quote(raw)
            label = _SYMBOL_LABELS.get(symbol, symbol)
            title_parts = [label]
            if price:
                title_parts.append(price)
            if change_pct:
                title_parts.append(f"({change_pct})")
            body = f"symbol={symbol} price={price} change_pct={change_pct}"
            category = "fx" if "=X" in symbol else "commodities"
            articles.append(
                Article(
                    url=url,
                    title=" ".join(title_parts),
                    source="yahoo_finance",
                    body=body,
                    published_at=datetime.now(tz=timezone.utc),
                    reliability=SourceReliability.HIGH,
                    tags=["yahoo_finance", symbol, category],
                )
            )
        return articles

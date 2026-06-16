"""Crypto RSS fetcher — parses standard RSS feeds from crypto news outlets."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from situation_monitor.ingestion.base import Fetcher, HttpClient
from situation_monitor.models import Article, SourceReliability

DEFAULT_URL = "https://www.coindesk.com/arc/outboundfeeds/rss/"


class CryptoRSSFetcher(Fetcher):
    def __init__(self, client: HttpClient | None = None) -> None:
        super().__init__(client)

    def fetch(self, url: str = DEFAULT_URL) -> list[Article]:
        try:
            raw = self._client.get(url)
        except Exception:
            return []
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            # A flaky feed can return an HTML error page or truncated body;
            # treat unparseable XML as "no articles" rather than crashing.
            return []
        channel = root.find("channel")
        if channel is None:
            return []
        articles: list[Article] = []
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            description = (item.findtext("description") or "").strip()
            published_at = None
            if pub_date := item.findtext("pubDate"):
                try:
                    published_at = parsedate_to_datetime(pub_date.strip())
                except Exception:
                    pass
            articles.append(
                Article(
                    url=link,
                    title=title,
                    source="crypto_rss",
                    body=description,
                    published_at=published_at,
                    reliability=SourceReliability.MEDIUM,
                    tags=["crypto"],
                )
            )
        return articles

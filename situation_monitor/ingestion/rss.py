"""RSS 2.0 fetcher using the stdlib XML parser."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from situation_monitor.config import SourceDef

from situation_monitor.ingestion.base import Fetcher, HttpClient
from situation_monitor.models import Article, SourceReliability


class RSSFetcher(Fetcher):
    def __init__(self, client: HttpClient | None = None) -> None:
        super().__init__(client)

    def fetch(self, url: str, source_def: SourceDef | None = None) -> list[Article]:
        raw = self._client.get(url)
        root = ET.fromstring(raw)
        channel = root.find("channel")
        if channel is None:
            return []
        source_name = (channel.findtext("title") or url).strip()
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
            article = Article(
                url=link,
                title=title,
                source=source_name,
                body=description,
                published_at=published_at,
                reliability=SourceReliability.MEDIUM,
                tags=["rss"],
            )
            if source_def is not None:
                article.domain = source_def.domain
                article.source_lean = source_def.lens
            articles.append(article)
        return articles

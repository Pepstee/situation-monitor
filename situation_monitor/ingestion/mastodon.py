"""Mastodon RSS fetcher — wraps RSSFetcher for Mastodon handles."""

from __future__ import annotations

from situation_monitor.ingestion.base import Fetcher, HttpClient
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.models import Article


class MastodonFetcher(Fetcher):
    def __init__(self, handle: str, client: HttpClient | None = None) -> None:
        super().__init__(client)
        user, instance = handle.lstrip("@").split("@", 1)
        self._username = user
        self._instance = instance
        self._rss = RSSFetcher(client=self._client)

    def fetch(self, url: str = "") -> list[Article]:
        rss_url = url or f"https://{self._instance}/@{self._username}.rss"
        articles = self._rss.fetch(rss_url)
        for article in articles:
            if "mastodon" not in article.tags:
                article.tags = article.tags + ["mastodon"]
        return articles

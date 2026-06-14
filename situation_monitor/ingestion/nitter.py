"""Nitter RSS fetcher — wraps RSSFetcher for Twitter/X handles."""

from __future__ import annotations

from situation_monitor.ingestion.base import Fetcher, HttpClient
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.models import Article

NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.poast.org",
    "https://nitter.1d4.us",
]


class NitterFetcher(Fetcher):
    def __init__(
        self,
        twitter_handle: str,
        nitter_base_url: str = "https://nitter.net",
        client: HttpClient | None = None,
    ) -> None:
        super().__init__(client)
        self._handle = twitter_handle.lstrip("@")
        self._base_url = nitter_base_url.rstrip("/")
        self._rss = RSSFetcher(client=self._client)

    def fetch(self, url: str = "") -> list[Article]:
        rss_url = url or f"{self._base_url}/{self._handle}/rss"
        articles = self._rss.fetch(rss_url)
        for article in articles:
            if "twitter" not in article.tags:
                article.tags = article.tags + ["twitter"]
        return articles

"""Hacker News fetcher via Algolia HN Search API."""

from __future__ import annotations

import json
from datetime import datetime

from situation_monitor.ingestion.base import Fetcher, HttpClient
from situation_monitor.models import Article, SourceReliability

DEFAULT_URL = "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=30"


class HNFetcher(Fetcher):
    def __init__(self, client: HttpClient | None = None) -> None:
        super().__init__(client)

    def fetch(self, url: str = DEFAULT_URL) -> list[Article]:
        raw = self._client.get(url)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, dict):
            # A hostile API may return a valid-but-non-dict top-level JSON value
            # (e.g. a list or scalar); data.get(...) would raise AttributeError
            # and crash the whole fetch. Degrade to no articles instead.
            return []
        articles: list[Article] = []
        for hit in data.get("hits", []):
            title = (hit.get("title") or "").strip()
            if not title:
                continue
            article_url = hit.get("url") or (
                f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            )
            if not article_url:
                continue
            published_at: datetime | None = None
            if created_at := hit.get("created_at"):
                # A hostile feed may set created_at to a non-string (int/list),
                # making .replace() raise AttributeError; degrade to a null
                # timestamp rather than crashing the whole fetch.
                try:
                    published_at = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError, TypeError):
                    pass
            articles.append(
                Article(
                    url=article_url,
                    title=title,
                    source="hackernews",
                    body=hit.get("story_text") or "",
                    published_at=published_at,
                    reliability=SourceReliability.MEDIUM,
                    tags=["hackernews"],
                )
            )
        return articles

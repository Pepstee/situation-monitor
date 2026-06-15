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
        except json.JSONDecodeError:
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
                try:
                    published_at = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00")
                    )
                except ValueError:
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

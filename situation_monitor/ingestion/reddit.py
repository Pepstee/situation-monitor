"""Reddit scraper via old.reddit.com JSON endpoint (no auth required)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from situation_monitor.ingestion.base import HttpClient
from situation_monitor.ingestion.http_client import ScrapingClient
from situation_monitor.models import Article, SourceReliability

_BASE = "https://old.reddit.com/r"


class RedditScraper:
    """Fetches top posts from a subreddit using old.reddit.com's public JSON endpoint."""

    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client if client is not None else ScrapingClient()

    def fetch(self, subreddit: str) -> list[Article]:
        url = f"{_BASE}/{subreddit}.json"
        raw = self._client.get(url)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return []
        if not isinstance(data, dict):
            return []
        articles: list[Article] = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            title = (post.get("title") or "").strip()
            if not title:
                continue
            post_url = (post.get("url") or "").strip()
            if not post_url:
                continue
            score = post.get("score", 0)
            published_at: datetime | None = None
            if created_utc := post.get("created_utc"):
                # A hostile feed may set created_utc to a non-numeric type
                # (TypeError on float([...])) or an out-of-range/infinite value
                # (OverflowError from fromtimestamp(inf)); both must degrade to a
                # null timestamp, never crash the whole fetch.
                try:
                    published_at = datetime.fromtimestamp(float(created_utc), tz=timezone.utc)
                except (ValueError, OSError, OverflowError, TypeError):
                    pass
            articles.append(
                Article(
                    url=post_url,
                    title=title,
                    source="reddit",
                    body=post.get("selftext") or "",
                    published_at=published_at,
                    reliability=SourceReliability.LOW,
                    tags=["reddit", f"r/{subreddit}", f"score:{score}"],
                )
            )
        return articles

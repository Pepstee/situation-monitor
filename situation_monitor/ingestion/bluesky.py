"""Bluesky fetcher via public AT Protocol XRPC API."""

from __future__ import annotations

import json
from datetime import datetime

from situation_monitor.ingestion.base import Fetcher, HttpClient
from situation_monitor.models import Article

_API_BASE = "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed"


class BlueskyFetcher(Fetcher):
    def __init__(self, handle: str, client: HttpClient | None = None) -> None:
        super().__init__(client)
        self._handle = handle

    def fetch(self, url: str = "") -> list[Article]:
        api_url = url or f"{_API_BASE}?actor={self._handle}&limit=30"
        try:
            raw = self._client.get(api_url)
            data = json.loads(raw)
        except Exception:
            return []

        if not isinstance(data, dict):
            # A hostile API may return a valid-but-non-dict top-level JSON value
            # (e.g. a list or scalar); data.get(...) would raise AttributeError
            # and crash the whole fetch. Degrade to no articles instead.
            return []

        articles: list[Article] = []
        for item in data.get("feed", []):
            post = item.get("post", {})
            record = post.get("record", {})
            text = (record.get("text") or "").strip()
            if not text:
                continue

            uri = post.get("uri", "")
            rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
            permalink = f"https://bsky.app/profile/{self._handle}/post/{rkey}"

            published_at: datetime | None = None
            if indexed_at := post.get("indexedAt"):
                # A hostile feed may set indexedAt to a non-string (int/list),
                # making .replace() raise AttributeError; degrade to a null
                # timestamp rather than crashing the whole fetch.
                try:
                    published_at = datetime.fromisoformat(
                        indexed_at.replace("Z", "+00:00")
                    )
                except (ValueError, AttributeError, TypeError):
                    pass

            articles.append(
                Article(
                    url=permalink,
                    title=text[:140],
                    source=self._handle,
                    body=text,
                    published_at=published_at,
                    tags=["bluesky"],
                )
            )
        return articles

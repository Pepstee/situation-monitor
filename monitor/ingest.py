"""Canonical local-event and fixture-backed article ingestion."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import datetime
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol

from schemas import Article, Event, SourceReliability


class BytesClient(Protocol):
    """Minimal injected byte source; this increment deliberately has no network client."""

    def get(self, source: str) -> bytes: ...


class FixtureClient:
    """Read one immutable local fixture for a fetcher-compatible interface."""

    def __init__(self, fixture: str | Path) -> None:
        self.fixture = Path(fixture)

    def get(self, source: str) -> bytes:
        del source
        return self.fixture.read_bytes()


class HNFetcher:
    """Parse Hacker News Algolia JSON supplied by an injected byte client."""

    def __init__(self, client: BytesClient) -> None:
        self._client = client

    def fetch(self, source: str = "fixture://hackernews") -> list[Article]:
        data = json.loads(self._client.get(source))
        articles: list[Article] = []
        for hit in data.get("hits", []):
            title = (hit.get("title") or "").strip()
            if not title:
                continue
            article_url = (hit.get("url") or "").strip()
            if not article_url:
                object_id = str(hit.get("objectID") or "").strip()
                if not object_id:
                    continue
                article_url = f"https://news.ycombinator.com/item?id={object_id}"
            published_at: datetime | None = None
            if created_at := hit.get("created_at"):
                try:
                    published_at = datetime.fromisoformat(
                        str(created_at).replace("Z", "+00:00")
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


class _TrendingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.repositories: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._in_heading = False
        self._in_link = False
        self._link_text: list[str] = []
        self._in_description = False
        self._description: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = attributes.get("class") or ""
        if tag == "article" and "Box-row" in classes:
            self._current = {"href": "", "title": "", "description": ""}
        elif tag == "h2" and self._current is not None:
            self._in_heading = True
        elif tag == "a" and self._in_heading and self._current is not None:
            href = (attributes.get("href") or "").strip()
            if href.startswith("/") and href.count("/") == 2:
                self._current["href"] = href
                self._in_link = True
                self._link_text = []
        elif tag == "p" and self._current is not None and "color-fg-muted" in classes:
            self._in_description = True
            self._description = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "article":
            if self._current and self._current["href"]:
                self.repositories.append(self._current)
            self._current = None
            self._in_heading = False
            self._in_link = False
            self._in_description = False
        elif tag == "h2":
            self._in_heading = False
        elif tag == "a" and self._in_link:
            if self._current is not None:
                self._current["title"] = "".join(self._link_text).strip()
            self._in_link = False
        elif tag == "p" and self._in_description:
            if self._current is not None:
                self._current["description"] = " ".join(self._description).strip()
            self._in_description = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text:
            return
        if self._in_link:
            self._link_text.append(text)
        elif self._in_description:
            self._description.append(text)


class GitHubTrendingFetcher:
    """Parse GitHub Trending HTML supplied by an injected byte client."""

    def __init__(self, client: BytesClient) -> None:
        self._client = client

    def fetch(self, source: str = "fixture://github-trending") -> list[Article]:
        parser = _TrendingParser()
        parser.feed(self._client.get(source).decode("utf-8", errors="replace"))
        articles: list[Article] = []
        for repository in parser.repositories:
            title = re.sub(r"\s+", " ", repository["title"]).strip()
            articles.append(
                Article(
                    url="https://github.com" + repository["href"],
                    title=title or repository["href"].lstrip("/"),
                    source="github_trending",
                    body=repository["description"],
                    reliability=SourceReliability.HIGH,
                    tags=["github", "trending"],
                )
            )
        return articles


class RSSFetcher:
    """Parse RSS 2.0 XML supplied by an injected byte client."""

    def __init__(self, client: BytesClient) -> None:
        self._client = client

    def fetch(self, source: str = "fixture://rss") -> list[Article]:
        root = ET.fromstring(self._client.get(source))
        channel = root.find("channel")
        if channel is None:
            return []
        source_name = (channel.findtext("title") or source).strip()
        articles: list[Article] = []
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not title or not link:
                continue
            published_at = None
            if published := item.findtext("pubDate"):
                try:
                    published_at = parsedate_to_datetime(published.strip())
                except (TypeError, ValueError):
                    pass
            articles.append(
                Article(
                    url=link,
                    title=title,
                    source=source_name,
                    body=(item.findtext("description") or "").strip(),
                    published_at=published_at,
                    reliability=SourceReliability.MEDIUM,
                    tags=["rss"],
                )
            )
        return articles


def fetch_fixture_articles(
    fixture_dir: str | Path,
    sources: Iterable[str] = ("hackernews", "github_trending", "rss"),
) -> list[Article]:
    """Run selected parsers against local fixtures only, in a stable order."""

    fixture_root = Path(fixture_dir)
    adapters = {
        "hackernews": (HNFetcher, "hn_sample.json"),
        "github_trending": (GitHubTrendingFetcher, "github_trending_sample.html"),
        "rss": (RSSFetcher, "rss_sample.xml"),
    }
    selected = set(sources)
    unknown = selected - set(adapters)
    if unknown:
        raise ValueError(f"unknown fixture source(s): {', '.join(sorted(unknown))}")

    articles: list[Article] = []
    for source_name, (adapter, fixture_name) in adapters.items():
        if source_name in selected:
            articles.extend(adapter(FixtureClient(fixture_root / fixture_name)).fetch())
    return sorted(
        articles,
        key=lambda article: (
            article.source.casefold(),
            article.title.casefold(),
            article.url,
        ),
    )


def article_record(article: Article) -> dict[str, object]:
    """Return a deterministic, JSON-safe inspection record."""

    return {
        "body": article.body,
        "published_at": article.published_at.isoformat()
        if article.published_at
        else None,
        "reliability": article.reliability.value,
        "source": article.source,
        "tags": list(article.tags),
        "title": article.title,
        "url": article.url,
    }


def load_events(file_path: str) -> tuple[list[Event], list[str]]:
    """Load and validate local JSON events while preserving graceful degradation."""

    valid_events: list[Event] = []
    error_messages: list[str] = []
    local_file = Path(file_path)
    if not local_file.exists():
        return valid_events, [f"Error: File not found: {file_path}"]

    try:
        content = local_file.read_text(encoding="utf-8")
        if not content.strip():
            return valid_events, [f"Warning: File is empty: {file_path}"]
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        return valid_events, [f"Error: Invalid JSON in {file_path}: {exc}"]
    except OSError as exc:
        return valid_events, [f"Error reading file {file_path}: {exc}"]

    if not isinstance(data, list):
        return valid_events, [
            f"Error: Expected JSON array at top level, got {type(data).__name__}"
        ]

    for index, event_data in enumerate(data):
        try:
            valid_events.append(Event.from_dict(event_data))
        except (ValueError, TypeError) as exc:
            error_messages.append(f"Error at index {index}: {exc}")
    return valid_events, error_messages

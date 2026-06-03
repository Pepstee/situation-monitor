"""GitHub Trending fetcher — parses the trending HTML page."""

from __future__ import annotations

import re
from html.parser import HTMLParser

from situation_monitor.ingestion.base import Fetcher, HttpClient
from situation_monitor.models import Article, SourceReliability

DEFAULT_URL = "https://github.com/trending"
_GH_BASE = "https://github.com"


class _TrendingParser(HTMLParser):
    """Extract repo records from GitHub's trending page HTML."""

    def __init__(self) -> None:
        super().__init__()
        self._repos: list[dict] = []
        self._cur: dict | None = None
        self._in_h2 = False
        self._collecting_link = False
        self._link_buf: list[str] = []
        self._in_desc_p = False
        self._desc_buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = dict(attrs)
        cls = ad.get("class") or ""
        if tag == "article" and "Box-row" in cls:
            self._cur = {"href": "", "title": "", "description": ""}
        elif tag == "h2" and self._cur is not None:
            self._in_h2 = True
        elif tag == "a" and self._in_h2 and self._cur is not None:
            href = (ad.get("href") or "").strip()
            if href and href.count("/") == 2:
                self._cur["href"] = href
                self._collecting_link = True
                self._link_buf = []
        elif tag == "p" and self._cur is not None and "color-fg-muted" in cls:
            self._in_desc_p = True
            self._desc_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "article":
            if self._cur and self._cur["href"]:
                self._repos.append(self._cur)
            self._cur = None
            self._in_h2 = False
            self._collecting_link = False
            self._in_desc_p = False
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "a" and self._collecting_link:
            if self._cur:
                self._cur["title"] = "".join(self._link_buf).strip()
            self._collecting_link = False
        elif tag == "p" and self._in_desc_p:
            if self._cur:
                self._cur["description"] = " ".join(self._desc_buf).strip()
            self._in_desc_p = False

    def handle_data(self, data: str) -> None:
        if self._collecting_link:
            text = data.strip()
            if text:
                self._link_buf.append(text)
        elif self._in_desc_p:
            text = data.strip()
            if text:
                self._desc_buf.append(text)


class GitHubTrendingFetcher(Fetcher):
    def __init__(self, client: HttpClient | None = None) -> None:
        super().__init__(client)

    def fetch(self, url: str = DEFAULT_URL) -> list[Article]:
        raw = self._client.get(url).decode("utf-8", errors="replace")
        parser = _TrendingParser()
        parser.feed(raw)
        articles: list[Article] = []
        for repo in parser._repos:
            title = re.sub(r"\s+", " ", repo["title"]).strip()
            if not title:
                title = repo["href"].lstrip("/")
            articles.append(
                Article(
                    url=_GH_BASE + repo["href"],
                    title=title,
                    source="github_trending",
                    body=repo.get("description", ""),
                    reliability=SourceReliability.HIGH,
                    tags=["github", "trending"],
                )
            )
        return articles

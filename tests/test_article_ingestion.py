"""Adapted union tests from both orphan Situation Monitor worktrees."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from monitor.ingest import (
    FixtureClient,
    GitHubTrendingFetcher,
    HNFetcher,
    RSSFetcher,
    fetch_fixture_articles,
)
from schemas import Article, SourceReliability


FIXTURES = Path(__file__).parent.parent / "monitor" / "fixtures"


class TestArticleModel:
    def test_reliability_contract(self):
        assert {member.value for member in SourceReliability} == {
            "high",
            "medium",
            "low",
            "unknown",
        }

    def test_minimal_article_has_independent_tag_list(self):
        first = Article(url="https://example.com/a", title="A", source="example")
        second = Article(url="https://example.com/b", title="B", source="example")
        first.tags.append("one")
        assert second.tags == []
        assert first.reliability is SourceReliability.UNKNOWN

    def test_explicit_fields_are_preserved(self):
        published = datetime(2026, 6, 3, 8, 30)
        article = Article(
            url="https://example.com/story",
            title="Story",
            source="example",
            body="Body",
            published_at=published,
            reliability=SourceReliability.HIGH,
            tags=["tech"],
        )
        assert article.published_at == published
        assert article.tags == ["tech"]

    @pytest.mark.parametrize("field", ["url", "title", "source"])
    @pytest.mark.parametrize("value", ["", "   "])
    def test_required_text_rejects_empty_and_whitespace(self, field, value):
        values = {"url": "u", "title": "t", "source": "s"}
        values[field] = value
        with pytest.raises(ValueError, match=field):
            Article(**values)

    def test_reliability_rejects_untyped_string(self):
        with pytest.raises(TypeError, match="SourceReliability"):
            Article(url="u", title="t", source="s", reliability="high")

    def test_tags_reject_non_string_member(self):
        with pytest.raises(TypeError, match="list of strings"):
            Article(url="u", title="t", source="s", tags=[1])


class TestFixtureIngestion:
    def test_fixture_client_ignores_locator_and_returns_exact_bytes(self):
        fixture = FIXTURES / "hn_sample.json"
        client = FixtureClient(fixture)
        assert client.get("never-contact-this-host") == fixture.read_bytes()

    def test_hacker_news_fixture_is_normalized(self):
        articles = HNFetcher(FixtureClient(FIXTURES / "hn_sample.json")).fetch()
        assert len(articles) == 5
        assert all(article.source == "hackernews" for article in articles)
        assert all(
            article.reliability is SourceReliability.MEDIUM for article in articles
        )
        assert all(article.published_at is not None for article in articles)

    def test_hacker_news_missing_url_uses_item_page(self):
        articles = HNFetcher(FixtureClient(FIXTURES / "hn_sample.json")).fetch()
        assert any(article.url.endswith("item?id=42345680") for article in articles)

    def test_github_fixture_is_normalized(self):
        articles = GitHubTrendingFetcher(
            FixtureClient(FIXTURES / "github_trending_sample.html")
        ).fetch()
        assert len(articles) == 5
        assert all(
            article.url.startswith("https://github.com/") for article in articles
        )
        assert all(article.source == "github_trending" for article in articles)
        assert all(
            article.reliability is SourceReliability.HIGH for article in articles
        )
        assert any(article.body for article in articles)

    def test_rss_fixture_is_normalized(self):
        articles = RSSFetcher(FixtureClient(FIXTURES / "rss_sample.xml")).fetch()
        assert len(articles) == 5
        assert all(article.source == "Tech News Daily" for article in articles)
        assert all(article.published_at is not None for article in articles)
        assert all(article.tags == ["rss"] for article in articles)

    def test_source_selection_is_bounded(self):
        articles = fetch_fixture_articles(FIXTURES, ["hackernews"])
        assert len(articles) == 5
        assert {article.source for article in articles} == {"hackernews"}

    def test_unknown_source_fails_closed(self):
        with pytest.raises(ValueError, match="unknown fixture source"):
            fetch_fixture_articles(FIXTURES, ["unknown"])

    def test_union_output_order_is_deterministic(self):
        first = fetch_fixture_articles(FIXTURES)
        second = fetch_fixture_articles(FIXTURES)
        assert first == second
        keys = [
            (item.source.casefold(), item.title.casefold(), item.url) for item in first
        ]
        assert keys == sorted(keys)


@pytest.fixture
def source_http_server():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            name = "hn_sample.json" if self.path.startswith("/api/") else "github_trending_sample.html"
            data = (FIXTURES / name).read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


def test_live_cli_uses_real_http_and_shared_parsers(source_http_server, monkeypatch, capsys):
    import json
    from urllib.parse import urlsplit
    from monitor.cli import main
    from monitor.ingest import HTTPClient

    original = HTTPClient.get
    requested = []

    def redirected(self, source):
        requested.append(source)
        parsed = urlsplit(source)
        return original(self, source_http_server + parsed.path + "?" + parsed.query)

    monkeypatch.setattr(HTTPClient, "get", redirected)
    assert main(["fetch", "--live", "--limit", "5", "--language", "python", "--since", "weekly"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["network_attempted"] is True
    assert output["mode"] == "live-fetch" and output["count"] == 10
    assert requested == [
        "https://hn.algolia.com/api/v1/search?tags=front_page&hitsPerPage=5",
        "https://github.com/trending/python?since=weekly",
    ]


def test_http_response_limit_is_enforced(source_http_server):
    from monitor.ingest import HTTPClient
    with pytest.raises(ValueError, match="byte limit"):
        HTTPClient(max_bytes=10).get(source_http_server + "/api/")


def test_invalid_live_rss_is_rejected_before_network(monkeypatch):
    from monitor.ingest import HTTPClient, fetch_live_articles

    def forbidden(*args):
        raise AssertionError("network request before validating sources")

    monkeypatch.setattr(HTTPClient, "get", forbidden)
    with pytest.raises(ValueError, match="rss-url"):
        fetch_live_articles(["rss"])

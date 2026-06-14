"""Unit tests for the CLI helper functions in situation_monitor.__main__.

These pin the exact behaviour of the source-resolution and config helpers that
the `once`/`serve`/`run` pipelines depend on. They exist so that a regression in
any branch — URL detection, shorthand scheme resolution, fetcher selection — is
caught directly, not only via the end-to-end digest output.
"""

from __future__ import annotations

import pytest

from situation_monitor.__main__ import (
    _GITHUB_TRENDING_DEFAULT_URL,
    _HN_DEFAULT_URL,
    _LocalFileClient,
    _is_url,
    _load_config,
    _resolve_source,
    _select_fetcher,
)
from situation_monitor.config import Config
from situation_monitor.ingestion.crypto import CryptoRSSFetcher
from situation_monitor.ingestion.github_trending import GitHubTrendingFetcher
from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.ingestion.rss import RSSFetcher


class TestLoadConfig:
    def test_returns_config_instance_with_no_path(self):
        config = _load_config(None)
        assert config is not None
        assert isinstance(config, Config)

    def test_unparseable_path_falls_back_to_defaults(self, tmp_path):
        bad = tmp_path / "not-json.json"
        bad.write_text("{ this is not json")
        config = _load_config(str(bad))
        assert isinstance(config, Config)

    def test_env_override_applied(self, monkeypatch):
        monkeypatch.setenv("SM_SOURCES", "a.xml,b.xml")
        config = _load_config(None)
        assert config.sources == ["a.xml", "b.xml"]


class TestLocalFileClient:
    def test_get_returns_exact_file_bytes(self, tmp_path):
        payload = b"<rss>hello</rss>"
        path = tmp_path / "feed.xml"
        path.write_bytes(payload)
        assert _LocalFileClient().get(str(path)) == payload

    def test_get_returns_non_empty_for_non_empty_file(self, tmp_path):
        path = tmp_path / "feed.xml"
        path.write_bytes(b"data")
        result = _LocalFileClient().get(str(path))
        assert result is not None
        assert len(result) == 4


class TestIsUrl:
    @pytest.mark.parametrize("value", ["http://example.com", "https://example.com/feed"])
    def test_http_and_https_are_urls(self, value):
        assert _is_url(value) is True

    @pytest.mark.parametrize(
        "value", ["/local/path/feed.xml", "feed.xml", "ftp://x", "hn://", ""]
    )
    def test_non_http_is_not_a_url(self, value):
        assert _is_url(value) is False


class TestResolveSource:
    def test_hn_shorthand_resolves_to_default_url(self):
        assert _resolve_source("hn://") == _HN_DEFAULT_URL

    def test_github_trending_shorthand_resolves_to_default_url(self):
        assert _resolve_source("github_trending://") == _GITHUB_TRENDING_DEFAULT_URL

    def test_plain_url_passes_through_unchanged(self):
        url = "http://example.com/rss.xml"
        assert _resolve_source(url) == url

    def test_local_path_passes_through_unchanged(self):
        assert _resolve_source("tests/fixtures/rss_sample.xml") == "tests/fixtures/rss_sample.xml"


class TestSelectFetcher:
    def test_hn_scheme_selects_hn_fetcher(self):
        assert isinstance(_select_fetcher("hn://"), HNFetcher)

    def test_hn_algolia_host_selects_hn_fetcher(self):
        assert isinstance(_select_fetcher("https://hn.algolia.com/api/v1/search"), HNFetcher)

    def test_github_scheme_selects_github_fetcher(self):
        assert isinstance(_select_fetcher("github_trending://"), GitHubTrendingFetcher)

    def test_github_host_selects_github_fetcher(self):
        assert isinstance(_select_fetcher("https://github.com/trending"), GitHubTrendingFetcher)

    def test_crypto_host_selects_crypto_fetcher(self):
        assert isinstance(_select_fetcher("https://www.coindesk.com/arc/outboundfeeds/rss/"), CryptoRSSFetcher)

    def test_plain_rss_selects_rss_fetcher(self):
        assert isinstance(_select_fetcher("https://example.com/rss.xml"), RSSFetcher)

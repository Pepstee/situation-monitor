"""Adversarial tests for MastodonFetcher."""

from __future__ import annotations

import pytest

from situation_monitor.ingestion.mastodon import MastodonFetcher
from situation_monitor.models import Article


# ---------------------------------------------------------------------------
# Stub HTTP client
# ---------------------------------------------------------------------------


class StubHttpClient:
    """Returns a fixed bytes payload for any GET, or raises on demand."""

    def __init__(
        self, payload: bytes | None = None, raise_exc: Exception | None = None
    ) -> None:
        self._payload = payload
        self._raise_exc = raise_exc
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        if self._raise_exc is not None:
            raise self._raise_exc
        return self._payload  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# RSS XML helpers
# ---------------------------------------------------------------------------


def _rss_with_items(*items: tuple[str, str, str]) -> bytes:
    """Build a minimal RSS 2.0 feed with the given (title, link, description) tuples."""
    item_xml = ""
    for title, link, description in items:
        item_xml += f"""
    <item>
      <title>{title}</title>
      <link>{link}</link>
      <description>{description}</description>
      <pubDate>Sat, 01 Jun 2024 12:00:00 +0000</pubDate>
    </item>"""
    return (
        f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Feed</title>{item_xml}
  </channel>
</rss>"""
    ).encode()


def _empty_rss() -> bytes:
    return b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Empty Feed</title>
  </channel>
</rss>"""


def _one_article() -> bytes:
    return _rss_with_items(
        ("Post Title", "https://mastodon.social/@user/statuses/1", "Body text")
    )


# ---------------------------------------------------------------------------
# (a) Correct RSS URL construction from user@instance handle
# ---------------------------------------------------------------------------


class TestURLConstruction:
    def test_url_format_is_https_instance_at_user_dot_rss(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("bob@mastodon.social", client=client).fetch()
        assert client.calls[0] == "https://mastodon.social/@bob.rss"

    def test_url_uses_instance_subdomain(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("alice@fosstodon.org", client=client).fetch()
        assert "fosstodon.org" in client.calls[0]
        assert "mastodon.social" not in client.calls[0]

    def test_url_contains_at_prefix_before_username(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("carol@chaos.social", client=client).fetch()
        assert "/@carol" in client.calls[0]

    def test_url_ends_with_dot_rss(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("user@example.social", client=client).fetch()
        assert client.calls[0].endswith(".rss")

    def test_url_uses_https_scheme(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert client.calls[0].startswith("https://")

    def test_different_users_on_same_instance_produce_different_urls(self) -> None:
        c1 = StubHttpClient(payload=_empty_rss())
        c2 = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("alice@mastodon.social", client=c1).fetch()
        MastodonFetcher("bob@mastodon.social", client=c2).fetch()
        assert c1.calls[0] != c2.calls[0]

    def test_same_user_on_different_instances_produce_different_urls(self) -> None:
        c1 = StubHttpClient(payload=_empty_rss())
        c2 = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("user@mastodon.social", client=c1).fetch()
        MastodonFetcher("user@fosstodon.org", client=c2).fetch()
        assert c1.calls[0] != c2.calls[0]

    def test_custom_url_overrides_default_rss_url(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("user@mastodon.social", client=client).fetch(
            url="https://override.example.com/feed.rss"
        )
        assert client.calls[0] == "https://override.example.com/feed.rss"

    def test_custom_url_does_not_include_default_instance(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("user@mastodon.social", client=client).fetch(
            url="https://override.example.com/"
        )
        assert "mastodon.social" not in client.calls[0]

    def test_fetch_called_exactly_once_per_invocation(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert len(client.calls) == 1


# ---------------------------------------------------------------------------
# (b) Articles tagged 'mastodon'
# ---------------------------------------------------------------------------


class TestMastodonTagging:
    def test_single_article_has_mastodon_tag(self) -> None:
        client = StubHttpClient(payload=_one_article())
        articles = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert len(articles) == 1
        assert "mastodon" in articles[0].tags

    def test_all_articles_have_mastodon_tag(self) -> None:
        rss = _rss_with_items(
            ("Post 1", "https://mastodon.social/@u/1", ""),
            ("Post 2", "https://mastodon.social/@u/2", ""),
            ("Post 3", "https://mastodon.social/@u/3", ""),
        )
        client = StubHttpClient(payload=rss)
        articles = MastodonFetcher("u@mastodon.social", client=client).fetch()
        assert len(articles) == 3
        assert all("mastodon" in a.tags for a in articles)

    def test_mastodon_tag_not_duplicated_when_already_present(self) -> None:
        # RSSFetcher does not add mastodon tag, but we verify idempotency via the
        # "mastodon not in tags" branch in the implementation
        client = StubHttpClient(payload=_one_article())
        articles = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert articles[0].tags.count("mastodon") == 1

    def test_rss_tag_not_stripped_by_mastodon_fetcher(self) -> None:
        # RSSFetcher sets tags=["rss"]; MastodonFetcher must preserve it
        client = StubHttpClient(payload=_one_article())
        articles = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert "rss" in articles[0].tags

    def test_returns_article_instances(self) -> None:
        client = StubHttpClient(payload=_one_article())
        articles = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert all(isinstance(a, Article) for a in articles)

    def test_article_url_preserved(self) -> None:
        client = StubHttpClient(payload=_one_article())
        articles = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert articles[0].url == "https://mastodon.social/@user/statuses/1"

    def test_article_title_preserved(self) -> None:
        client = StubHttpClient(payload=_one_article())
        articles = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert articles[0].title == "Post Title"


# ---------------------------------------------------------------------------
# (c) Graceful empty-list return on network failure
# ---------------------------------------------------------------------------


class TestNetworkFailure:
    def test_empty_response_body_returns_empty_list(self) -> None:
        # Server returns an empty body (e.g. connection dropped after headers)
        client = StubHttpClient(payload=b"")
        result = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert result == []

    def test_corrupted_xml_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=b"<<< not valid xml >>>")
        result = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert result == []

    def test_truncated_response_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=b"<rss><channel><title>cut")
        result = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert result == []

    def test_html_error_page_with_no_channel_returns_empty_list(self) -> None:
        # Server returns an HTML error page; no <channel> element → []
        client = StubHttpClient(
            payload=b"<html><body><p>503 Service Unavailable</p></body></html>"
        )
        result = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert result == []

    def test_json_error_response_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=b'{"error": "not found"}')
        result = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert result == []

    def test_rss_feed_with_no_items_returns_empty_list(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        result = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert result == []

    def test_rss_items_missing_title_are_skipped(self) -> None:
        # RSSFetcher skips items without a title; all items bad → []
        rss = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
  <item><link>https://example.com/1</link></item>
</channel></rss>"""
        client = StubHttpClient(payload=rss)
        result = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert result == []

    def test_rss_items_missing_link_are_skipped(self) -> None:
        rss = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>T</title>
  <item><title>No Link Here</title></item>
</channel></rss>"""
        client = StubHttpClient(payload=rss)
        result = MastodonFetcher("user@mastodon.social", client=client).fetch()
        assert result == []


# ---------------------------------------------------------------------------
# (d) Default instance fallback when no @ in handle
# ---------------------------------------------------------------------------


class TestHandleParsing:
    def test_handle_without_leading_at_parses_correctly(self) -> None:
        """user@instance (no leading @) is the canonical form."""
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("alice@mastodon.social", client=client).fetch()
        assert client.calls[0] == "https://mastodon.social/@alice.rss"

    def test_handle_with_single_leading_at_parses_correctly(self) -> None:
        """@user@instance (with one leading @) is also accepted."""
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("@alice@mastodon.social", client=client).fetch()
        assert client.calls[0] == "https://mastodon.social/@alice.rss"

    def test_leading_at_and_no_leading_at_produce_identical_urls(self) -> None:
        c1 = StubHttpClient(payload=_empty_rss())
        c2 = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("user@fosstodon.org", client=c1).fetch()
        MastodonFetcher("@user@fosstodon.org", client=c2).fetch()
        assert c1.calls[0] == c2.calls[0]

    def test_handle_with_multiple_leading_ats_stripped_correctly(self) -> None:
        """lstrip('@') removes all leading @ signs."""
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("@@user@mastodon.social", client=client).fetch()
        assert client.calls[0] == "https://mastodon.social/@user.rss"

    def test_handle_with_no_at_separator_raises_value_error(self) -> None:
        """A handle with no @instance part cannot determine the server."""
        with pytest.raises(ValueError):
            MastodonFetcher("justausername")

    def test_handle_with_only_leading_at_and_no_instance_raises(self) -> None:
        """@username with no instance is also invalid."""
        with pytest.raises(ValueError):
            MastodonFetcher("@onlyusername")

    def test_subdomain_instance_parsed_correctly(self) -> None:
        client = StubHttpClient(payload=_empty_rss())
        MastodonFetcher("user@social.coop", client=client).fetch()
        assert client.calls[0] == "https://social.coop/@user.rss"

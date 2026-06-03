"""Tests for GitHubTrendingFetcher using the bundled HTML fixture — zero network calls."""

from __future__ import annotations

import pathlib

from situation_monitor.ingestion.github_trending import GitHubTrendingFetcher
from situation_monitor.models import Article, SourceReliability

FIXTURE_PATH = pathlib.Path(__file__).parent / "fixtures" / "github_trending.html"


class _FakeClient:
    """In-memory HTTP stub — returns pre-loaded bytes, never touches the network."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def get(self, url: str) -> bytes:  # noqa: ARG002
        return self._data


def _fetcher(data: bytes) -> GitHubTrendingFetcher:
    return GitHubTrendingFetcher(client=_FakeClient(data))


def _from_fixture() -> GitHubTrendingFetcher:
    return _fetcher(FIXTURE_PATH.read_bytes())


def _html(*articles_html: str) -> bytes:
    body = "\n".join(articles_html)
    return f"<html><body>{body}</body></html>".encode()


def _box_row(href: str, title: str, desc: str = "Some description") -> str:
    return (
        f'<article class="Box-row">'
        f'<h2><a href="{href}">{title}</a></h2>'
        f'<p class="color-fg-muted">{desc}</p>'
        f"</article>"
    )


class TestGitHubTrendingFetcherHappyPath:
    def test_returns_nonempty_list(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        assert len(articles) > 0

    def test_at_least_two_repos_from_fixture(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        assert len(articles) >= 2

    def test_all_items_are_articles(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert isinstance(article, Article)

    def test_all_tagged_github_and_trending(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert "github" in article.tags
            assert "trending" in article.tags

    def test_source_is_github_trending(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.source == "github_trending"

    def test_reliability_is_high(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.reliability == SourceReliability.HIGH

    def test_urls_start_with_https_github_com(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.url.startswith("https://github.com/"), (
                f"Expected absolute github.com URL, got: {article.url!r}"
            )

    def test_titles_are_non_empty(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.title, f"Empty title on article: {article.url!r}"

    def test_urls_are_non_empty(self) -> None:
        for article in _from_fixture().fetch("http://fake"):
            assert article.url

    def test_parses_repo_title_from_fixture(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        titles = {a.title for a in articles}
        assert "vinta / awesome-python" in titles

    def test_parses_repo_url_from_fixture(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        urls = {a.url for a in articles}
        assert "https://github.com/vinta/awesome-python" in urls

    def test_parses_description_from_fixture(self) -> None:
        articles = _from_fixture().fetch("http://fake")
        linux = next((a for a in articles if "torvalds/linux" in a.url), None)
        assert linux is not None
        assert "Linux kernel" in linux.body

    def test_multiline_title_whitespace_normalised_from_fixture(self) -> None:
        # torvalds/linux title is split across lines in the fixture HTML
        articles = _from_fixture().fetch("http://fake")
        torvalds = next((a for a in articles if "torvalds" in a.url), None)
        assert torvalds is not None
        assert torvalds.title == "torvalds / linux"
        assert "  " not in torvalds.title


class TestGitHubTrendingFetcherEdgeCases:
    def test_empty_html_returns_empty_list(self) -> None:
        assert _fetcher(b"").fetch("http://fake") == []

    def test_html_without_box_row_returns_empty_list(self) -> None:
        html = b"<html><body><article>No Box-row class here</article></body></html>"
        assert _fetcher(html).fetch("http://fake") == []

    def test_article_without_href_is_filtered_out(self) -> None:
        html = _html(
            '<article class="Box-row">'
            '<h2><a>No href at all</a></h2>'
            '<p class="color-fg-muted">Desc</p>'
            "</article>"
        )
        assert _fetcher(html).fetch("http://fake") == []

    def test_href_with_three_slashes_is_ignored(self) -> None:
        html = _html(
            _box_row("/user/repo/extra", "Should be ignored"),
            _box_row("/valid/repo", "Valid Repo"),
        )
        articles = _fetcher(html).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].url == "https://github.com/valid/repo"

    def test_url_is_absolute_github_path(self) -> None:
        html = _html(_box_row("/myuser/myrepo", "myuser / myrepo"))
        articles = _fetcher(html).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].url == "https://github.com/myuser/myrepo"

    def test_title_single_spaces_after_normalisation(self) -> None:
        html = b"""<html><body>
        <article class="Box-row">
          <h2><a href="/owner/repo">  owner  /  repo  </a></h2>
          <p class="color-fg-muted">Desc</p>
        </article>
        </body></html>"""
        articles = _fetcher(html).fetch("http://fake")
        assert len(articles) == 1
        title = articles[0].title
        assert "  " not in title
        assert title == title.strip()
        assert title == "owner / repo"

    def test_title_leading_trailing_whitespace_stripped(self) -> None:
        html = _html(_box_row("/a/b", "  a / b  "))
        articles = _fetcher(html).fetch("http://fake")
        assert articles[0].title == articles[0].title.strip()

    def test_empty_link_text_falls_back_to_href(self) -> None:
        # When the <a> tag has only whitespace text, title falls back to href.lstrip("/")
        html = b"""<html><body>
        <article class="Box-row">
          <h2><a href="/user/no-title-repo">   </a></h2>
          <p class="color-fg-muted">Desc</p>
        </article>
        </body></html>"""
        articles = _fetcher(html).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].title == "user/no-title-repo"

    def test_description_extracted_correctly(self) -> None:
        html = _html(_box_row("/user/repo", "user / repo", "A fantastic project for testing purposes"))
        articles = _fetcher(html).fetch("http://fake")
        assert articles[0].body == "A fantastic project for testing purposes"

    def test_p_without_color_fg_muted_not_used_as_description(self) -> None:
        html = _html(
            '<article class="Box-row">'
            '<h2><a href="/user/repo">user / repo</a></h2>'
            "<p>Not a description — wrong class</p>"
            "</article>"
        )
        articles = _fetcher(html).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].body == ""

    def test_tags_list_is_exactly_github_trending(self) -> None:
        html = _html(_box_row("/x/y", "X / Y"))
        articles = _fetcher(html).fetch("http://fake")
        assert articles[0].tags == ["github", "trending"]

    def test_multiple_repos_all_returned(self) -> None:
        html = _html(
            _box_row("/a/b", "A / B", "First"),
            _box_row("/c/d", "C / D", "Second"),
            _box_row("/e/f", "E / F", "Third"),
        )
        articles = _fetcher(html).fetch("http://fake")
        assert len(articles) == 3
        urls = {a.url for a in articles}
        assert urls == {
            "https://github.com/a/b",
            "https://github.com/c/d",
            "https://github.com/e/f",
        }

    def test_multiple_repos_all_tagged_github_and_trending(self) -> None:
        html = _html(
            _box_row("/a/b", "A / B"),
            _box_row("/c/d", "C / D"),
        )
        for article in _fetcher(html).fetch("http://fake"):
            assert "github" in article.tags
            assert "trending" in article.tags

    def test_article_with_box_row_class_among_others_is_parsed(self) -> None:
        # "Box-row" must match even when mixed with other classes
        html = b"""<html><body>
        <article class="Box-row d-flex flex-justify-between my-1 py-2">
          <h2><a href="/multi/class">multi / class</a></h2>
          <p class="col-9 color-fg-muted my-1">Description here</p>
        </article>
        </body></html>"""
        articles = _fetcher(html).fetch("http://fake")
        assert len(articles) == 1
        assert articles[0].url == "https://github.com/multi/class"

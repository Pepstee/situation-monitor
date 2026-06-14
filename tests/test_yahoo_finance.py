"""Tests for YahooFinanceScraper — zero network calls via injected HttpClient."""

from __future__ import annotations

from situation_monitor.ingestion.yahoo_finance import YahooFinanceScraper
from situation_monitor.models import Article, SourceReliability

_REQUIRED_SYMBOLS = ["CL=F", "BZ=F", "NG=F", "GC=F", "EURUSD=X", "GBPUSD=X", "JPYUSD=X"]


def _fin_streamers(price: str, change_pct_raw: str) -> str:
    return (
        f'<fin-streamer data-field="regularMarketPrice" value="{price}">{price}</fin-streamer>'
        f'<fin-streamer data-field="regularMarketChangePercent" value="{change_pct_raw}">{change_pct_raw}</fin-streamer>'
    )


def _page(price: str = "75.42", change_pct_raw: str = "-0.0231") -> bytes:
    return (
        "<html><body>"
        + _fin_streamers(price, change_pct_raw)
        + "</body></html>"
    ).encode()


class _FakeClient:
    """Returns the same bytes for every URL — never touches the network."""

    def __init__(self, responses: dict[str, bytes] | None = None, default: bytes = b"") -> None:
        self._responses = responses or {}
        self._default = default
        self.calls: list[str] = []

    def get(self, url: str) -> bytes:
        self.calls.append(url)
        return self._responses.get(url, self._default)


class _ErrorClient:
    def get(self, url: str) -> bytes:  # noqa: ARG002
        raise OSError("network error")


def _scraper(responses: dict[str, bytes] | None = None, default: bytes = _page()) -> YahooFinanceScraper:
    return YahooFinanceScraper(client=_FakeClient(responses=responses, default=default))


class TestYahooFinanceScraperHappyPath:
    def test_returns_list(self) -> None:
        articles = _scraper().fetch(["CL=F"])
        assert isinstance(articles, list)

    def test_one_article_per_symbol(self) -> None:
        articles = _scraper().fetch(["CL=F", "GC=F"])
        assert len(articles) == 2

    def test_all_items_are_articles(self) -> None:
        for article in _scraper().fetch(["CL=F"]):
            assert isinstance(article, Article)

    def test_source_is_yahoo_finance(self) -> None:
        for article in _scraper().fetch(["CL=F"]):
            assert article.source == "yahoo_finance"

    def test_reliability_is_high(self) -> None:
        for article in _scraper().fetch(["CL=F"]):
            assert article.reliability == SourceReliability.HIGH

    def test_url_contains_symbol(self) -> None:
        articles = _scraper().fetch(["CL=F"])
        assert "CL=F" in articles[0].url

    def test_url_is_yahoo_finance(self) -> None:
        articles = _scraper().fetch(["EURUSD=X"])
        assert "finance.yahoo.com" in articles[0].url

    def test_body_contains_symbol(self) -> None:
        articles = _scraper().fetch(["CL=F"])
        assert "CL=F" in articles[0].body

    def test_body_contains_price(self) -> None:
        articles = _scraper(default=_page("75.42")).fetch(["CL=F"])
        assert "75.42" in articles[0].body

    def test_body_contains_change_pct(self) -> None:
        articles = _scraper(default=_page("75.42", "-0.0231")).fetch(["CL=F"])
        assert "change_pct=" in articles[0].body

    def test_tags_include_symbol(self) -> None:
        articles = _scraper().fetch(["GC=F"])
        assert "GC=F" in articles[0].tags

    def test_tags_include_yahoo_finance(self) -> None:
        articles = _scraper().fetch(["GC=F"])
        assert "yahoo_finance" in articles[0].tags

    def test_fx_symbol_tagged_fx(self) -> None:
        articles = _scraper().fetch(["EURUSD=X"])
        assert "fx" in articles[0].tags

    def test_commodity_symbol_tagged_commodities(self) -> None:
        articles = _scraper().fetch(["CL=F"])
        assert "commodities" in articles[0].tags

    def test_title_non_empty(self) -> None:
        for article in _scraper().fetch(["CL=F"]):
            assert article.title

    def test_published_at_set(self) -> None:
        articles = _scraper().fetch(["CL=F"])
        assert articles[0].published_at is not None

    def test_price_in_title_when_available(self) -> None:
        articles = _scraper(default=_page("75.42")).fetch(["CL=F"])
        assert "75.42" in articles[0].title


class TestYahooFinanceScraperAllRequiredSymbols:
    def test_all_required_symbols_produce_articles(self) -> None:
        articles = _scraper().fetch(_REQUIRED_SYMBOLS)
        assert len(articles) == len(_REQUIRED_SYMBOLS)

    def test_each_required_symbol_has_body_with_symbol(self) -> None:
        articles = _scraper().fetch(_REQUIRED_SYMBOLS)
        for article in articles:
            assert any(sym in article.body for sym in _REQUIRED_SYMBOLS)

    def test_fx_symbols_tagged_fx(self) -> None:
        fx_symbols = [s for s in _REQUIRED_SYMBOLS if "=X" in s]
        articles = _scraper().fetch(fx_symbols)
        for article in articles:
            assert "fx" in article.tags

    def test_commodity_symbols_tagged_commodities(self) -> None:
        comm_symbols = [s for s in _REQUIRED_SYMBOLS if "=X" not in s]
        articles = _scraper().fetch(comm_symbols)
        for article in articles:
            assert "commodities" in article.tags


class TestYahooFinanceScraperParsing:
    def test_parses_price_from_fin_streamer(self) -> None:
        html = _page("123.45")
        articles = _scraper(default=html).fetch(["GC=F"])
        assert "123.45" in articles[0].body

    def test_parses_change_pct_from_fin_streamer(self) -> None:
        html = _page("100.0", "0.0150")
        articles = _scraper(default=html).fetch(["GC=F"])
        assert "change_pct=" in articles[0].body
        # 0.015 raw -> 1.50% or similar
        assert "1.50" in articles[0].body or "1.5" in articles[0].body

    def test_json_fallback_parses_price(self) -> None:
        html = b'<html><body><script>{"regularMarketPrice":{"raw":99.99}}</script></body></html>'
        articles = _scraper(default=html).fetch(["CL=F"])
        assert "99.99" in articles[0].body

    def test_json_fallback_parses_change_pct(self) -> None:
        html = b'<html><body><script>{"regularMarketChangePercent":{"raw":-0.025}}</script></body></html>'
        articles = _scraper(default=html).fetch(["CL=F"])
        assert "change_pct=" in articles[0].body

    def test_empty_html_still_produces_article(self) -> None:
        articles = _scraper(default=b"<html></html>").fetch(["CL=F"])
        assert len(articles) == 1
        assert "CL=F" in articles[0].body

    def test_no_fin_streamer_price_empty_in_body(self) -> None:
        articles = _scraper(default=b"<html></html>").fetch(["CL=F"])
        assert "price=" in articles[0].body


class TestYahooFinanceScraperEdgeCases:
    def test_empty_symbol_list_returns_empty(self) -> None:
        assert _scraper().fetch([]) == []

    def test_network_error_skips_symbol(self) -> None:
        scraper = YahooFinanceScraper(client=_ErrorClient())
        articles = scraper.fetch(["CL=F", "GC=F"])
        assert articles == []

    def test_partial_network_error_returns_successful_symbols(self) -> None:
        client = _FakeClient(
            responses={"https://finance.yahoo.com/quote/GC=F/": _page("1900.0")},
            default=b"",
        )

        class _PartialClient:
            def get(self, url: str) -> bytes:
                if "GC=F" in url:
                    return _page("1900.0")
                raise OSError("fail")

        scraper = YahooFinanceScraper(client=_PartialClient())
        articles = scraper.fetch(["CL=F", "GC=F"])
        assert len(articles) == 1
        assert "GC=F" in articles[0].tags

    def test_client_called_once_per_symbol(self) -> None:
        client = _FakeClient(default=_page())
        YahooFinanceScraper(client=client).fetch(["CL=F", "GC=F", "EURUSD=X"])
        assert len(client.calls) == 3

    def test_injected_client_used_not_real_network(self) -> None:
        # If a real network call were made, the URL would resolve; we return known bytes instead
        client = _FakeClient(default=_page("42.00"))
        articles = YahooFinanceScraper(client=client).fetch(["CL=F"])
        assert "42.00" in articles[0].body

    def test_duplicate_symbols_produce_two_articles(self) -> None:
        articles = _scraper().fetch(["CL=F", "CL=F"])
        assert len(articles) == 2

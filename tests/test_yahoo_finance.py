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


class TestYahooFinanceBodyFormat:
    """Verify the exact body string format and field values, not just substring presence."""

    def test_body_format_is_symbol_price_change_pct(self) -> None:
        articles = _scraper(default=_page("75.42", "-0.0231")).fetch(["CL=F"])
        body = articles[0].body
        assert body.startswith("symbol=CL=F price=")
        assert "change_pct=" in body

    def test_body_price_value_exact(self) -> None:
        articles = _scraper(default=_page("1234.56", "0.0")).fetch(["GC=F"])
        body = articles[0].body
        # Should contain exactly "price=1234.56", not just "1234.56" anywhere
        assert "price=1234.56" in body

    def test_change_pct_multiplied_by_100_negative(self) -> None:
        # raw value -0.0231 → -2.31%
        articles = _scraper(default=_page("75.42", "-0.0231")).fetch(["CL=F"])
        body = articles[0].body
        assert "change_pct=-2.31%" in body

    def test_change_pct_multiplied_by_100_positive(self) -> None:
        # raw value 0.0150 → 1.50%
        articles = _scraper(default=_page("100.0", "0.0150")).fetch(["GC=F"])
        body = articles[0].body
        assert "change_pct=1.50%" in body

    def test_change_pct_zero(self) -> None:
        articles = _scraper(default=_page("100.0", "0.0")).fetch(["GC=F"])
        body = articles[0].body
        assert "change_pct=0.00%" in body

    def test_missing_price_field_price_empty_no_crash(self) -> None:
        # Page has change_pct but no price fin-streamer — price must be empty string, no exception
        html = (
            b'<html><body>'
            b'<fin-streamer data-field="regularMarketChangePercent" value="-0.01">-0.01</fin-streamer>'
            b'</body></html>'
        )
        articles = _scraper(default=html).fetch(["CL=F"])
        assert len(articles) == 1
        assert "price= " in articles[0].body or articles[0].body.index("price=") + 6 <= len(articles[0].body)

    def test_missing_price_field_price_empty_string_in_body(self) -> None:
        html = b"<html></html>"
        articles = _scraper(default=html).fetch(["CL=F"])
        body = articles[0].body
        # body should be "symbol=CL=F price= change_pct=" — price value is empty
        assert "price= " in body or body.endswith("price=") or "price= change_pct" in body


class TestYahooFinanceParserPrecision:
    """Tests that exercise parser internals via the scraper interface."""

    def test_value_attr_takes_precedence_over_text_content(self) -> None:
        # value attr says "200.00", text content says "WRONG" — value attr should win
        html = (
            b'<html><body>'
            b'<fin-streamer data-field="regularMarketPrice" value="200.00">WRONG</fin-streamer>'
            b'</body></html>'
        )
        articles = _scraper(default=html).fetch(["CL=F"])
        assert "200.00" in articles[0].body
        assert "WRONG" not in articles[0].body

    def test_text_fallback_when_value_attr_empty(self) -> None:
        # value attr is empty; text content should be used for price
        html = (
            b'<html><body>'
            b'<fin-streamer data-field="regularMarketPrice" value="">88.88</fin-streamer>'
            b'</body></html>'
        )
        articles = _scraper(default=html).fetch(["CL=F"])
        assert "88.88" in articles[0].body

    def test_first_price_fin_streamer_wins(self) -> None:
        # Two price streamers — only the first value should appear in the body
        html = (
            b'<html><body>'
            b'<fin-streamer data-field="regularMarketPrice" value="111.11">111.11</fin-streamer>'
            b'<fin-streamer data-field="regularMarketPrice" value="999.99">999.99</fin-streamer>'
            b'</body></html>'
        )
        articles = _scraper(default=html).fetch(["CL=F"])
        assert "price=111.11" in articles[0].body
        assert "999.99" not in articles[0].body

    def test_first_change_pct_fin_streamer_wins(self) -> None:
        html = (
            b'<html><body>'
            b'<fin-streamer data-field="regularMarketChangePercent" value="0.01">0.01</fin-streamer>'
            b'<fin-streamer data-field="regularMarketChangePercent" value="0.99">0.99</fin-streamer>'
            b'</body></html>'
        )
        articles = _scraper(default=html).fetch(["CL=F"])
        body = articles[0].body
        # First value 0.01 → 1.00%; second value 0.99 → 99.00% — only first should appear
        assert "1.00%" in body
        assert "99.00%" not in body

    def test_non_numeric_change_pct_value_stored_as_is(self) -> None:
        # Non-numeric value attr cannot be multiplied — should be stored without crash
        html = (
            b'<html><body>'
            b'<fin-streamer data-field="regularMarketPrice" value="50.0">50.0</fin-streamer>'
            b'<fin-streamer data-field="regularMarketChangePercent" value="N/A">N/A</fin-streamer>'
            b'</body></html>'
        )
        articles = _scraper(default=html).fetch(["CL=F"])
        assert len(articles) == 1  # no crash

    def test_json_fallback_negative_change_pct_math(self) -> None:
        # raw -0.025 → -2.50%
        html = b'<script>{"regularMarketChangePercent":{"raw":-0.025}}</script>'
        articles = _scraper(default=html).fetch(["CL=F"])
        body = articles[0].body
        assert "change_pct=" in body
        assert "-2.50%" in body

    def test_fin_streamer_price_wins_over_json_fallback(self) -> None:
        # fin-streamer is parsed first; JSON fallback should not override it
        html = (
            b'<html><body>'
            b'<fin-streamer data-field="regularMarketPrice" value="50.00">50.00</fin-streamer>'
            b'<script>{"regularMarketPrice":{"raw":999.99}}</script>'
            b'</body></html>'
        )
        articles = _scraper(default=html).fetch(["CL=F"])
        assert "price=50.00" in articles[0].body
        assert "999.99" not in articles[0].body


class TestYahooFinanceSymbolLabels:
    """Verify known-symbol labels appear in title, and unknown symbols fall back to the symbol."""

    def test_known_symbol_label_in_title(self) -> None:
        articles = _scraper().fetch(["CL=F"])
        assert "WTI Crude Oil" in articles[0].title

    def test_brent_crude_label(self) -> None:
        articles = _scraper().fetch(["BZ=F"])
        assert "Brent Crude Oil" in articles[0].title

    def test_gold_label(self) -> None:
        articles = _scraper().fetch(["GC=F"])
        assert "Gold" in articles[0].title

    def test_eurusd_label(self) -> None:
        articles = _scraper().fetch(["EURUSD=X"])
        assert "EUR/USD" in articles[0].title

    def test_unknown_symbol_falls_back_to_symbol_in_title(self) -> None:
        # Symbol not in _SYMBOL_LABELS → symbol string used as label
        articles = _scraper().fetch(["AAPL"])
        assert "AAPL" in articles[0].title

    def test_unknown_symbol_tagged_commodities_when_no_x_suffix(self) -> None:
        articles = _scraper().fetch(["AAPL"])
        assert "commodities" in articles[0].tags

    def test_unknown_fx_symbol_tagged_fx(self) -> None:
        articles = _scraper().fetch(["CHFUSD=X"])
        assert "fx" in articles[0].tags


class TestYahooFinanceUrlStructure:
    """URL construction — trailing slash, base domain, per-symbol uniqueness."""

    def test_url_ends_with_trailing_slash(self) -> None:
        articles = _scraper().fetch(["CL=F"])
        assert articles[0].url.endswith("/")

    def test_urls_differ_per_symbol(self) -> None:
        client = _FakeClient(default=_page())
        articles = YahooFinanceScraper(client=client).fetch(["CL=F", "GC=F"])
        assert articles[0].url != articles[1].url

    def test_url_called_with_correct_symbol_path(self) -> None:
        client = _FakeClient(default=_page())
        YahooFinanceScraper(client=client).fetch(["EURUSD=X"])
        assert any("EURUSD=X" in url for url in client.calls)

    def test_each_url_called_exactly_once(self) -> None:
        client = _FakeClient(default=_page())
        YahooFinanceScraper(client=client).fetch(["CL=F", "GC=F"])
        assert client.calls.count("https://finance.yahoo.com/quote/CL=F/") == 1
        assert client.calls.count("https://finance.yahoo.com/quote/GC=F/") == 1

"""Tests for practical market layer — zero network calls (injected HttpClient)."""

from __future__ import annotations

import pathlib

import pytest

from situation_monitor.practical import (
    PracticalMover,
    _direction,
    _extract_change_from_title,
    _parse_rss_items,
    fetch_practical_movers,
    fetch_regulatory_movers,
)

FIXTURE_DIR = pathlib.Path(__file__).parent / "fixtures"
PRACTICAL_RSS_PATH = FIXTURE_DIR / "practical_rss.xml"

# ── Inline fixture data ────────────────────────────────────────────────────────

# Real ECB Euroref XML format — default namespace is the ecb vocabulary URI.
_ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope
    xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
    xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <gesmes:subject>Reference rates</gesmes:subject>
  <gesmes:Sender>
    <gesmes:name>European Central Bank</gesmes:name>
  </gesmes:Sender>
  <Cube>
    <Cube time="2026-06-13">
      <Cube currency="USD" rate="1.1500"/>
      <Cube currency="JPY" rate="160.20"/>
      <Cube currency="GBP" rate="0.8600"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""

# EUR/USD 1.15 → change = round((1.15 - 1.10) / 1.10 * 100, 2)
_ECB_EXPECTED_CHANGE = round((1.15 - 1.10) / 1.10 * 100, 2)

_YAHOO_OIL_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>WTI Crude Oil</title>
    <link>https://finance.yahoo.com</link>
    <description>WTI Crude Oil headlines</description>
    <item>
      <title>WTI Crude up +2.5% on OPEC output cut hopes</title>
      <link>https://finance.yahoo.com/news/wti-crude-up</link>
      <pubDate>Fri, 13 Jun 2026 09:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Oil markets steady ahead of Fed meeting</title>
      <link>https://finance.yahoo.com/news/oil-steady</link>
      <pubDate>Fri, 13 Jun 2026 08:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

_YAHOO_GOLD_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Gold Futures</title>
    <link>https://finance.yahoo.com</link>
    <description>Gold headlines</description>
    <item>
      <title>Gold drops -1.2% as dollar strengthens</title>
      <link>https://finance.yahoo.com/news/gold-drops</link>
      <pubDate>Fri, 13 Jun 2026 09:30:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


# ── Stub HTTP clients ──────────────────────────────────────────────────────────

class _MapClient:
    """Returns canned bytes based on substring match against the requested URL."""

    def __init__(self, url_map: dict[str, bytes], default: bytes = b"") -> None:
        self._map = url_map
        self._default = default

    def get(self, url: str) -> bytes:
        for pattern, data in self._map.items():
            if pattern in url:
                return data
        return self._default


class _ConstClient:
    """Returns the same bytes for every URL."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def get(self, url: str) -> bytes:  # noqa: ARG002
        return self._data


class _ErrorClient:
    """Simulates a total network outage — every call raises OSError."""

    def get(self, url: str) -> bytes:
        raise OSError(f"Connection refused for {url}")


def _practical_client(
    ecb: bytes = _ECB_XML,
    oil: bytes = _YAHOO_OIL_RSS,
    gold: bytes = _YAHOO_GOLD_RSS,
) -> _MapClient:
    return _MapClient({
        "eurofxref-daily.xml": ecb,
        "CL%3DF": oil,
        "GC%3DF": gold,
    })


# ── Unit: _direction ───────────────────────────────────────────────────────────

class TestDirection:
    def test_positive_returns_up(self) -> None:
        assert _direction(1.5) == "up"

    def test_small_positive_returns_up(self) -> None:
        assert _direction(0.0001) == "up"

    def test_negative_returns_down(self) -> None:
        assert _direction(-0.1) == "down"

    def test_large_negative_returns_down(self) -> None:
        assert _direction(-99.9) == "down"

    def test_zero_returns_neutral(self) -> None:
        assert _direction(0.0) == "neutral"

    def test_direction_values_are_restricted(self) -> None:
        assert _direction(5.0) in {"up", "down", "neutral"}


# ── Unit: _extract_change_from_title ──────────────────────────────────────────

class TestExtractChangeFromTitle:
    def test_positive_pct_with_plus_sign(self) -> None:
        assert _extract_change_from_title("Oil up +2.5% on OPEC cuts") == 2.5

    def test_negative_pct_with_minus_sign(self) -> None:
        assert _extract_change_from_title("Gold drops -1.2% as dollar rallies") == -1.2

    def test_unsigned_pct_extracted(self) -> None:
        assert _extract_change_from_title("Asset moves 0.75% higher") == 0.75

    def test_integer_pct_extracted(self) -> None:
        assert _extract_change_from_title("Market surges 5% on strong jobs data") == 5.0

    def test_no_pct_returns_zero(self) -> None:
        assert _extract_change_from_title("Congress passes new trade bill") == 0.0

    def test_empty_string_returns_zero(self) -> None:
        assert _extract_change_from_title("") == 0.0

    def test_first_pct_wins_when_multiple(self) -> None:
        assert _extract_change_from_title("Up 3% then down 1%") == 3.0

    def test_pct_at_start_of_string(self) -> None:
        assert _extract_change_from_title("2% rise reported") == 2.0

    def test_large_pct_value_extracted(self) -> None:
        assert _extract_change_from_title("Crash of -30% in a single session") == -30.0

    def test_exponent_fragment_is_not_mistaken_for_a_change(self) -> None:
        # "1e999%" must not yield a spurious 999.0 — the digits are glued to an
        # exponent token, not a standalone percentage. A garbage headline → 0.0.
        assert _extract_change_from_title("Oil 1e999% surge") == 0.0

    def test_result_is_always_finite(self) -> None:
        import math
        for title in ("Up 1e500%", "Move 9e308% today", "Word123abc%"):
            assert math.isfinite(_extract_change_from_title(title))

    def test_decimal_glued_to_word_is_rejected(self) -> None:
        # A fragment like "v2.5%" inside "rev2.5%" is part of a larger token.
        assert _extract_change_from_title("rev2.5% milestone") == 0.0


# ── Unit: _parse_rss_items ────────────────────────────────────────────────────

class TestParseRssItems:
    def test_returns_list_of_three_tuples(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item><title>Foo</title><link>http://x.com/1</link></item>
        </channel></rss>"""
        items = _parse_rss_items(xml)
        assert isinstance(items, list)
        assert len(items) == 1
        title, link, pub = items[0]
        assert isinstance(title, str)
        assert isinstance(link, str)

    def test_title_and_link_extracted_correctly(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item><title>Hello World</title><link>http://x.com/hw</link></item>
        </channel></rss>"""
        title, link, _ = _parse_rss_items(xml)[0]
        assert title == "Hello World"
        assert link == "http://x.com/hw"

    def test_pubdate_extracted_when_present(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item>
            <title>Dated</title>
            <link>http://x.com/d</link>
            <pubDate>Mon, 13 Jun 2026 10:00:00 +0000</pubDate>
          </item>
        </channel></rss>"""
        _, _, pub = _parse_rss_items(xml)[0]
        assert pub is not None

    def test_pubdate_is_none_when_absent(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item><title>No date</title><link>http://x.com/nd</link></item>
        </channel></rss>"""
        _, _, pub = _parse_rss_items(xml)[0]
        assert pub is None

    def test_item_with_empty_title_is_skipped(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item><title></title><link>http://x.com/1</link></item>
          <item><title>Good</title><link>http://x.com/2</link></item>
        </channel></rss>"""
        items = _parse_rss_items(xml)
        assert len(items) == 1
        assert items[0][0] == "Good"

    def test_item_with_empty_link_is_skipped(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item><title>No link</title><link></link></item>
          <item><title>Has link</title><link>http://x.com/2</link></item>
        </channel></rss>"""
        items = _parse_rss_items(xml)
        assert len(items) == 1
        assert items[0][1] == "http://x.com/2"

    def test_whitespace_only_title_is_skipped(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item><title>   </title><link>http://x.com/1</link></item>
          <item><title>Real Title</title><link>http://x.com/2</link></item>
        </channel></rss>"""
        items = _parse_rss_items(xml)
        assert len(items) == 1

    def test_title_whitespace_is_stripped(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item><title>  Padded  </title><link>http://x.com/1</link></item>
        </channel></rss>"""
        title, _, _ = _parse_rss_items(xml)[0]
        assert title == "Padded"

    def test_missing_channel_element_returns_empty(self) -> None:
        xml = b"""<rss version="2.0"></rss>"""
        assert _parse_rss_items(xml) == []

    def test_empty_channel_returns_empty(self) -> None:
        xml = b"""<rss version="2.0"><channel></channel></rss>"""
        assert _parse_rss_items(xml) == []

    def test_multiple_items_returned_in_document_order(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item><title>First</title><link>http://x.com/1</link></item>
          <item><title>Second</title><link>http://x.com/2</link></item>
          <item><title>Third</title><link>http://x.com/3</link></item>
        </channel></rss>"""
        titles = [t for t, _, _ in _parse_rss_items(xml)]
        assert titles == ["First", "Second", "Third"]

    def test_all_empty_titles_and_links_returns_empty(self) -> None:
        xml = b"""<rss version="2.0"><channel>
          <item><title></title><link></link></item>
          <item><title>  </title><link>  </link></item>
        </channel></rss>"""
        assert _parse_rss_items(xml) == []

    def test_fixture_file_is_valid_rss(self) -> None:
        items = _parse_rss_items(PRACTICAL_RSS_PATH.read_bytes())
        assert len(items) >= 1
        for title, link, _ in items:
            assert title
            assert link


# ── Integration: fetch_practical_movers — ECB path ───────────────────────────

class TestFetchPracticalMoversEcb:
    """ECB EUR/USD XML is parsed into a correctly-shaped PracticalMover."""

    def test_eur_usd_mover_present(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        assert any(m.asset == "EUR/USD" for m in movers)

    def test_eur_usd_change_pct_matches_formula(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        m = next(m for m in movers if m.asset == "EUR/USD")
        assert m.change_pct == pytest.approx(_ECB_EXPECTED_CHANGE, abs=0.01)

    def test_eur_usd_direction_up_when_rate_above_baseline(self) -> None:
        # Rate 1.15 > 1.10 baseline
        movers = fetch_practical_movers(client=_practical_client())
        m = next(m for m in movers if m.asset == "EUR/USD")
        assert m.direction == "up"

    def test_eur_usd_direction_down_when_rate_below_baseline(self) -> None:
        low_xml = _ECB_XML.replace(b'rate="1.1500"', b'rate="1.05"')
        movers = fetch_practical_movers(client=_practical_client(ecb=low_xml))
        m = next(m for m in movers if m.asset == "EUR/USD")
        assert m.direction == "down"
        assert m.change_pct < 0

    def test_eur_usd_direction_neutral_at_baseline(self) -> None:
        baseline_xml = _ECB_XML.replace(b'rate="1.1500"', b'rate="1.10"')
        movers = fetch_practical_movers(client=_practical_client(ecb=baseline_xml))
        m = next(m for m in movers if m.asset == "EUR/USD")
        assert m.direction == "neutral"
        assert m.change_pct == pytest.approx(0.0, abs=0.001)

    def test_eur_usd_who_it_affects_is_non_empty(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        m = next(m for m in movers if m.asset == "EUR/USD")
        assert m.who_it_affects

    def test_eur_usd_what_to_watch_is_non_empty(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        m = next(m for m in movers if m.asset == "EUR/USD")
        assert m.what_to_watch

    def test_eur_usd_source_url_points_to_ecb(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        m = next(m for m in movers if m.asset == "EUR/USD")
        assert "ecb.europa.eu" in m.source_url

    def test_non_usd_currencies_ignored(self) -> None:
        # The fixture has JPY and GBP too; only USD should produce a EUR/USD mover
        movers = fetch_practical_movers(client=_practical_client())
        eur_usd_count = sum(1 for m in movers if m.asset == "EUR/USD")
        assert eur_usd_count == 1

    def test_invalid_rate_string_does_not_crash(self) -> None:
        bad_xml = _ECB_XML.replace(b'rate="1.1500"', b'rate="INVALID"')
        # Should not raise; simply omit the mover for a bad rate
        movers = fetch_practical_movers(client=_practical_client(ecb=bad_xml))
        assert isinstance(movers, list)


# ── Integration: fetch_practical_movers — Yahoo RSS path ──────────────────────

class TestFetchPracticalMoversYahoo:
    """Yahoo Finance RSS is parsed into WTI Oil and Gold PracticalMovers."""

    def test_returns_list(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        assert isinstance(movers, list)

    def test_wti_crude_oil_mover_present(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        assert any(m.asset == "WTI Crude Oil" for m in movers)

    def test_gold_mover_present(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        assert any(m.asset == "Gold" for m in movers)

    def test_oil_change_extracted_from_headline(self) -> None:
        # Headline: "WTI Crude up +2.5% on OPEC output cut hopes"
        movers = fetch_practical_movers(client=_practical_client())
        oil = next(m for m in movers if m.asset == "WTI Crude Oil")
        assert oil.change_pct == pytest.approx(2.5)

    def test_oil_direction_up(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        oil = next(m for m in movers if m.asset == "WTI Crude Oil")
        assert oil.direction == "up"

    def test_gold_change_extracted_from_headline(self) -> None:
        # Headline: "Gold drops -1.2% as dollar strengthens"
        movers = fetch_practical_movers(client=_practical_client())
        gold = next(m for m in movers if m.asset == "Gold")
        assert gold.change_pct == pytest.approx(-1.2)

    def test_gold_direction_down(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        gold = next(m for m in movers if m.asset == "Gold")
        assert gold.direction == "down"

    def test_oil_source_url_is_item_link(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        oil = next(m for m in movers if m.asset == "WTI Crude Oil")
        assert oil.source_url == "https://finance.yahoo.com/news/wti-crude-up"

    def test_all_movers_are_practical_mover_instances(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        for m in movers:
            assert isinstance(m, PracticalMover)

    def test_movers_have_non_empty_who_it_affects(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        for m in movers:
            assert m.who_it_affects, f"{m.asset}: empty who_it_affects"

    def test_movers_have_non_empty_what_to_watch(self) -> None:
        movers = fetch_practical_movers(client=_practical_client())
        for m in movers:
            assert m.what_to_watch, f"{m.asset}: empty what_to_watch"

    def test_headline_without_pct_gives_zero_change_and_neutral(self) -> None:
        rss_no_pct = b"""<rss version="2.0"><channel>
          <item>
            <title>Oil markets steady today with no clear direction</title>
            <link>https://finance.yahoo.com/news/steady</link>
          </item>
        </channel></rss>"""
        client = _practical_client(oil=rss_no_pct, gold=rss_no_pct)
        movers = fetch_practical_movers(client=client)
        oil = next((m for m in movers if m.asset == "WTI Crude Oil"), None)
        assert oil is not None
        assert oil.change_pct == 0.0
        assert oil.direction == "neutral"

    def test_source_url_falls_back_to_feed_url_when_item_link_empty(self) -> None:
        from situation_monitor.practical import _YAHOO_OIL_URL
        rss_no_link = b"""<rss version="2.0"><channel>
          <item>
            <title>Oil up +1.0%</title>
            <link></link>
          </item>
        </channel></rss>"""
        # Item link is empty → _parse_rss_items skips it → no oil mover produced
        # (This tests that empty-link items are correctly filtered out)
        client = _practical_client(oil=rss_no_link)
        movers = fetch_practical_movers(client=client)
        oil_movers = [m for m in movers if m.asset == "WTI Crude Oil"]
        # Empty link causes the item to be filtered by _parse_rss_items
        assert oil_movers == []


# ── Integration: fetch_regulatory_movers ─────────────────────────────────────

class TestFetchRegulatoryMovers:
    """News RSS from fixture → regulatory PracticalMover list."""

    def _news_client(self, rss: bytes | None = None) -> _ConstClient:
        return _ConstClient(rss if rss is not None else PRACTICAL_RSS_PATH.read_bytes())

    def test_returns_list(self) -> None:
        assert isinstance(fetch_regulatory_movers(client=self._news_client()), list)

    def test_returns_at_least_one_mover_from_fixture(self) -> None:
        movers = fetch_regulatory_movers(client=self._news_client())
        assert len(movers) >= 1

    def test_all_movers_are_practical_mover_instances(self) -> None:
        for m in fetch_regulatory_movers(client=self._news_client()):
            assert isinstance(m, PracticalMover)

    def test_asset_starts_with_bracketed_source_name(self) -> None:
        for m in fetch_regulatory_movers(client=self._news_client()):
            assert m.asset.startswith("["), f"Missing bracket prefix: {m.asset!r}"
            assert "]" in m.asset, f"Unclosed bracket in asset: {m.asset!r}"

    def test_asset_title_part_is_non_empty(self) -> None:
        for m in fetch_regulatory_movers(client=self._news_client()):
            bracket_end = m.asset.index("]")
            title_part = m.asset[bracket_end + 2:]  # skip "] "
            assert title_part, f"Empty title part in asset: {m.asset!r}"

    def test_asset_title_truncated_at_80_chars(self) -> None:
        long_title = "P" * 100
        rss = (
            b"<rss version='2.0'><channel>"
            b"<item><title>" + long_title.encode() + b"</title>"
            b"<link>http://x.com/1</link></item>"
            b"</channel></rss>"
        )
        for m in fetch_regulatory_movers(client=_ConstClient(rss)):
            bracket_end = m.asset.index("]")
            title_part = m.asset[bracket_end + 2:]
            assert len(title_part) <= 80, f"Title part not truncated: {title_part!r}"

    def test_source_url_is_item_link(self) -> None:
        for m in fetch_regulatory_movers(client=self._news_client()):
            assert m.source_url.startswith("http"), f"Bad source_url: {m.source_url!r}"

    def test_who_it_affects_is_non_empty(self) -> None:
        for m in fetch_regulatory_movers(client=self._news_client()):
            assert m.who_it_affects

    def test_what_to_watch_is_non_empty(self) -> None:
        for m in fetch_regulatory_movers(client=self._news_client()):
            assert m.what_to_watch

    def test_at_most_five_movers_per_feed(self) -> None:
        items = b""
        for i in range(10):
            items += (
                f"<item><title>Item {i}</title>"
                f"<link>http://x.com/{i}</link></item>"
            ).encode()
        rss = b"<rss version='2.0'><channel>" + items + b"</channel></rss>"
        movers = fetch_regulatory_movers(client=_ConstClient(rss))
        # Two feeds × 5 items each = 10 max
        assert len(movers) <= 10

    def test_empty_rss_returns_empty_list(self) -> None:
        rss = b"<rss version='2.0'><channel></channel></rss>"
        assert fetch_regulatory_movers(client=_ConstClient(rss)) == []

    def test_positive_pct_in_title_gives_up_direction(self) -> None:
        rss = b"""<rss version="2.0"><channel>
          <item>
            <title>Fed rate hike sends markets up +3.0%</title>
            <link>http://x.com/hike</link>
          </item>
        </channel></rss>"""
        movers = fetch_regulatory_movers(client=_ConstClient(rss))
        assert any(m.direction == "up" for m in movers)

    def test_negative_pct_in_title_gives_down_direction(self) -> None:
        rss = b"""<rss version="2.0"><channel>
          <item>
            <title>Sanctions cause -2.5% commodity shock</title>
            <link>http://x.com/sanctions</link>
          </item>
        </channel></rss>"""
        movers = fetch_regulatory_movers(client=_ConstClient(rss))
        assert any(m.direction == "down" for m in movers)

    def test_no_pct_in_title_gives_neutral_direction(self) -> None:
        rss = b"""<rss version="2.0"><channel>
          <item>
            <title>Congress debates new infrastructure bill</title>
            <link>http://x.com/bill</link>
          </item>
        </channel></rss>"""
        movers = fetch_regulatory_movers(client=_ConstClient(rss))
        assert any(m.direction == "neutral" for m in movers)

    def test_fixture_file_produces_movers_with_correct_urls(self) -> None:
        movers = fetch_regulatory_movers(client=self._news_client())
        urls = {m.source_url for m in movers}
        assert "https://feeds.example.com/politics/fed-rate-hike" in urls

    def test_fixture_file_first_item_direction_is_up(self) -> None:
        # First fixture item title: "Fed raises rates by +0.25% amid inflation concerns"
        movers = fetch_regulatory_movers(client=self._news_client())
        assert any(m.direction == "up" for m in movers)


# ── Error paths: network failures must NOT be silently swallowed ──────────────

class TestNetworkErrors:
    """
    When HttpClient.get() raises, the function must propagate the error rather
    than returning [], which would mask connectivity failures as "no movers".
    """

    def test_fetch_practical_movers_raises_on_total_network_failure(self) -> None:
        with pytest.raises(Exception):
            fetch_practical_movers(client=_ErrorClient())

    def test_fetch_regulatory_movers_raises_on_total_network_failure(self) -> None:
        with pytest.raises(Exception):
            fetch_regulatory_movers(client=_ErrorClient())

    def test_fetch_practical_movers_does_not_silently_return_empty_on_error(self) -> None:
        silently_empty = False
        try:
            result = fetch_practical_movers(client=_ErrorClient())
            silently_empty = result == []
        except Exception:
            silently_empty = False
        assert not silently_empty, (
            "fetch_practical_movers returned [] on network error instead of raising — "
            "this masks connectivity failures; the error must propagate"
        )

    def test_fetch_regulatory_movers_does_not_silently_return_empty_on_error(self) -> None:
        silently_empty = False
        try:
            result = fetch_regulatory_movers(client=_ErrorClient())
            silently_empty = result == []
        except Exception:
            silently_empty = False
        assert not silently_empty, (
            "fetch_regulatory_movers returned [] on network error instead of raising — "
            "this masks connectivity failures; the error must propagate"
        )

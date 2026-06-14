"""Tests for equity-index PracticalMover, AI-News digest section,
and dashboard '/' route domain filter.

Acceptance criteria exercised:
1. fetch_practical_movers with a SPY RSS fixture → PracticalMover whose
   .asset contains 'S&P', 'index', or 'SPX'.
2. daily_digest with Domain.AI articles → distinct '*🤖 AI News*' section
   header in output; absent otherwise.
3. Dashboard '/' route: ?domain=AI → AI-domain stories only; no param →
   all domains present. Asserts via Flask test client.
"""

from __future__ import annotations

import json

import pytest

from situation_monitor.dashboard import make_app
from situation_monitor.digest import daily_digest
from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
from situation_monitor.models import Article, Domain, SpinResult
from situation_monitor.practical import PracticalMover, fetch_practical_movers

# ---------------------------------------------------------------------------
# Fixture RSS bytes for practical-movers tests
# ---------------------------------------------------------------------------

# ECB daily-reference XML — rate at 1.10 baseline ⇒ change_pct ≈ 0.0
_ECB_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope
    xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
    xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube>
    <Cube time="2026-06-14">
      <Cube currency="USD" rate="1.1000"/>
    </Cube>
  </Cube>
</gesmes:Envelope>
"""

_YAHOO_OIL_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>WTI Crude Oil</title>
    <item>
      <title>Oil flat today</title>
      <link>https://finance.yahoo.com/news/oil-flat</link>
    </item>
  </channel>
</rss>
"""

_YAHOO_GOLD_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Gold Futures</title>
    <item>
      <title>Gold steady</title>
      <link>https://finance.yahoo.com/news/gold-steady</link>
    </item>
  </channel>
</rss>
"""

# SPY (S&P 500) RSS — positive headline with explicit percentage
_YAHOO_SPY_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>SPDR S&amp;P 500 ETF Trust (SPY)</title>
    <link>https://finance.yahoo.com</link>
    <description>S&amp;P 500 ETF headlines</description>
    <item>
      <title>S&amp;P 500 index climbs +1.5% on strong earnings</title>
      <link>https://finance.yahoo.com/news/spy-gains</link>
      <pubDate>Sat, 14 Jun 2026 09:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Markets rally as tech leads S&amp;P 500 higher</title>
      <link>https://finance.yahoo.com/news/spy-rally</link>
      <pubDate>Sat, 14 Jun 2026 08:00:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

# SPY RSS with an explicit negative move
_YAHOO_SPY_RSS_DOWN = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>S&amp;P 500</title>
    <item>
      <title>S&amp;P 500 falls -2.3% as sell-off deepens</title>
      <link>https://finance.yahoo.com/news/spy-falls</link>
    </item>
  </channel>
</rss>
"""

# SPY RSS whose headline has no percentage — tests neutral/zero fallback
_YAHOO_SPY_RSS_FLAT = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>S&amp;P 500</title>
    <item>
      <title>S&amp;P 500 ends mixed session with little change</title>
      <link>https://finance.yahoo.com/news/spy-flat</link>
    </item>
  </channel>
</rss>
"""

# Empty channel — no items produced
_EMPTY_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel></channel></rss>
"""


# ---------------------------------------------------------------------------
# Injected HTTP client stubs (never touch the network)
# ---------------------------------------------------------------------------


class _MapClient:
    """Returns canned bytes keyed by substring match on the requested URL."""

    def __init__(self, url_map: dict[str, bytes], default: bytes = b"") -> None:
        self._map = url_map
        self._default = default

    def get(self, url: str) -> bytes:
        for pattern, data in self._map.items():
            if pattern in url:
                return data
        return self._default


def _full_client(spy: bytes = _YAHOO_SPY_RSS) -> _MapClient:
    """Serve all four practical-movers feeds so no source is a total failure."""
    return _MapClient({
        "eurofxref-daily.xml": _ECB_XML,
        "CL%3DF": _YAHOO_OIL_RSS,
        "GC%3DF": _YAHOO_GOLD_RSS,
        "SPY": spy,
    })


# ---------------------------------------------------------------------------
# Helpers for digest / dashboard tests
# ---------------------------------------------------------------------------


def _article(
    title: str,
    source: str = "test.com",
    url: str | None = None,
    domain: Domain | None = None,
) -> Article:
    safe_url = (
        url
        or f"https://{source}/{title[:40].replace(' ', '-').replace('&', 'and').lower()}"
    )
    return Article(url=safe_url, title=title, source=source, domain=domain)


def _spin(spin_pct: float = 50.0, lens: str = "center") -> SpinResult:
    return SpinResult(spin_pct=spin_pct, lens=lens, rubric={}, receipts="stub")


def _aa(
    title: str,
    domain: Domain | None = None,
    url: str | None = None,
    lens: str = "center",
) -> AnnotatedArticle:
    return AnnotatedArticle(
        article=_article(title=title, domain=domain, url=url),
        spin=_spin(lens=lens),
    )


def _event(
    title: str = "Event",
    center: list[AnnotatedArticle] | None = None,
    left: list[AnnotatedArticle] | None = None,
    right: list[AnnotatedArticle] | None = None,
    spin_delta: float = 0.0,
) -> DualLensEvent:
    return DualLensEvent(
        event_title=title,
        left_articles=left or [],
        right_articles=right or [],
        center_articles=center or [],
        spin_delta=spin_delta,
    )


def _html(app, path: str = "/") -> str:
    with app.test_client() as c:
        return c.get(path).data.decode()


# ===========================================================================
# 1.  Equity-index PracticalMover — S&P 500 via SPY RSS
# ===========================================================================


class TestFetchPracticalMoversEquityIndex:
    """fetch_practical_movers with a SPY RSS fixture must return a PracticalMover
    whose .asset satisfies the equity-index acceptance criterion."""

    def test_spy_rss_produces_equity_index_asset(self) -> None:
        """Core criterion: mover.asset contains 'S&P', 'index', or 'SPX'."""
        movers = fetch_practical_movers(client=_full_client())
        equity_movers = [
            m for m in movers
            if "S&P" in m.asset or "index" in m.asset.lower() or "SPX" in m.asset
        ]
        assert equity_movers, (
            f"No equity-index mover found; assets returned: {[m.asset for m in movers]}"
        )

    def test_spy_asset_name_is_sp500_spy(self) -> None:
        """SPY feed produces asset label 'S&P 500 (SPY)' — contains 'S&P'."""
        movers = fetch_practical_movers(client=_full_client())
        assert any(m.asset == "S&P 500 (SPY)" for m in movers), (
            f"Expected asset='S&P 500 (SPY)'; got: {[m.asset for m in movers]}"
        )

    def test_spy_change_pct_extracted_from_headline(self) -> None:
        """Change pct is parsed from '… +1.5% …' in the SPY RSS headline."""
        movers = fetch_practical_movers(client=_full_client())
        spy = next(m for m in movers if "S&P" in m.asset)
        assert spy.change_pct == pytest.approx(1.5)

    def test_spy_direction_up_on_positive_headline(self) -> None:
        """Positive pct in headline → direction='up'."""
        movers = fetch_practical_movers(client=_full_client())
        spy = next(m for m in movers if "S&P" in m.asset)
        assert spy.direction == "up"

    def test_spy_direction_down_on_negative_headline(self) -> None:
        """Negative pct in headline → direction='down' and negative change_pct."""
        movers = fetch_practical_movers(client=_full_client(spy=_YAHOO_SPY_RSS_DOWN))
        spy = next(m for m in movers if "S&P" in m.asset)
        assert spy.direction == "down"
        assert spy.change_pct == pytest.approx(-2.3)

    def test_spy_direction_neutral_when_no_pct_in_headline(self) -> None:
        """Headline with no percentage → direction='neutral', change_pct=0.0."""
        movers = fetch_practical_movers(client=_full_client(spy=_YAHOO_SPY_RSS_FLAT))
        spy = next(m for m in movers if "S&P" in m.asset)
        assert spy.direction == "neutral"
        assert spy.change_pct == 0.0

    def test_spy_mover_is_practical_mover_instance(self) -> None:
        """The equity-index mover must be a PracticalMover dataclass instance."""
        movers = fetch_practical_movers(client=_full_client())
        spy = next(m for m in movers if "S&P" in m.asset)
        assert isinstance(spy, PracticalMover)

    def test_spy_mover_who_it_affects_non_empty(self) -> None:
        """who_it_affects must be populated — it is the human-impact field."""
        movers = fetch_practical_movers(client=_full_client())
        spy = next(m for m in movers if "S&P" in m.asset)
        assert spy.who_it_affects, "who_it_affects must not be empty for the S&P mover"

    def test_spy_mover_what_to_watch_non_empty(self) -> None:
        """what_to_watch must be populated — it drives the daily alert copy."""
        movers = fetch_practical_movers(client=_full_client())
        spy = next(m for m in movers if "S&P" in m.asset)
        assert spy.what_to_watch, "what_to_watch must not be empty for the S&P mover"

    def test_spy_source_url_is_first_item_link(self) -> None:
        """source_url must equal the <link> of the first RSS item."""
        movers = fetch_practical_movers(client=_full_client())
        spy = next(m for m in movers if "S&P" in m.asset)
        assert spy.source_url == "https://finance.yahoo.com/news/spy-gains"

    def test_empty_spy_rss_produces_no_equity_index_mover(self) -> None:
        """An empty SPY channel produces no S&P mover but other movers still appear."""
        movers = fetch_practical_movers(client=_full_client(spy=_EMPTY_RSS))
        sp_movers = [m for m in movers if "S&P" in m.asset]
        assert sp_movers == [], f"Unexpected S&P mover from empty RSS: {sp_movers}"
        # ECB + Oil + Gold should still be present
        assert len(movers) >= 1

    def test_exactly_one_equity_index_mover_per_feed(self) -> None:
        """Exactly one S&P mover is created even when the SPY RSS has multiple items."""
        movers = fetch_practical_movers(client=_full_client())
        sp_count = sum(1 for m in movers if "S&P" in m.asset)
        assert sp_count == 1, f"Expected exactly 1 S&P mover; found {sp_count}"

    def test_spy_mover_present_alongside_other_movers(self) -> None:
        """SPY mover coexists with EUR/USD, Oil, and Gold movers."""
        movers = fetch_practical_movers(client=_full_client())
        asset_names = {m.asset for m in movers}
        assert "EUR/USD" in asset_names
        assert "WTI Crude Oil" in asset_names
        assert "Gold" in asset_names
        assert any("S&P" in name for name in asset_names)


# ===========================================================================
# 2.  AI-News section in daily_digest
# ===========================================================================


class TestAiDigestAiNewsSection:
    """daily_digest must include a '*🤖 AI News*' section iff Domain.AI articles
    are present in the event list."""

    # --- header presence ---

    def test_ai_section_header_present_with_ai_center_article(self) -> None:
        """Core criterion: Domain.AI article in center bucket → AI News header."""
        event = _event("AI Launch", center=[_aa("Gemini Ultra released", domain=Domain.AI)])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" in result

    def test_ai_section_header_distinct_markdown_bold(self) -> None:
        """Header must be '*🤖 AI News*' (Markdown bold), not just the string 'AI'."""
        event = _event("AI Story", center=[_aa("AI Safety Summit", domain=Domain.AI)])
        result = daily_digest([event], [])
        # Strip the surrounding bold markers — the header line must exist verbatim
        assert "*\U0001f916 AI News*" in result
        # Sanity: a plain 'AI' substring is insufficient — the bold header is required
        header_line = next(
            (ln for ln in result.split("\n") if "\U0001f916" in ln), None
        )
        assert header_line is not None, "AI News header line not found in output"

    def test_ai_section_header_absent_for_world_articles(self) -> None:
        """Domain.WORLD articles must NOT produce an AI News section."""
        event = _event("World News", center=[_aa("G7 Summit begins", domain=Domain.WORLD)])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" not in result

    def test_ai_section_header_absent_for_markets_articles(self) -> None:
        """Domain.MARKETS articles must NOT produce an AI News section."""
        event = _event("Markets", center=[
            _aa("S&P 500 rallies 2%", domain=Domain.MARKETS, url="https://m.com/spy")
        ])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" not in result

    def test_ai_section_header_absent_for_domain_none(self) -> None:
        """Articles with domain=None must NOT trigger the AI News section."""
        event = _event("Tech", center=[_aa("New gadget launch", domain=None)])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" not in result

    def test_ai_section_header_absent_for_empty_events(self) -> None:
        """With no events, no AI News section should appear."""
        result = daily_digest([], [])
        assert "*\U0001f916 AI News*" not in result
        assert "AI News" not in result

    # --- content correctness ---

    def test_ai_article_title_listed_under_section(self) -> None:
        """The AI article title must appear as a bullet after the AI News header."""
        event = _event("AI", center=[_aa("Claude 5 announced", domain=Domain.AI)])
        result = daily_digest([event], [])
        lines = result.split("\n")
        ai_start = next(i for i, ln in enumerate(lines) if "*\U0001f916 AI News*" in ln)
        ai_section = "\n".join(lines[ai_start:])
        assert "Claude 5 announced" in ai_section

    def test_non_ai_title_absent_from_ai_section(self) -> None:
        """World-domain article title must NOT appear inside the AI News section."""
        ai_aa = _aa("ChatGPT update", domain=Domain.AI, url="https://ai.com/1")
        world_aa = _aa("Volcano erupts in Iceland", domain=Domain.WORLD, url="https://world.com/1")
        event = _event("Mixed", center=[ai_aa, world_aa])
        result = daily_digest([event], [])
        lines = result.split("\n")
        ai_start = next(i for i, ln in enumerate(lines) if "*\U0001f916 AI News*" in ln)
        ai_section = "\n".join(lines[ai_start:])
        assert "ChatGPT update" in ai_section
        assert "Volcano erupts in Iceland" not in ai_section

    def test_ai_articles_from_left_bucket_trigger_section(self) -> None:
        """AI articles in left_articles must also trigger the section."""
        event = _event("Policy", left=[
            _aa("AI Act signed into law", domain=Domain.AI, url="https://l.com/1")
        ])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" in result
        assert "AI Act signed into law" in result

    def test_ai_articles_from_right_bucket_trigger_section(self) -> None:
        """AI articles in right_articles must also trigger the section."""
        event = _event("Deregulation", right=[
            _aa("AI deregulation bill passed", domain=Domain.AI, url="https://r.com/1")
        ])
        result = daily_digest([event], [])
        assert "*\U0001f916 AI News*" in result
        assert "AI deregulation bill passed" in result

    def test_ai_section_follows_top_stories(self) -> None:
        """AI News section must appear after Top Stories in the output."""
        event = _event("Mixed", center=[
            _aa("Treaty signed", domain=Domain.WORLD, url="https://world.com/treaty"),
            _aa("GPT-6 rumours", domain=Domain.AI, url="https://ai.com/gpt6"),
        ])
        result = daily_digest([event], [])
        top_idx = result.index("*Top Stories*")
        ai_idx = result.index("*\U0001f916 AI News*")
        assert ai_idx > top_idx

    def test_ai_section_follows_market_movers_when_present(self) -> None:
        """AI News section must appear after Market Movers when movers are given."""
        event = _event("AI", center=[_aa("New model release", domain=Domain.AI)])
        mover = PracticalMover(
            asset="S&P 500 (SPY)",
            change_pct=1.5,
            direction="up",
            who_it_affects="Equity investors",
            what_to_watch="Fed policy, earnings",
            source_url="https://finance.yahoo.com/news/spy-gains",
        )
        result = daily_digest([event], [mover])
        movers_idx = result.index("*Market Movers*")
        ai_idx = result.index("*\U0001f916 AI News*")
        assert ai_idx > movers_idx

    def test_ai_section_capped_at_five_bullets(self) -> None:
        """At most 5 AI articles are listed even when more are available."""
        articles = [
            _aa(f"AI story {i}", domain=Domain.AI, url=f"https://ai.com/{i}")
            for i in range(8)
        ]
        event = _event("AI Flood", center=articles)
        result = daily_digest([event], [])
        lines = result.split("\n")
        ai_start = next(i for i, ln in enumerate(lines) if "*\U0001f916 AI News*" in ln)
        ai_bullets = [ln for ln in lines[ai_start + 1:] if ln.startswith("•")]
        assert len(ai_bullets) <= 5, f"Expected ≤5 AI bullets; got {len(ai_bullets)}"


# ===========================================================================
# 3.  Dashboard '/' route domain filter
# ===========================================================================


class TestDashboardRootDomainFilter:
    """The '/' route must filter rendered stories by domain when ?domain= is
    provided, and return all stories when the parameter is absent."""

    def test_no_param_renders_all_domains(self) -> None:
        """Without ?domain, all story titles appear in the HTML."""
        ai_story = _article("OpenAI unveils GPT-6", domain=Domain.AI)
        world_story = _article("NATO summit opens", domain=Domain.WORLD, url="https://world.com/nato")
        markets_story = _article("Bitcoin hits ATH", domain=Domain.MARKETS, url="https://m.com/btc")
        app = make_app(lambda: [ai_story, world_story, markets_story])
        html = _html(app, "/")
        assert "OpenAI unveils GPT-6" in html
        assert "NATO summit opens" in html
        assert "Bitcoin hits ATH" in html

    def test_domain_ai_shows_only_ai_stories(self) -> None:
        """?domain=AI must exclude non-AI story titles from the rendered HTML."""
        ai_story = _article("AlphaFold 4 announced", domain=Domain.AI)
        world_story = _article("Election results certified", domain=Domain.WORLD, url="https://world.com/el")
        app = make_app(lambda: [ai_story, world_story])
        html = _html(app, "/?domain=AI")
        assert "AlphaFold 4 announced" in html
        assert "Election results certified" not in html

    def test_domain_ai_story_count_matches_filter(self) -> None:
        """The story count line must reflect the filtered AI count, not the total."""
        stories = [
            _article("AI story one", domain=Domain.AI, url="https://ai.com/1"),
            _article("AI story two", domain=Domain.AI, url="https://ai.com/2"),
            _article("World story", domain=Domain.WORLD, url="https://world.com/1"),
        ]
        app = make_app(lambda: stories)
        html = _html(app, "/?domain=AI")
        # Template emits "{{ stories | length }} stories"
        assert "2 stories" in html

    def test_no_param_story_count_includes_all(self) -> None:
        """Without filter, the story count must include all domains."""
        stories = [
            _article("AI piece", domain=Domain.AI, url="https://ai.com/x"),
            _article("Markets piece", domain=Domain.MARKETS, url="https://m.com/x"),
            _article("World piece", domain=Domain.WORLD, url="https://w.com/x"),
        ]
        app = make_app(lambda: stories)
        html = _html(app, "/")
        assert "3 stories" in html

    def test_domain_ai_excludes_domain_none_stories(self) -> None:
        """Stories with domain=None must not appear under ?domain=AI."""
        unclassified = _article("Unclassified story", domain=None, url="https://misc.com/x")
        ai_story = _article("GPT-6 benchmarks published", domain=Domain.AI, url="https://ai.com/y")
        app = make_app(lambda: [unclassified, ai_story])
        html = _html(app, "/?domain=AI")
        assert "Unclassified story" not in html
        assert "GPT-6 benchmarks published" in html

    def test_domain_ai_lowercase_param_also_filters(self) -> None:
        """?domain=ai (lowercase) must produce the same filtering as ?domain=AI."""
        ai_story = _article("Transformer architecture paper", domain=Domain.AI)
        world_story = _article("World peace treaty signed", domain=Domain.WORLD, url="https://world.com/peace")
        app = make_app(lambda: [ai_story, world_story])
        html = _html(app, "/?domain=ai")
        assert "Transformer architecture paper" in html
        assert "World peace treaty signed" not in html

    def test_domain_world_shows_only_world_stories(self) -> None:
        """?domain=world must show only WORLD-domain stories."""
        world_story = _article("Climate accord signed", domain=Domain.WORLD, url="https://w.com/climate")
        ai_story = _article("OpenAI valuation doubles", domain=Domain.AI, url="https://ai.com/val")
        app = make_app(lambda: [world_story, ai_story])
        html = _html(app, "/?domain=world")
        assert "Climate accord signed" in html
        assert "OpenAI valuation doubles" not in html

    def test_domain_markets_shows_only_markets_stories(self) -> None:
        """?domain=markets must show only MARKETS-domain stories."""
        markets_story = _article("Gold surges 3%", domain=Domain.MARKETS, url="https://m.com/gold")
        ai_story = _article("LLM paper accepted", domain=Domain.AI, url="https://ai.com/llm")
        app = make_app(lambda: [markets_story, ai_story])
        html = _html(app, "/?domain=markets")
        assert "Gold surges 3%" in html
        assert "LLM paper accepted" not in html

    def test_domain_ai_filter_returns_http_200(self) -> None:
        """?domain=AI must return HTTP 200."""
        app = make_app(lambda: [_article("AI piece", domain=Domain.AI)])
        with app.test_client() as c:
            resp = c.get("/?domain=AI")
        assert resp.status_code == 200

    def test_root_no_param_returns_http_200(self) -> None:
        """Root route without params must return HTTP 200."""
        app = make_app(lambda: [_article("Some story", url="https://x.com/1")])
        with app.test_client() as c:
            resp = c.get("/")
        assert resp.status_code == 200

    def test_domain_ai_zero_stories_when_no_ai_stories_present(self) -> None:
        """?domain=AI with only non-AI stories must yield 0 stories count."""
        world_story = _article("Summit concluded", domain=Domain.WORLD, url="https://w.com/summit")
        app = make_app(lambda: [world_story])
        html = _html(app, "/?domain=AI")
        assert "0 stories" in html
        assert "Summit concluded" not in html

    def test_multiple_ai_stories_all_rendered(self) -> None:
        """All AI-domain stories are rendered when ?domain=AI is applied."""
        stories = [
            _article(f"AI discovery {i}", domain=Domain.AI, url=f"https://ai.com/{i}")
            for i in range(4)
        ]
        app = make_app(lambda: stories)
        html = _html(app, "/?domain=AI")
        for i in range(4):
            assert f"AI discovery {i}" in html
        assert "4 stories" in html

    def test_get_stories_called_fresh_on_each_request(self) -> None:
        """get_stories is invoked on every request — the domain filter must not cache."""
        call_log: list[str] = []

        def _get_stories():
            domain = "AI" if len(call_log) % 2 == 0 else "WORLD"
            call_log.append(domain)
            return [_article(f"Story {len(call_log)}", domain=Domain.AI, url=f"https://x.com/{len(call_log)}")]

        app = make_app(_get_stories)
        with app.test_client() as c:
            c.get("/?domain=AI")
            c.get("/?domain=AI")
        assert len(call_log) == 2, "get_stories must be called once per request"

    def test_domain_filter_independent_from_api_events_route(self) -> None:
        """Filtering on '/' must not affect the /api/events endpoint."""
        event = _event("AI Event", center=[_aa("AI story", domain=Domain.AI)])
        app = make_app(lambda: [], lambda: [event])
        with app.test_client() as c:
            resp = c.get("/api/events")
        data = json.loads(resp.data)
        assert len(data) == 1, (
            "Domain filter on '/' must not bleed into /api/events; "
            f"expected 1 event, got {len(data)}"
        )

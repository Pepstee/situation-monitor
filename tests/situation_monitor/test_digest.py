"""Adversarial tests for digest.py (daily_digest, breaking_ping) and scheduler coverage.

Focus:
- daily_digest() assembles both the dual-lens Top Stories section and the Market Movers section
- breaking_ping() is a silent no-op (no raise, no network call) when TELEGRAM_BOT_TOKEN is unset
- Threshold gate: articles below relevance threshold never trigger a network send
- Scheduler: run_scheduler wires up APScheduler correctly; _run_digest handles failures
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from situation_monitor.digest import breaking_ping, daily_digest
from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
from situation_monitor.models import Article, SpinResult
from situation_monitor.practical import PracticalMover


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _article(
    title: str = "Test Article",
    source: str = "test.com",
    relevance_score: float | None = None,
    url: str | None = None,
) -> Article:
    safe_url = url or f"https://{source}/{title[:30].replace(' ', '-').lower()}"
    a = Article(url=safe_url, title=title, source=source)
    a.relevance_score = relevance_score
    return a


def _spin(spin_pct: float = 50.0, lens: str = "center") -> SpinResult:
    return SpinResult(spin_pct=spin_pct, lens=lens, rubric={}, receipts="test-stub")


def _annotated(
    title: str = "Test Article",
    source: str = "test.com",
    spin_pct: float = 50.0,
    lens: str = "center",
    url: str | None = None,
) -> AnnotatedArticle:
    return AnnotatedArticle(
        article=_article(title=title, source=source, url=url),
        spin=_spin(spin_pct, lens),
    )


def _event(
    title: str = "Test Event",
    left: list[AnnotatedArticle] | None = None,
    right: list[AnnotatedArticle] | None = None,
    center: list[AnnotatedArticle] | None = None,
    spin_delta: float = 0.0,
) -> DualLensEvent:
    return DualLensEvent(
        event_title=title,
        left_articles=left or [],
        right_articles=right or [],
        center_articles=center or [],
        spin_delta=spin_delta,
    )


def _mover(
    asset: str = "EUR/USD",
    change_pct: float = 1.5,
    direction: str = "up",
) -> PracticalMover:
    return PracticalMover(
        asset=asset,
        change_pct=change_pct,
        direction=direction,
        who_it_affects="importers and exporters",
        what_to_watch="ECB rate decisions",
        source_url="https://www.ecb.europa.eu/stats",
    )


# ---------------------------------------------------------------------------
# daily_digest: dual-lens Top Stories section
# ---------------------------------------------------------------------------


class TestDailyDigestDualLensSection:
    """Top Stories block must reflect the dual-lens L/C/R structure."""

    def _fixture_events(self) -> list[DualLensEvent]:
        left_aa = _annotated(
            "Belfast ceasefire collapses under political pressure today",
            "cnn.com", 80.0, "left",
        )
        right_aa = _annotated(
            "Belfast ceasefire opposed by unionist leaders today",
            "foxnews.com", 30.0, "right",
        )
        return [
            _event(
                "Belfast ceasefire collapses under political pressure today",
                left=[left_aa],
                right=[right_aa],
                spin_delta=50.0,
            )
        ]

    def test_top_stories_header_present(self):
        result = daily_digest(self._fixture_events(), [])
        assert "*Top Stories*" in result

    def test_event_title_appears_in_output(self):
        result = daily_digest(self._fixture_events(), [])
        assert "Belfast ceasefire" in result

    def test_left_article_count_shown_in_bracket(self):
        result = daily_digest(self._fixture_events(), [])
        assert "L:1" in result

    def test_right_article_count_shown_in_bracket(self):
        result = daily_digest(self._fixture_events(), [])
        assert "R:1" in result

    def test_spin_delta_displayed_when_above_5_percent(self):
        result = daily_digest(self._fixture_events(), [])
        # spin_delta=50.0 → ↕50%
        assert "↕50%" in result

    def test_spin_delta_hidden_when_at_or_below_5_percent(self):
        aa = _annotated("Federal Reserve holds rates steady today", "reuters.com", 52.0, "center")
        event = _event("Federal Reserve holds rates steady today", center=[aa], spin_delta=5.0)
        result = daily_digest([event], [])
        assert "↕" not in result

    def test_spin_delta_hidden_when_exactly_zero(self):
        aa = _annotated("Neutral policy update announced today", "bbc.com", 50.0, "center")
        event = _event("Neutral policy update announced today", center=[aa], spin_delta=0.0)
        result = daily_digest([event], [])
        assert "↕" not in result

    def test_center_article_count_shown(self):
        center_aa = _annotated("Balanced Belfast coverage today here", "reuters.com", 50.0, "center")
        left_aa = _annotated("Belfast crisis left perspective today", "cnn.com", 80.0, "left")
        right_aa = _annotated("Belfast crisis right perspective today", "foxnews.com", 30.0, "right")
        event = _event(
            "Belfast crisis coverage perspective today here",
            left=[left_aa], right=[right_aa], center=[center_aa], spin_delta=50.0,
        )
        result = daily_digest([event], [])
        assert "C:1" in result
        assert "L:1" in result
        assert "R:1" in result

    def test_empty_events_shows_no_stories_placeholder(self):
        result = daily_digest([], [])
        assert "_No events found._" in result

    def test_empty_events_omits_top_stories_header(self):
        result = daily_digest([], [])
        assert "*Top Stories*" not in result

    def test_top_n_limits_number_of_events_shown(self):
        events = [
            _event(f"Distinct story number {i} happening right now")
            for i in range(12)
        ]
        result = daily_digest(events, [], top_n=10)
        assert "story number 9" in result       # 10th event (index 9) — shown
        assert "story number 10" not in result  # 11th event (index 10) — cut

    def test_top_n_zero_shows_no_events(self):
        result = daily_digest(self._fixture_events(), [], top_n=0)
        assert "_No events found._" in result

    def test_as_of_date_in_header(self):
        fixed = datetime(2026, 3, 15, 8, 0)
        result = daily_digest([], [], as_of=fixed)
        assert "2026-03-15 08:00" in result

    def test_header_always_present(self):
        result = daily_digest([], [])
        assert "*Situation Monitor*" in result

    def test_no_bracket_when_all_articles_missing(self):
        """An event with no articles in any bucket shows no [L:… R:… C:…] block."""
        event = _event("Empty event no articles anywhere")
        result = daily_digest([event], [])
        # Event title appears but no bracket notation
        assert "Empty event" in result
        assert "L:" not in result
        assert "R:" not in result
        assert "C:" not in result


# ---------------------------------------------------------------------------
# daily_digest: practical movers (Market Movers) section
# ---------------------------------------------------------------------------


class TestDailyDigestPracticalMoversSection:
    """Market Movers block must appear and accurately reflect PracticalMover data."""

    def test_market_movers_header_present_when_movers_nonempty(self):
        result = daily_digest([], [_mover("EUR/USD", 1.5, "up")])
        assert "*Market Movers*" in result

    def test_asset_name_appears_in_output(self):
        result = daily_digest([], [_mover("EUR/USD", 1.5, "up")])
        assert "EUR/USD" in result

    def test_up_arrow_for_positive_direction(self):
        result = daily_digest([], [_mover("EUR/USD", 2.0, "up")])
        assert "▲" in result

    def test_down_arrow_for_negative_direction(self):
        result = daily_digest([], [_mover("Gold", 1.2, "down")])
        assert "▼" in result

    def test_neutral_arrow_for_neutral_direction(self):
        result = daily_digest([], [_mover("EUR/USD", 0.0, "neutral")])
        assert "→" in result

    def test_change_pct_formatted_to_one_decimal_place(self):
        result = daily_digest([], [_mover("WTI Crude", 3.456, "up")])
        assert "3.5%" in result

    def test_change_pct_abs_value_displayed(self):
        """Even a negative change_pct should be shown as absolute value."""
        result = daily_digest([], [_mover("Gold", -2.75, "down")])
        assert "2.8%" in result

    def test_no_market_movers_header_when_movers_empty(self):
        result = daily_digest([], [])
        assert "*Market Movers*" not in result

    def test_only_top_5_movers_shown(self):
        movers = [_mover(f"ASSET{i}", float(i), "up") for i in range(9)]
        result = daily_digest([], movers)
        assert "ASSET4" in result   # 5th (index 4) — included
        assert "ASSET5" not in result  # 6th (index 5) — cut

    def test_both_sections_present_together(self):
        """Core acceptance criterion: daily_digest returns string containing
        both the dual-lens Top Stories section and the practical movers section."""
        left_aa = _annotated(
            "Market crisis triggered by banking sector collapse",
            "cnn.com", 80.0, "left",
            url="https://cnn.com/market-crisis",
        )
        right_aa = _annotated(
            "Banking sector collapse blamed on regulation failure",
            "foxnews.com", 30.0, "right",
            url="https://foxnews.com/banking-collapse",
        )
        events = [
            _event(
                "Market crisis triggered by banking sector collapse",
                left=[left_aa],
                right=[right_aa],
                spin_delta=50.0,
            )
        ]
        movers = [
            _mover("EUR/USD", 1.5, "up"),
            _mover("Gold", -0.8, "down"),
        ]
        result = daily_digest(events, movers)
        # Dual-lens section
        assert "*Top Stories*" in result
        assert "L:1" in result
        assert "R:1" in result
        # Practical movers section
        assert "*Market Movers*" in result
        assert "EUR/USD" in result
        assert "Gold" in result


# ---------------------------------------------------------------------------
# breaking_ping: no-token path (CI-safe no-op)
# ---------------------------------------------------------------------------


class TestBreakingPingNoToken:
    """With TELEGRAM_BOT_TOKEN absent and no bot_token param, breaking_ping must
    be a complete no-op: no exception, no network I/O."""

    def _high_sig_article(self) -> Article:
        return _article(
            "Breaking: major geopolitical crisis erupts across capitals",
            relevance_score=0.95,
        )

    def test_does_not_raise_without_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        breaking_ping([self._high_sig_article()])  # must not raise

    def test_does_not_call_urlopen_without_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        with patch("urllib.request.urlopen") as mock_open:
            breaking_ping([self._high_sig_article()])
            mock_open.assert_not_called()

    def test_returns_none_without_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        result = breaking_ping([self._high_sig_article()])
        assert result is None

    def test_silent_for_empty_article_list_without_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with patch("urllib.request.urlopen") as mock_open:
            breaking_ping([])
            mock_open.assert_not_called()

    def test_logs_debug_message_when_token_absent(self, monkeypatch, caplog):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        with caplog.at_level(logging.DEBUG, logger="situation_monitor.digest"):
            breaking_ping([self._high_sig_article()])
        assert any("TELEGRAM_BOT_TOKEN" in r.message for r in caplog.records)

    def test_does_not_raise_when_env_var_explicitly_empty_string(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        with patch("urllib.request.urlopen") as mock_open:
            breaking_ping([self._high_sig_article()])
            mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# breaking_ping: missing chat_id path
# ---------------------------------------------------------------------------


class TestBreakingPingNoChatId:
    """When a token IS present but chat_id is absent, must warn and not send."""

    def test_no_network_call_without_chat_id(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        art = _article("High significance article today", relevance_score=0.95)
        with patch("urllib.request.urlopen") as mock_open:
            breaking_ping([art], bot_token="faketoken")
            mock_open.assert_not_called()

    def test_logs_warning_when_chat_id_absent(self, monkeypatch, caplog):
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        art = _article("High significance article today", relevance_score=0.95)
        with caplog.at_level(logging.WARNING, logger="situation_monitor.digest"):
            breaking_ping([art], bot_token="faketoken")
        assert any("TELEGRAM_CHAT_ID" in r.message for r in caplog.records)

    def test_returns_none_when_chat_id_absent(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        art = _article("High significance article today", relevance_score=0.95)
        result = breaking_ping([art], bot_token="faketoken")
        assert result is None


# ---------------------------------------------------------------------------
# breaking_ping: threshold gate
# ---------------------------------------------------------------------------


class TestBreakingPingThresholdGate:
    """Articles below the relevance threshold must never trigger a network send."""

    def _mock_urlopen_context(self):
        """Return a context-manager mock for urllib.request.urlopen."""
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        return mock_resp

    def test_below_threshold_does_not_send(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article("Minor story below significance threshold today", relevance_score=0.60)
        with patch("urllib.request.urlopen") as mock_open:
            breaking_ping([art], threshold=0.85, bot_token="faketoken", chat_id="123")
            mock_open.assert_not_called()

    def test_exactly_at_threshold_sends(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article("Event exactly at threshold boundary now", relevance_score=0.85)
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen_context()) as mock_open:
            breaking_ping([art], threshold=0.85, bot_token="faketoken", chat_id="123")
            mock_open.assert_called_once()

    def test_above_threshold_sends(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article("Breaking high significance event now", relevance_score=0.92)
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen_context()) as mock_open:
            breaking_ping([art], threshold=0.85, bot_token="faketoken", chat_id="123")
            mock_open.assert_called_once()

    def test_custom_threshold_respected(self, monkeypatch):
        """score=0.70 is below default 0.85 but above a custom threshold of 0.60."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article("Medium significance story today here", relevance_score=0.70)
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen_context()) as mock_open:
            breaking_ping([art], threshold=0.60, bot_token="faketoken", chat_id="123")
            mock_open.assert_called_once()

    def test_threshold_read_from_env_var(self, monkeypatch):
        """BREAKING_THRESHOLD=0.50 in env → score 0.60 triggers a send."""
        monkeypatch.setenv("BREAKING_THRESHOLD", "0.50")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article("Story above custom env threshold today", relevance_score=0.60)
        with patch("urllib.request.urlopen", return_value=self._mock_urlopen_context()) as mock_open:
            breaking_ping([art], bot_token="faketoken", chat_id="123")
            mock_open.assert_called_once()

    def test_none_relevance_score_treated_as_zero(self, monkeypatch):
        """relevance_score=None must NOT satisfy threshold >= 0.85."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article("Story with missing relevance score", relevance_score=None)
        with patch("urllib.request.urlopen") as mock_open:
            breaking_ping([art], threshold=0.85, bot_token="faketoken", chat_id="123")
            mock_open.assert_not_called()

    def test_all_articles_below_threshold_no_send(self, monkeypatch):
        """When every article is below threshold the hot list is empty; nothing is sent."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        articles = [
            _article("Low relevance article one", relevance_score=0.40),
            _article("Low relevance article two", relevance_score=0.55),
            _article("Low relevance article three", relevance_score=0.70),
        ]
        with patch("urllib.request.urlopen") as mock_open:
            breaking_ping(articles, threshold=0.85, bot_token="faketoken", chat_id="123")
            mock_open.assert_not_called()

    def test_only_above_threshold_articles_in_send_payload(self, monkeypatch):
        """Mixed batch: only the high-significance title appears in the sent message."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        low = _article("Low significance story today", relevance_score=0.40)
        high = _article("High significance breaking news now", relevance_score=0.95)

        captured: dict = {}

        def _capture_req(req, **kwargs):
            captured["data"] = req.data
            return self._mock_urlopen_context()

        with patch("urllib.request.urlopen", side_effect=_capture_req):
            breaking_ping([low, high], threshold=0.85, bot_token="faketoken", chat_id="123")

        assert "data" in captured, "urlopen should have been called for the high-sig article"
        body = json.loads(captured["data"].decode())
        sent_text = body["text"]
        assert "High significance breaking" in sent_text
        assert "Low significance" not in sent_text

    def test_send_payload_limited_to_five_articles(self, monkeypatch):
        """Even when many articles are above threshold, only the first 5 are sent."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        articles = [
            _article(f"Breaking story number {i} today here", relevance_score=0.90)
            for i in range(8)
        ]

        captured: dict = {}

        def _capture_req(req, **kwargs):
            captured["data"] = req.data
            return self._mock_urlopen_context()

        with patch("urllib.request.urlopen", side_effect=_capture_req):
            breaking_ping(articles, threshold=0.85, bot_token="faketoken", chat_id="123")

        body = json.loads(captured["data"].decode())
        sent_text = body["text"]
        assert "story number 5" not in sent_text  # 6th article (index 5) — cut
        assert "story number 4" in sent_text      # 5th article (index 4) — included

    def test_send_uses_markdown_parse_mode(self, monkeypatch):
        """Telegram payload must use Markdown parse mode."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article("Significant breaking article today now", relevance_score=0.90)
        captured: dict = {}

        def _capture_req(req, **kwargs):
            captured["data"] = req.data
            return self._mock_urlopen_context()

        with patch("urllib.request.urlopen", side_effect=_capture_req):
            breaking_ping([art], threshold=0.85, bot_token="faketoken", chat_id="123")

        body = json.loads(captured["data"].decode())
        assert body.get("parse_mode") == "Markdown"

    def test_send_passes_correct_chat_id(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article("Significant breaking article today", relevance_score=0.90)
        captured: dict = {}

        def _capture_req(req, **kwargs):
            captured["data"] = req.data
            return self._mock_urlopen_context()

        with patch("urllib.request.urlopen", side_effect=_capture_req):
            breaking_ping([art], threshold=0.85, bot_token="faketoken", chat_id="chat-9999")

        body = json.loads(captured["data"].decode())
        assert body["chat_id"] == "chat-9999"

    def test_special_chars_in_title_are_escaped(self, monkeypatch):
        """Square brackets in article titles must be escaped to avoid Markdown breakage."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article(
            "[Update] Major [breaking] story unfolding now globally",
            relevance_score=0.92,
        )
        captured: dict = {}

        def _capture_req(req, **kwargs):
            captured["data"] = req.data
            return self._mock_urlopen_context()

        with patch("urllib.request.urlopen", side_effect=_capture_req):
            breaking_ping([art], threshold=0.85, bot_token="faketoken", chat_id="123")

        body = json.loads(captured["data"].decode())
        # Raw unescaped [ or ] inside the link text would break Markdown
        assert r"\[Update\]" in body["text"] or "\\[" in body["text"]

    def test_send_failure_does_not_raise(self, monkeypatch):
        """_send_telegram must swallow network errors, never propagate them."""
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        art = _article("High sig article network will fail", relevance_score=0.92)
        with patch("urllib.request.urlopen", side_effect=OSError("connection refused")):
            # Must not raise
            breaking_ping([art], threshold=0.85, bot_token="faketoken", chat_id="123")

    def test_empty_article_list_no_send_even_with_token(self, monkeypatch):
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        with patch("urllib.request.urlopen") as mock_open:
            breaking_ping([], threshold=0.85, bot_token="faketoken", chat_id="123")
            mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# Scheduler: run_scheduler wires up APScheduler
# ---------------------------------------------------------------------------


class TestRunScheduler:
    """Smoke tests for run_scheduler(): correct job config, correct default hour."""

    def test_adds_daily_digest_job(self):
        from situation_monitor.scheduler import run_scheduler

        mock_sched = MagicMock()
        mock_sched.start.side_effect = KeyboardInterrupt

        with patch("apscheduler.schedulers.blocking.BlockingScheduler", return_value=mock_sched):
            with patch("apscheduler.triggers.cron.CronTrigger"):
                try:
                    run_scheduler(digest_hour=7)
                except KeyboardInterrupt:
                    pass

        mock_sched.add_job.assert_called_once()
        kwargs = mock_sched.add_job.call_args[1]
        assert kwargs.get("name") == "daily_digest"

    def test_default_hour_is_seven(self):
        from situation_monitor.scheduler import run_scheduler

        mock_sched = MagicMock()
        mock_sched.start.side_effect = KeyboardInterrupt

        with patch("apscheduler.schedulers.blocking.BlockingScheduler", return_value=mock_sched):
            with patch("apscheduler.triggers.cron.CronTrigger") as mock_trigger:
                try:
                    run_scheduler()
                except KeyboardInterrupt:
                    pass

                mock_trigger.assert_called_once_with(hour=7, timezone="Europe/London")

    def test_custom_hour_passed_to_trigger(self):
        from situation_monitor.scheduler import run_scheduler

        mock_sched = MagicMock()
        mock_sched.start.side_effect = KeyboardInterrupt

        with patch("apscheduler.schedulers.blocking.BlockingScheduler", return_value=mock_sched):
            with patch("apscheduler.triggers.cron.CronTrigger") as mock_trigger:
                try:
                    run_scheduler(digest_hour=9)
                except KeyboardInterrupt:
                    pass

                mock_trigger.assert_called_once_with(hour=9, timezone="Europe/London")

    def test_misfire_grace_time_set(self):
        from situation_monitor.scheduler import run_scheduler

        mock_sched = MagicMock()
        mock_sched.start.side_effect = KeyboardInterrupt

        with patch("apscheduler.schedulers.blocking.BlockingScheduler", return_value=mock_sched):
            with patch("apscheduler.triggers.cron.CronTrigger"):
                try:
                    run_scheduler()
                except KeyboardInterrupt:
                    pass

        kwargs = mock_sched.add_job.call_args[1]
        assert kwargs.get("misfire_grace_time") == 300


# ---------------------------------------------------------------------------
# Scheduler: _run_digest error handling
# ---------------------------------------------------------------------------


class TestRunDigestErrorHandling:
    """_run_digest must handle ingestion failures without raising."""

    def test_ingestion_failure_logs_and_returns(self):
        from situation_monitor.scheduler import _run_digest

        with patch("situation_monitor.scheduler._build_config", return_value=MagicMock()):
            with patch("situation_monitor.__main__._ingest_and_enrich",
                       side_effect=RuntimeError("network timeout")):
                # Must not propagate the RuntimeError
                _run_digest()

    def test_practical_movers_failure_falls_back_to_empty(self, monkeypatch):
        """If fetch_practical_movers raises, movers falls back to [] and digest still runs."""
        from situation_monitor.scheduler import _run_digest

        dummy_articles = [_article("Test article about Belfast today", relevance_score=0.5)]
        dummy_events = [
            _event("Test article about Belfast today", spin_delta=0.0)
        ]

        with patch("situation_monitor.scheduler._build_config", return_value=MagicMock()):
            with patch("situation_monitor.__main__._ingest_and_enrich",
                       return_value=dummy_articles):
                with patch("situation_monitor.dual_lens.group_by_event",
                           return_value=dummy_events):
                    with patch("situation_monitor.practical.fetch_practical_movers",
                               side_effect=ConnectionError("feed down")):
                        with patch("situation_monitor.digest.daily_digest",
                                   return_value="digest text") as mock_digest:
                            with patch("situation_monitor.digest.breaking_ping"):
                                _run_digest()

                        # daily_digest must have been called with empty movers
                        call_args = mock_digest.call_args
                        movers_arg = call_args[0][1]
                        assert movers_arg == []

"""Tests for send_daily_digest and SM_TELEGRAM_* env-var wiring.

Acceptance criteria exercised here:
  1. send_daily_digest(token=None, …) does not call _send_telegram and returns None
  2. send_daily_digest(token=TOKEN, chat_id=CHAT_ID, …) calls _send_telegram exactly
     once with the assembled digest text
  3. SM_TELEGRAM_TOKEN / SM_TELEGRAM_CHAT_ID env vars are reflected in Config after
     _apply_env is called
  4. All tests pass alongside the existing digest suite
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, call, patch

import pytest

from situation_monitor.config import Config
from situation_monitor.digest import send_daily_digest, daily_digest
from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent
from situation_monitor.models import Article, SpinResult
from situation_monitor.practical import PracticalMover


# ---------------------------------------------------------------------------
# Fixture helpers (local copies — independent of other test files)
# ---------------------------------------------------------------------------


def _article(title: str = "Test Article", source: str = "test.com") -> Article:
    return Article(url=f"https://{source}/{title[:20].replace(' ', '-').lower()}", title=title, source=source)


def _spin(spin_pct: float = 50.0, lens: str = "center") -> SpinResult:
    return SpinResult(spin_pct=spin_pct, lens=lens, rubric={}, receipts="stub")


def _annotated(title: str = "Test Article", source: str = "test.com") -> AnnotatedArticle:
    return AnnotatedArticle(article=_article(title, source), spin=_spin())


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


def _mover(asset: str = "EUR/USD", change_pct: float = 1.5, direction: str = "up") -> PracticalMover:
    return PracticalMover(
        asset=asset,
        change_pct=change_pct,
        direction=direction,
        who_it_affects="traders",
        what_to_watch="rate decisions",
        source_url="https://example.com",
    )


# ---------------------------------------------------------------------------
# send_daily_digest: token=None path
# ---------------------------------------------------------------------------


class TestSendDailyDigestNoToken:
    """When token is absent (None or falsy) the function must be a complete no-op."""

    def test_returns_none_when_token_is_none(self):
        result = send_daily_digest([], [], token=None, chat_id="12345")
        assert result is None

    def test_does_not_call_send_telegram_when_token_is_none(self):
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token=None, chat_id="12345")
            mock_send.assert_not_called()

    def test_returns_none_when_token_is_empty_string(self):
        result = send_daily_digest([], [], token="", chat_id="12345")
        assert result is None

    def test_does_not_call_send_telegram_when_token_is_empty_string(self):
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token="", chat_id="12345")
            mock_send.assert_not_called()

    def test_does_not_raise_when_token_is_none(self):
        # Must not raise even with non-trivial event/mover lists
        events = [_event("Major political development today", left=[_annotated()])]
        movers = [_mover()]
        send_daily_digest(events, movers, token=None, chat_id="12345")

    def test_logs_info_when_token_absent(self, caplog):
        with caplog.at_level(logging.INFO, logger="situation_monitor.digest"):
            send_daily_digest([], [], token=None, chat_id="12345")
        assert any("SM_TELEGRAM_TOKEN" in r.message for r in caplog.records)

    def test_does_not_call_send_telegram_when_only_chat_id_is_none(self):
        """token present but chat_id absent — _send_telegram must NOT be called."""
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token="real-token", chat_id=None)
            mock_send.assert_not_called()

    def test_returns_none_when_only_chat_id_is_none(self):
        result = send_daily_digest([], [], token="real-token", chat_id=None)
        assert result is None

    def test_does_not_call_send_telegram_when_chat_id_is_empty_string(self):
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token="real-token", chat_id="")
            mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# send_daily_digest: token + chat_id path
# ---------------------------------------------------------------------------


class TestSendDailyDigestWithCredentials:
    """When both token and chat_id are provided, _send_telegram must be called
    exactly once with the text produced by daily_digest(events, movers)."""

    TOKEN = "bot123:ABC-DEF"
    CHAT_ID = "-1001234567890"

    def test_calls_send_telegram_exactly_once(self):
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token=self.TOKEN, chat_id=self.CHAT_ID)
            assert mock_send.call_count == 1

    def test_send_telegram_receives_correct_token(self):
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token=self.TOKEN, chat_id=self.CHAT_ID)
            actual_token = mock_send.call_args[0][0]
            assert actual_token == self.TOKEN

    def test_send_telegram_receives_correct_chat_id(self):
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token=self.TOKEN, chat_id=self.CHAT_ID)
            actual_chat_id = mock_send.call_args[0][1]
            assert actual_chat_id == self.CHAT_ID

    def test_send_telegram_receives_assembled_digest_text(self):
        """The text passed to _send_telegram must equal daily_digest(events, movers)."""
        events = [
            _event(
                "Interest rates cut by central bank today",
                left=[_annotated("Rate cut left take", "cnn.com")],
                right=[_annotated("Rate cut right take", "foxnews.com")],
                spin_delta=30.0,
            )
        ]
        movers = [_mover("Gold", 2.1, "up")]

        expected_text = daily_digest(events, movers)

        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest(events, movers, token=self.TOKEN, chat_id=self.CHAT_ID)
            actual_text = mock_send.call_args[0][2]
            assert actual_text == expected_text

    def test_send_telegram_receives_header_in_text(self):
        """Sanity-check: the assembled text contains the digest header marker."""
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token=self.TOKEN, chat_id=self.CHAT_ID)
            actual_text = mock_send.call_args[0][2]
            assert "*Situation Monitor*" in actual_text

    def test_send_telegram_receives_top_stories_when_events_present(self):
        events = [_event("Trade deal collapses in last minute negotiations today")]
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest(events, [], token=self.TOKEN, chat_id=self.CHAT_ID)
            actual_text = mock_send.call_args[0][2]
            assert "*Top Stories*" in actual_text
            assert "Trade deal" in actual_text

    def test_send_telegram_receives_market_movers_when_movers_present(self):
        movers = [_mover("BTC/USD", 5.5, "up")]
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], movers, token=self.TOKEN, chat_id=self.CHAT_ID)
            actual_text = mock_send.call_args[0][2]
            assert "*Market Movers*" in actual_text
            assert "BTC/USD" in actual_text

    def test_send_telegram_called_with_positional_args_in_order(self):
        """Confirm positional argument order: token, chat_id, text."""
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token=self.TOKEN, chat_id=self.CHAT_ID)
            args = mock_send.call_args[0]
            assert len(args) == 3
            token_arg, chat_id_arg, text_arg = args
            assert token_arg == self.TOKEN
            assert chat_id_arg == self.CHAT_ID
            assert isinstance(text_arg, str)

    def test_send_telegram_not_called_again_after_first_invocation(self):
        """Single call — no retry logic, no duplicate sends."""
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token=self.TOKEN, chat_id=self.CHAT_ID)
            send_daily_digest([], [], token=self.TOKEN, chat_id=self.CHAT_ID)
            assert mock_send.call_count == 2  # each call → exactly one send

    def test_text_matches_daily_digest_with_empty_inputs(self):
        """Even with no events or movers the text is the full (header-only) digest."""
        expected_text = daily_digest([], [])
        with patch("situation_monitor.digest._send_telegram") as mock_send:
            send_daily_digest([], [], token=self.TOKEN, chat_id=self.CHAT_ID)
            actual_text = mock_send.call_args[0][2]
            # Can't compare timestamps exactly, so verify structural markers
            assert "*Situation Monitor*" in actual_text
            assert "_No events found._" in actual_text
            # Both digests have the same structure
            assert actual_text.count("*Situation Monitor*") == expected_text.count("*Situation Monitor*")


# ---------------------------------------------------------------------------
# _apply_env: SM_TELEGRAM_TOKEN and SM_TELEGRAM_CHAT_ID env var wiring
# ---------------------------------------------------------------------------


class TestApplyEnvTelegramVars:
    """SM_TELEGRAM_TOKEN and SM_TELEGRAM_CHAT_ID must be written into the Config
    object by _apply_env when present in the environment."""

    def _apply_env(self, config: Config) -> None:
        from situation_monitor.__main__ import _apply_env
        _apply_env(config)

    def test_telegram_token_written_from_env(self, monkeypatch):
        monkeypatch.setenv("SM_TELEGRAM_TOKEN", "mytoken123")
        monkeypatch.delenv("SM_TELEGRAM_CHAT_ID", raising=False)
        config = Config.from_defaults()
        self._apply_env(config)
        assert config.telegram_token == "mytoken123"

    def test_telegram_chat_id_written_from_env(self, monkeypatch):
        monkeypatch.delenv("SM_TELEGRAM_TOKEN", raising=False)
        monkeypatch.setenv("SM_TELEGRAM_CHAT_ID", "-1009876543210")
        config = Config.from_defaults()
        self._apply_env(config)
        assert config.telegram_chat_id == "-1009876543210"

    def test_both_vars_written_together(self, monkeypatch):
        monkeypatch.setenv("SM_TELEGRAM_TOKEN", "tok-aaa")
        monkeypatch.setenv("SM_TELEGRAM_CHAT_ID", "chat-bbb")
        config = Config.from_defaults()
        self._apply_env(config)
        assert config.telegram_token == "tok-aaa"
        assert config.telegram_chat_id == "chat-bbb"

    def test_telegram_token_absent_leaves_none(self, monkeypatch):
        monkeypatch.delenv("SM_TELEGRAM_TOKEN", raising=False)
        config = Config.from_defaults()
        self._apply_env(config)
        assert config.telegram_token is None

    def test_telegram_chat_id_absent_leaves_none(self, monkeypatch):
        monkeypatch.delenv("SM_TELEGRAM_CHAT_ID", raising=False)
        config = Config.from_defaults()
        self._apply_env(config)
        assert config.telegram_chat_id is None

    def test_telegram_token_overwrites_existing_value(self, monkeypatch):
        """_apply_env must overwrite a pre-set telegram_token in the config object."""
        monkeypatch.setenv("SM_TELEGRAM_TOKEN", "new-token")
        config = Config.from_defaults()
        config.telegram_token = "old-token"
        self._apply_env(config)
        assert config.telegram_token == "new-token"

    def test_telegram_chat_id_overwrites_existing_value(self, monkeypatch):
        monkeypatch.setenv("SM_TELEGRAM_CHAT_ID", "new-chat")
        config = Config.from_defaults()
        config.telegram_chat_id = "old-chat"
        self._apply_env(config)
        assert config.telegram_chat_id == "new-chat"

    def test_empty_string_env_var_not_applied(self, monkeypatch):
        """An empty-string env var (falsy walrus guard) must leave the field untouched."""
        monkeypatch.setenv("SM_TELEGRAM_TOKEN", "")
        config = Config.from_defaults()
        config.telegram_token = "pre-set"
        self._apply_env(config)
        # Empty string is falsy in `if v := …`, so pre-set value should remain
        assert config.telegram_token == "pre-set"

    def test_empty_string_chat_id_not_applied(self, monkeypatch):
        monkeypatch.setenv("SM_TELEGRAM_CHAT_ID", "")
        config = Config.from_defaults()
        config.telegram_chat_id = "pre-set"
        self._apply_env(config)
        assert config.telegram_chat_id == "pre-set"

    def test_other_env_fields_unaffected_by_telegram_vars(self, monkeypatch):
        """Setting SM_TELEGRAM_* must not perturb unrelated Config fields."""
        # Isolate all SM_* vars that _apply_env reads so the test is hermetic
        for var in ("SM_LLM_BACKEND", "SM_DASHBOARD_PORT", "SM_OLLAMA_MODEL",
                    "SM_OLLAMA_URL", "SM_MAX_ARTICLES", "SM_FETCH_INTERVAL",
                    "SM_LOG_LEVEL", "SM_POLL_INTERVAL", "SM_SOURCES",
                    "SM_POLYMARKET_MARKETS", "SM_POLYMARKET_SLUGS"):
            monkeypatch.delenv(var, raising=False)
        monkeypatch.setenv("SM_TELEGRAM_TOKEN", "tok")
        monkeypatch.setenv("SM_TELEGRAM_CHAT_ID", "chat")
        config = Config.from_defaults()
        original_backend = config.llm_backend
        original_port = config.dashboard_port
        self._apply_env(config)
        assert config.llm_backend == original_backend
        assert config.dashboard_port == original_port


# ---------------------------------------------------------------------------
# Config.from_env: SM_TELEGRAM_* reflected in freshly constructed Config
# ---------------------------------------------------------------------------


class TestConfigFromEnvTelegramVars:
    """Config.from_env() is an alternative path — it must also pick up the vars."""

    def test_from_env_picks_up_telegram_token(self, monkeypatch):
        monkeypatch.setenv("SM_TELEGRAM_TOKEN", "env-token-xyz")
        monkeypatch.delenv("SM_TELEGRAM_CHAT_ID", raising=False)
        config = Config.from_env()
        assert config.telegram_token == "env-token-xyz"

    def test_from_env_picks_up_telegram_chat_id(self, monkeypatch):
        monkeypatch.delenv("SM_TELEGRAM_TOKEN", raising=False)
        monkeypatch.setenv("SM_TELEGRAM_CHAT_ID", "-999888777")
        config = Config.from_env()
        assert config.telegram_chat_id == "-999888777"

    def test_from_env_both_absent_yields_none_fields(self, monkeypatch):
        monkeypatch.delenv("SM_TELEGRAM_TOKEN", raising=False)
        monkeypatch.delenv("SM_TELEGRAM_CHAT_ID", raising=False)
        config = Config.from_env()
        assert config.telegram_token is None
        assert config.telegram_chat_id is None

    def test_from_env_token_and_chat_id_together(self, monkeypatch):
        monkeypatch.setenv("SM_TELEGRAM_TOKEN", "full-tok")
        monkeypatch.setenv("SM_TELEGRAM_CHAT_ID", "full-chat")
        config = Config.from_env()
        assert config.telegram_token == "full-tok"
        assert config.telegram_chat_id == "full-chat"

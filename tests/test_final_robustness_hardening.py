"""Adversarial robustness tests for four specific edge cases.

1. sanitise_article: None body / None title must not raise.
2. _apply_env: bad int/float env vars (e.g. "notanumber", "3.14") are silently ignored;
   the corresponding config field keeps its default value.
3. breaking_ping: non-numeric BREAKING_THRESHOLD env var is silently discarded and
   the default threshold (0.85) is used instead.
4. estimate_spin: when llm_client raises any exception, a valid SpinResult fallback
   is returned rather than propagating the exception.
"""

from __future__ import annotations

import pytest

from situation_monitor.bias import SpinEstimator
from situation_monitor.config import Config
from situation_monitor.digest import breaking_ping
from situation_monitor.models import Article, Domain, SpinResult
from situation_monitor.sanitiser import sanitise_article


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _article(title: str = "Placeholder title", body: str = "") -> Article:
    return Article(
        url="https://example.com/test",
        title=title,
        source="example.com",
        body=body,
    )


# ---------------------------------------------------------------------------
# 1. sanitise_article: None body / None title must not raise
# ---------------------------------------------------------------------------


class TestSanitiserNoneFields:
    """sanitise_article must never raise when title or body is None.

    Article.__post_init__ prevents constructing one with None title or source,
    but any code can mutate those fields after construction.  The sanitiser uses
    `field or ""` as a guard and must remain resilient.
    """

    def test_none_body_does_not_raise(self) -> None:
        art = _article()
        art.body = None  # type: ignore[assignment]  -- post-init mutation
        sanitise_article(art)  # must not raise

    def test_none_body_becomes_empty_string(self) -> None:
        art = _article()
        art.body = None  # type: ignore[assignment]
        sanitise_article(art)
        assert art.body == ""

    def test_none_title_does_not_raise(self) -> None:
        art = _article()
        art.title = None  # type: ignore[assignment]  -- post-init mutation
        sanitise_article(art)  # must not raise

    def test_none_title_becomes_empty_string(self) -> None:
        art = _article()
        art.title = None  # type: ignore[assignment]
        sanitise_article(art)
        assert art.title == ""

    def test_both_none_does_not_raise(self) -> None:
        art = _article()
        art.title = None  # type: ignore[assignment]
        art.body = None  # type: ignore[assignment]
        sanitise_article(art)  # must not raise

    def test_both_none_become_empty_strings(self) -> None:
        art = _article()
        art.title = None  # type: ignore[assignment]
        art.body = None  # type: ignore[assignment]
        sanitise_article(art)
        assert art.title == ""
        assert art.body == ""

    def test_returns_same_object_when_title_none(self) -> None:
        art = _article()
        art.title = None  # type: ignore[assignment]
        result = sanitise_article(art)
        assert result is art

    def test_html_body_after_none_body_still_cleaned(self) -> None:
        """Verify the None→empty path does not break subsequent real content."""
        art = _article()
        art.body = None  # type: ignore[assignment]
        sanitise_article(art)
        # Now assign real content and sanitise again; must still strip tags
        art.body = "<p>real content</p>"
        art.title = "Proper title"
        sanitise_article(art)
        assert "<p>" not in art.body
        assert art.body == "real content"


# ---------------------------------------------------------------------------
# 2. _apply_env: bad int/float env vars are silently ignored
# ---------------------------------------------------------------------------


class TestApplyEnvBadIntVars:
    """_apply_env wraps int() conversions in try/except (ValueError, TypeError).

    A non-numeric or float-formatted string must leave the config field at its
    default rather than raising or partially updating to 0.
    """

    def _fresh_config(self) -> Config:
        return Config.from_defaults()

    def _apply_env(self, config: Config) -> None:
        from situation_monitor.__main__ import _apply_env  # noqa: PLC0415
        _apply_env(config)

    def test_poll_interval_non_numeric_string_keeps_default(self, monkeypatch) -> None:
        default = Config.from_defaults().poll_interval_seconds
        monkeypatch.setenv("SM_POLL_INTERVAL", "notanumber")
        config = self._fresh_config()
        self._apply_env(config)
        assert config.poll_interval_seconds == default

    def test_poll_interval_float_string_keeps_default(self, monkeypatch) -> None:
        default = Config.from_defaults().poll_interval_seconds
        monkeypatch.setenv("SM_POLL_INTERVAL", "3.14")
        config = self._fresh_config()
        self._apply_env(config)
        assert config.poll_interval_seconds == default

    def test_dashboard_port_non_numeric_keeps_default(self, monkeypatch) -> None:
        default = Config.from_defaults().dashboard_port
        monkeypatch.setenv("SM_DASHBOARD_PORT", "eighty")
        config = self._fresh_config()
        self._apply_env(config)
        assert config.dashboard_port == default

    def test_dashboard_port_float_string_keeps_default(self, monkeypatch) -> None:
        default = Config.from_defaults().dashboard_port
        monkeypatch.setenv("SM_DASHBOARD_PORT", "8080.5")
        config = self._fresh_config()
        self._apply_env(config)
        assert config.dashboard_port == default

    def test_max_articles_non_numeric_keeps_default(self, monkeypatch) -> None:
        default = Config.from_defaults().max_articles_per_digest
        monkeypatch.setenv("SM_MAX_ARTICLES", "lots")
        config = self._fresh_config()
        self._apply_env(config)
        assert config.max_articles_per_digest == default

    def test_max_articles_scientific_notation_keeps_default(self, monkeypatch) -> None:
        default = Config.from_defaults().max_articles_per_digest
        # "1e3" is a valid float but int() raises ValueError on it
        monkeypatch.setenv("SM_MAX_ARTICLES", "1e3")
        config = self._fresh_config()
        self._apply_env(config)
        assert config.max_articles_per_digest == default

    def test_fetch_interval_non_numeric_keeps_default(self, monkeypatch) -> None:
        default = Config.from_defaults().fetch_interval_seconds
        monkeypatch.setenv("SM_FETCH_INTERVAL", "-")
        config = self._fresh_config()
        self._apply_env(config)
        assert config.fetch_interval_seconds == default

    def test_fetch_interval_float_string_keeps_default(self, monkeypatch) -> None:
        default = Config.from_defaults().fetch_interval_seconds
        monkeypatch.setenv("SM_FETCH_INTERVAL", "900.9")
        config = self._fresh_config()
        self._apply_env(config)
        assert config.fetch_interval_seconds == default

    def test_bad_poll_interval_does_not_raise(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_POLL_INTERVAL", "####")
        config = self._fresh_config()
        self._apply_env(config)  # must not raise

    def test_valid_int_string_is_accepted(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_POLL_INTERVAL", "120")
        config = self._fresh_config()
        self._apply_env(config)
        assert config.poll_interval_seconds == 120


# ---------------------------------------------------------------------------
# 3. breaking_ping: non-numeric BREAKING_THRESHOLD is silently discarded
# ---------------------------------------------------------------------------


class TestBreakingPingNonNumericThreshold:
    """When BREAKING_THRESHOLD is set to a non-numeric value and threshold=None
    is passed (so the env var is read), breaking_ping must fall back to 0.85
    without raising.
    """

    def test_non_numeric_env_threshold_does_not_raise(self, monkeypatch) -> None:
        monkeypatch.setenv("BREAKING_THRESHOLD", "notanumber")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        # threshold=None means the env var is read; it must not raise
        breaking_ping([], threshold=None)  # must not raise

    def test_non_numeric_env_threshold_uses_default_fallback(self, monkeypatch) -> None:
        """With env threshold = "abc", fallback is 0.85.  An article at score 0.90
        would trigger if threshold were <= 0.90; without Telegram creds the send
        path is never reached — but the function must complete without error."""
        monkeypatch.setenv("BREAKING_THRESHOLD", "abc")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        art = _article("High significance event happened today", "Some body text.")
        art.relevance_score = 0.90
        # With bad threshold → default 0.85; 0.90 >= 0.85 would fire, but no token → no-op
        breaking_ping([art], threshold=None)  # must not raise

    def test_float_string_env_threshold_is_parsed_normally(self, monkeypatch) -> None:
        """A valid float string like "0.75" must be accepted without error."""
        monkeypatch.setenv("BREAKING_THRESHOLD", "0.75")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        breaking_ping([], threshold=None)  # must not raise

    def test_empty_string_env_threshold_does_not_raise(self, monkeypatch) -> None:
        """An empty string "" for BREAKING_THRESHOLD triggers ValueError → default 0.85."""
        monkeypatch.setenv("BREAKING_THRESHOLD", "")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        breaking_ping([], threshold=None)  # must not raise

    def test_explicit_numeric_threshold_bypasses_env(self, monkeypatch) -> None:
        """When threshold is passed explicitly, BREAKING_THRESHOLD env var is ignored."""
        monkeypatch.setenv("BREAKING_THRESHOLD", "notanumber")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        breaking_ping([], threshold=0.85)  # explicit threshold: no env parse, must not raise

    def test_non_numeric_env_does_not_corrupt_threshold_to_non_float(self, monkeypatch) -> None:
        """After the bad-env path, internal threshold must be a float (0.85), not a string."""
        # We verify indirectly: a high-score article does not cause a crash when
        # the fallback threshold is used to compare against article.relevance_score.
        monkeypatch.setenv("BREAKING_THRESHOLD", "INVALID!!!")
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
        art = _article("Story A title here")
        art.relevance_score = 0.95
        breaking_ping([art], threshold=None)  # threshold comparison must not raise TypeError


# ---------------------------------------------------------------------------
# 4. estimate_spin: llm_client exception returns a SpinResult fallback
# ---------------------------------------------------------------------------


class TestEstimateSpinLlmException:
    """SpinEstimator.estimate_spin must return a SpinResult fallback when
    llm_client raises — never propagate the exception to the caller.
    """

    def _article(self, domain: Domain | None = None) -> Article:
        return Article(
            url="https://bbc.com/news/world/x",
            title="Test spin analysis headline",
            source="BBC",
            body="Article body for spin analysis.",
            domain=domain,
        )

    def _raising_client(self, exc: BaseException):
        """Return a callable that raises *exc* on every call."""
        def _raise(prompt: str) -> str:
            raise exc
        return _raise

    def test_runtime_error_returns_spin_result(self) -> None:
        result = SpinEstimator().estimate_spin(
            self._article(), self._raising_client(RuntimeError("network down"))
        )
        assert isinstance(result, SpinResult)

    def test_value_error_returns_spin_result(self) -> None:
        result = SpinEstimator().estimate_spin(
            self._article(), self._raising_client(ValueError("bad payload"))
        )
        assert isinstance(result, SpinResult)

    def test_os_error_returns_spin_result(self) -> None:
        result = SpinEstimator().estimate_spin(
            self._article(), self._raising_client(OSError("connection refused"))
        )
        assert isinstance(result, SpinResult)

    def test_exception_fallback_spin_pct_is_fifty(self) -> None:
        result = SpinEstimator().estimate_spin(
            self._article(), self._raising_client(RuntimeError("oops"))
        )
        assert result.spin_pct == pytest.approx(50.0)

    def test_exception_fallback_receipts_non_empty(self) -> None:
        result = SpinEstimator().estimate_spin(
            self._article(), self._raising_client(RuntimeError("timeout"))
        )
        assert isinstance(result.receipts, str)
        assert len(result.receipts) > 0

    def test_exception_fallback_rubric_is_dict(self) -> None:
        result = SpinEstimator().estimate_spin(
            self._article(), self._raising_client(RuntimeError("x"))
        )
        assert isinstance(result.rubric, dict)

    def test_exception_fallback_uses_prior_lean(self) -> None:
        """The fallback path calls _prior_lean(article.source); for 'bbc.com'
        the ALLSIDES_PRIORS entry has lean 'center'."""
        result = SpinEstimator().estimate_spin(
            Article(url="https://bbc.com/x", title="BBC story", source="bbc.com"),
            self._raising_client(RuntimeError("failure")),
        )
        assert "center" in result.lens or "centre" in result.lens

    def test_exception_fallback_ai_domain_hype_non_none(self) -> None:
        """For AI-domain articles the fallback must still set hype_vs_substance."""
        result = SpinEstimator().estimate_spin(
            self._article(domain=Domain.AI),
            self._raising_client(RuntimeError("down")),
        )
        assert result.hype_vs_substance is not None

    def test_exception_fallback_non_ai_hype_is_none(self) -> None:
        result = SpinEstimator().estimate_spin(
            self._article(domain=Domain.WORLD),
            self._raising_client(RuntimeError("down")),
        )
        assert result.hype_vs_substance is None

    def test_exception_fallback_ai_vendor_pr_set(self) -> None:
        result = SpinEstimator().estimate_spin(
            self._article(domain=Domain.AI),
            self._raising_client(RuntimeError("down")),
        )
        assert result.vendor_pr is not None

    def test_exception_from_generic_base_exception_subclass(self) -> None:
        """Any Exception subclass, however exotic, must be caught."""
        class _Exotic(Exception):
            pass

        result = SpinEstimator().estimate_spin(
            self._article(), self._raising_client(_Exotic("exotic"))
        )
        assert isinstance(result, SpinResult)

    def test_exception_not_propagated_to_caller(self) -> None:
        """The explicit contract: no exception must escape estimate_spin."""
        try:
            SpinEstimator().estimate_spin(
                self._article(), self._raising_client(RuntimeError("fatal"))
            )
        except Exception as exc:
            pytest.fail(f"estimate_spin propagated an exception: {exc!r}")


# ---------------------------------------------------------------------------
# 5. Non-string LLM responses must degrade gracefully, not crash the parsers.
#    A backend can return None (or any non-string) on a degenerate reply; the
#    try/except around the client call does NOT cover the subsequent parse, so
#    each parser must itself tolerate a non-string response.
# ---------------------------------------------------------------------------


class TestNonStringLLMResponse:
    """relevance, propaganda, and bias parsers must not raise on non-string input."""

    @staticmethod
    def _art() -> Article:
        return Article(
            url="https://example.com/x",
            title="Some neutral headline",
            source="example.com",
            body="Plain factual body.",
        )

    @pytest.mark.parametrize("bad", [None, 123, 4.5, ["x"], {"score": 1}, object()])
    def test_score_relevance_non_string(self, bad: object) -> None:
        from situation_monitor.relevance import score_relevance

        # Non-string client reply → neutral default 1.0, no exception.
        score = score_relevance(self._art(), ["topic"], lambda _p: bad)
        assert score == 1.0

    @pytest.mark.parametrize("bad", [None, 123, 4.5, ["x"], {"flags": []}, object()])
    def test_flag_article_non_string(self, bad: object) -> None:
        from situation_monitor.propaganda import flag_article

        assert flag_article(self._art(), lambda _p: bad) == []

    @pytest.mark.parametrize("bad", [None, 123, 4.5, ["x"], {"rubric": {}}, object()])
    def test_enrich_article_non_string(self, bad: object) -> None:
        from situation_monitor.propaganda import enrich_article

        art = self._art()
        enrich_article(art, lambda _p: bad)  # must not raise
        assert art.propaganda_flags == []
        assert art.loaded_language is False
        assert art.propaganda_flag is False

    @pytest.mark.parametrize("bad", [None, 123, 4.5, ["x"], {"rubric": {}}, object()])
    def test_estimate_spin_non_string(self, bad: object) -> None:
        result = SpinEstimator().estimate_spin(self._art(), lambda _p: bad)
        assert isinstance(result, SpinResult)

"""Tests for Config default llm_backend and no-raise guarantee at startup.

The orchestrator must not require an ANTHROPIC_API_KEY at startup — the default
backend is 'ollama', so get_llm_client(Config()) must return a callable without
touching any API credentials.
"""

from __future__ import annotations

import os

import pytest

from situation_monitor.config import Config
from situation_monitor.llm import get_llm_client


# ---------------------------------------------------------------------------
# Config default value
# ---------------------------------------------------------------------------

class TestConfigDefaultLlmBackend:
    def test_direct_instantiation_defaults_to_ollama(self) -> None:
        assert Config().llm_backend == "ollama"

    def test_from_defaults_returns_ollama(self) -> None:
        assert Config.from_defaults().llm_backend == "ollama"

    def test_from_defaults_is_equivalent_to_direct_instantiation(self) -> None:
        assert Config.from_defaults().llm_backend == Config().llm_backend

    def test_default_is_a_string(self) -> None:
        assert isinstance(Config().llm_backend, str)

    def test_default_is_not_empty(self) -> None:
        assert Config().llm_backend != ""

    def test_default_is_not_claude_backend(self) -> None:
        # Ensures we never default to the backend that needs an API key.
        assert Config().llm_backend != "claude"

    def test_default_is_not_anthropic_backend(self) -> None:
        assert Config().llm_backend not in ("anthropic", "claude-api")


# ---------------------------------------------------------------------------
# from_env does not bleed into Config()
# ---------------------------------------------------------------------------

class TestEnvVarDoesNotPollutePlainInstantiation:
    """SM_LLM_BACKEND must only affect Config.from_env(), not Config()."""

    def test_sm_llm_backend_env_does_not_affect_config_init(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SM_LLM_BACKEND", "claude")
        assert Config().llm_backend == "ollama"

    def test_sm_llm_backend_env_does_not_affect_from_defaults(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SM_LLM_BACKEND", "offline")
        assert Config.from_defaults().llm_backend == "ollama"

    def test_from_env_does_pick_up_sm_llm_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SM_LLM_BACKEND", "offline")
        assert Config.from_env().llm_backend == "offline"

    def test_from_env_without_sm_llm_backend_still_defaults_to_ollama(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SM_LLM_BACKEND", raising=False)
        assert Config.from_env().llm_backend == "ollama"


# ---------------------------------------------------------------------------
# get_llm_client does not raise at construction, API key absent
# ---------------------------------------------------------------------------

class TestGetLlmClientNoRaiseWithoutApiKey:
    """Creating an LLM client from the default config must never raise,
    regardless of whether ANTHROPIC_API_KEY is set in the environment.
    """

    def test_no_raise_with_api_key_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # Must not raise — only construction is tested, not invocation.
        client = get_llm_client(Config())
        assert callable(client)

    def test_no_raise_with_api_key_explicitly_cleared(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("ANTHROPIC_API_KEY_LEGACY", raising=False)
        client = get_llm_client(Config())
        assert callable(client)

    def test_no_raise_with_garbage_api_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
        # With ollama backend, the key is irrelevant; must not raise.
        client = get_llm_client(Config())
        assert callable(client)

    def test_returns_callable_not_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        client = get_llm_client(Config())
        assert client is not None

    def test_returned_callable_accepts_one_string_argument(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The client interface contract: callable(prompt: str) -> str.
        We verify the signature without actually hitting the network.
        """
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        import inspect
        client = get_llm_client(Config())
        sig = inspect.signature(client)
        params = list(sig.parameters.values())
        assert len(params) == 1, f"Expected 1 param, got {len(params)}: {params}"


# ---------------------------------------------------------------------------
# Explicit ollama backend also never raises at construction
# ---------------------------------------------------------------------------

class TestExplicitOllamaBackend:
    def test_explicit_ollama_no_raise(self) -> None:
        client = get_llm_client(Config(llm_backend="ollama"))
        assert callable(client)

    def test_explicit_ollama_with_custom_url_no_raise(self) -> None:
        cfg = Config(llm_backend="ollama", ollama_url="http://localhost:9999")
        client = get_llm_client(cfg)
        assert callable(client)

    def test_explicit_ollama_with_custom_model_no_raise(self) -> None:
        cfg = Config(llm_backend="ollama", ollama_model="mistral")
        client = get_llm_client(cfg)
        assert callable(client)


# ---------------------------------------------------------------------------
# Override path must always win, regardless of backend
# ---------------------------------------------------------------------------

class TestOverrideBypassesBackend:
    def test_override_respected_for_default_config(self) -> None:
        override = lambda prompt: '{"score": 1.0}'
        client = get_llm_client(Config(), _override=override)
        assert client is override

    def test_override_respected_even_with_api_key_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        override = lambda prompt: "ok"
        client = get_llm_client(Config(), _override=override)
        assert client("anything") == "ok"


# ---------------------------------------------------------------------------
# Explicit backend overrides still do not raise at construction
# ---------------------------------------------------------------------------

class TestNonOllamaBackendsDoNotRaiseAtConstruction:
    """Even switching to the claude or offline backend must not raise at
    construction — only at invocation (where network/subprocess calls happen).
    """

    def test_offline_backend_no_raise(self) -> None:
        client = get_llm_client(Config(llm_backend="offline"))
        assert callable(client)

    def test_deterministic_backend_no_raise(self) -> None:
        client = get_llm_client(Config(llm_backend="deterministic"))
        assert callable(client)

    def test_stub_backend_no_raise(self) -> None:
        client = get_llm_client(Config(llm_backend="stub"))
        assert callable(client)

    def test_claude_backend_no_raise_at_construction(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        # No API key check happens until the callable is invoked.
        client = get_llm_client(Config(llm_backend="claude"))
        assert callable(client)

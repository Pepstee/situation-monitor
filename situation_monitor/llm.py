"""LLM client factory for situation_monitor."""

from __future__ import annotations

import json
import subprocess
import urllib.request
from typing import Callable

from situation_monitor.config import Config


def get_llm_client(
    config: Config,
    _override: Callable[[str], str] | None = None,
) -> Callable[[str], str]:
    """Return a callable(prompt) -> str.

    Pass _override for tests to skip real LLM calls.
    """
    if _override is not None:
        return _override

    # "offline" / "deterministic" / "stub" all select the dependency-free local backend:
    # the dual-lens spin estimator and bias rubric run for real (no network), and the
    # optional LLM enrichment hook returns a neutral fixed score. "offline" is the
    # canonical name used by the acceptance run; "stub" is retained for the test suite.
    if config.llm_backend in ("offline", "deterministic", "stub"):

        def _offline(_prompt: str) -> str:
            return '{"score": 0.5}'

        return _offline

    if config.llm_backend == "ollama":

        def _ollama(prompt: str) -> str:
            payload = json.dumps(
                {"model": config.ollama_model, "prompt": prompt, "stream": False}
            ).encode()
            req = urllib.request.Request(
                f"{config.ollama_url}/api/generate",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            return data.get("response", "")

        return _ollama

    def _claude(prompt: str) -> str:
        result = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout

    return _claude

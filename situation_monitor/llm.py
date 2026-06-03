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

    if config.llm_backend == "stub":

        def _stub(_prompt: str) -> str:
            return '{"score": 0.5}'

        return _stub

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

"""LLM client factory for situation_monitor."""

from __future__ import annotations

import json
import re
import subprocess
import urllib.request
from typing import Callable

from situation_monitor.config import Config

_TOPIC_STOPWORDS = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with",
    "any", "all", "new", "news",
})


def _offline_relevance(prompt: str) -> float | None:
    """Deterministic, network-free relevance score derived from the prompt text.

    The relevance prompt embeds a ``Topics:`` line and the article title/body.
    We measure genuine keyword overlap between the topic vocabulary and the
    article text rather than emitting a frozen constant, so the offline backend
    differentiates a matching article from an unrelated one. Returns ``None``
    when the prompt is not a relevance prompt (e.g. spin/propaganda), leaving
    those callers on the neutral default they already expect.
    """
    topic_match = re.search(r"^Topics:\s*(.+)$", prompt, re.MULTILINE)
    title_match = re.search(r"^Article title:\s*(.+)$", prompt, re.MULTILINE)
    if topic_match is None or title_match is None:
        return None

    topic_words = {
        w
        for w in re.findall(r"[a-z0-9]+", topic_match.group(1).lower())
        if len(w) > 2 and w not in _TOPIC_STOPWORDS
    }
    if not topic_words:
        return 1.0

    body_start = title_match.start()
    article_text = prompt[body_start:].lower()
    article_words = set(re.findall(r"[a-z0-9]+", article_text))

    hits = sum(1 for w in topic_words if w in article_words)
    return round(hits / len(topic_words), 4)


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
    # enrichment hook derives a genuine relevance score from real keyword overlap
    # instead of a frozen constant. "offline" is the canonical name used by the
    # acceptance run; "stub" is retained for the test suite.
    if config.llm_backend in ("offline", "deterministic", "stub"):

        def _offline(prompt: str) -> str:
            score = _offline_relevance(prompt)
            # Non-relevance prompts (spin/propaganda) derive their own deterministic
            # signal elsewhere; keep their neutral default unchanged.
            return json.dumps({"score": 0.5 if score is None else score})

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

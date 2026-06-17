"""LLM-based per-article relevance scoring.

The parser is deliberately tolerant of two response shapes, because the default
backend is now a local model (ollama) whose output is not guaranteed to be JSON:

* **Structured JSON** — ``{"score": 0.85}`` (or a bare number) is parsed
  structurally. A JSON object *without* a numeric ``score`` key yields no usable
  score and the caller falls back to the neutral default.
* **Free-form prose** — anything that is not valid JSON falls back to extracting
  the first number in the text (``"Relevance: 0.6"`` → ``0.6``).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Callable

from situation_monitor.models import Article

logger = logging.getLogger(__name__)

_PROMPT_TEMPLATE = """\
You are a relevance classifier. Given an article and a list of topics, \
respond with a single float between 0.0 and 1.0 representing how relevant \
the article is to any of the topics. 1.0 = highly relevant, 0.0 = not relevant at all.

Topics: {topics}

Article title: {title}
Article body (truncated): {body}

Respond with only the numeric score, e.g. 0.85"""

# Optional leading minus so a negative score parses and then clamps to 0.0
# rather than silently losing its sign.
_FLOAT_RE = re.compile(r"-?\d+\.?\d*|-?\.\d+")
_FENCE_OPEN_RE = re.compile(r"^```[^\n]*\n?")
_FENCE_CLOSE_RE = re.compile(r"```\s*$")


def _strip_fence(raw: str) -> str:
    """Remove a surrounding markdown code fence (```json … ```), if present."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = _FENCE_OPEN_RE.sub("", s)
        s = _FENCE_CLOSE_RE.sub("", s)
    return s.strip()


def _extract_score(raw: str) -> float | None:
    """Return a numeric score from *raw*, or None when none is present.

    Prefers structured JSON; falls back to the first number in free-form prose.
    A non-string response (e.g. a backend returning ``None`` on a degenerate
    reply) yields no score so the caller falls back to the neutral default,
    rather than raising.
    """
    if not isinstance(raw, str):
        return None
    text = _strip_fence(raw)
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        data = None

    if isinstance(data, bool):
        return None  # JSON true/false is not a score
    if isinstance(data, (int, float)):
        return float(data)
    if isinstance(data, dict):
        val = data.get("score")
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            return None  # missing / null / non-numeric score → neutral default
        return float(val)

    match = _FLOAT_RE.search(text)
    if match is None:
        return None
    try:
        return float(match.group())
    except ValueError:
        return None


def score_relevance(
    article: Article,
    topics: list[str],
    llm_client: Callable[[str], str],
) -> float:
    """Return a relevance score in [0.0, 1.0] for *article* against *topics*.

    Returns 1.0 when topics is empty (nothing to filter against) or on any error.
    """
    if not topics:
        return 1.0

    prompt = _PROMPT_TEMPLATE.format(
        topics=", ".join(topics),
        title=article.title,
        body=(article.body or "")[:1000],
    )

    try:
        raw = llm_client(prompt)
    except Exception as exc:  # noqa: BLE001
        logger.warning("relevance scoring failed (%s), defaulting to 1.0", exc)
        return 1.0

    score = _extract_score(raw)
    if score is None:
        return 1.0
    return max(0.0, min(1.0, score))

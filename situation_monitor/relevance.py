"""LLM-based per-article relevance scoring."""

from __future__ import annotations

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

_FLOAT_RE = re.compile(r"\d+\.?\d*|\.\d+")


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
        match = _FLOAT_RE.search(raw)
        if match is None:
            raise ValueError("no float found in LLM response")
        score = float(match.group())
        return max(0.0, min(1.0, score))
    except Exception as exc:  # noqa: BLE001
        logger.warning("relevance scoring failed (%s), defaulting to 1.0", exc)
        return 1.0

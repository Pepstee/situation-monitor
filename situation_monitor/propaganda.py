"""Propaganda flag detection via injected LLM client."""

from __future__ import annotations

import json
from typing import Callable

from situation_monitor.models import Article

_PROMPT_TEMPLATE = """\
Analyse the following article for propaganda techniques.
Return a JSON object with a single key "flags" whose value is a list of strings.
Each string names a propaganda technique present (e.g. "loaded_language",
"appeal_to_fear", "bandwagon", "false_dichotomy", "scapegoating").
If none are found, return {{"flags": []}}.
Respond with valid JSON only.

Title: {title}

Body excerpt:
{excerpt}
"""

_EXCERPT_CHARS = 2000


def flag_article(article: Article, client: Callable[[str], str]) -> list[str]:
    excerpt = article.body[:_EXCERPT_CHARS]
    prompt = _PROMPT_TEMPLATE.format(title=article.title, excerpt=excerpt)
    try:
        raw = client(prompt)
        data = json.loads(raw)
        flags = data.get("flags", [])
        if isinstance(flags, list) and all(isinstance(f, str) for f in flags):
            return flags
    except Exception:
        pass
    return []

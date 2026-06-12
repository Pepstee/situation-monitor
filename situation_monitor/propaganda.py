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

_ENRICH_PROMPT_TEMPLATE = """\
Analyse the following article for propaganda techniques.
Return a JSON object with:
  - "flags": a list of strings naming propaganda techniques present
    (e.g. "loaded_language", "appeal_to_fear", "bandwagon", "false_dichotomy", "scapegoating")
  - "loaded_language": true if the text uses emotionally charged or manipulative language
  - "propaganda_flag": true if any propaganda technique is detected
If none are found return {{"flags": [], "loaded_language": false, "propaganda_flag": false}}.
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


def enrich_article(article: Article, client: Callable[[str], str]) -> None:
    """Enrich article in-place: propaganda_flags, loaded_language, propaganda_flag."""
    excerpt = article.body[:_EXCERPT_CHARS]
    prompt = _ENRICH_PROMPT_TEMPLATE.format(title=article.title, excerpt=excerpt)
    try:
        raw = client(prompt)
        data = json.loads(raw)
        flags = data.get("flags", [])
        if isinstance(flags, list) and all(isinstance(f, str) for f in flags):
            article.propaganda_flags = flags
        article.loaded_language = bool(data.get("loaded_language", False))
        article.propaganda_flag = bool(data.get("propaganda_flag", False))
    except Exception:
        pass

"""Propaganda flag detection via injected LLM client.

Two layers cooperate. :func:`enrich_article` consults an LLM (when one is
configured) for nuanced technique detection. :func:`apply_lexicon_baseline`
adds a deterministic, network-free floor driven by the same curated spin
lexicons that power the dual-lens estimator — so the propaganda layer is
genuinely populated and explainable even with no LLM in the loop, instead of
collapsing to a uniform "none" for every article offline.
"""

from __future__ import annotations

import json
from typing import Callable

from situation_monitor.lexicon import score_text
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


# Map curated spin lexicon categories to canonical propaganda technique names.
_LEXICON_TECHNIQUE: dict[str, str] = {
    "loaded_language": "loaded_language",
    "charged_verbs": "loaded_language",
    "fear": "appeal_to_fear",
    "endorsement": "glittering_generalities",
}


def lexicon_signal(article: Article) -> tuple[list[str], bool, bool]:
    """Deterministic, offline propaganda signal from the curated spin lexicons.

    Returns ``(flags, loaded_language, propaganda_flag)``. Network-free and
    fully explainable — it reuses the same scorer as the dual-lens estimator, so
    a neutral wire report yields no flags and a framed headline yields the exact
    techniques that fired.
    """
    score = score_text(article.title, article.body or "")
    flags: list[str] = []
    for category in score.fired:
        technique = _LEXICON_TECHNIQUE.get(category)
        if technique and technique not in flags:
            flags.append(technique)
    loaded = bool(score.fired.get("loaded_language") or score.fired.get("charged_verbs"))
    return flags, loaded, bool(flags)


def apply_lexicon_baseline(article: Article) -> None:
    """OR-merge the deterministic lexicon signal onto *article* in-place.

    Only ever adds signal: a positive from a real LLM is never downgraded, but
    when the LLM contributed nothing (e.g. the offline backend) the article still
    carries genuine, differentiated propaganda flags.
    """
    flags, loaded, flagged = lexicon_signal(article)
    merged = list(article.propaganda_flags)
    for technique in flags:
        if technique not in merged:
            merged.append(technique)
    article.propaganda_flags = merged
    article.loaded_language = bool(article.loaded_language) or loaded
    article.propaganda_flag = bool(article.propaganda_flag) or flagged

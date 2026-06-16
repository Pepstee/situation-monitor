"""Propaganda flag detection via injected LLM client.

Two layers cooperate. :func:`enrich_article` consults an LLM (when one is
configured) for nuanced technique detection. :func:`apply_lexicon_baseline`
adds a deterministic, network-free floor driven by the same curated spin
lexicons that power the dual-lens estimator — so the propaganda layer is
genuinely populated and explainable even with no LLM in the loop, instead of
collapsing to a uniform "none" for every article offline.
"""

from __future__ import annotations

import re
from typing import Callable

from situation_monitor.lexicon import score_text
from situation_monitor.models import Article

_PROMPT_TEMPLATE = """\
Analyse the following article for propaganda techniques.
List any propaganda techniques found, one per line, choosing from:
loaded_language, appeal_to_fear, bandwagon, false_dichotomy, scapegoating.
If none are found, write "none".

Title: {title}

Body excerpt:
{excerpt}
"""

_ENRICH_PROMPT_TEMPLATE = """\
Analyse the following article for propaganda techniques.
List any propaganda techniques found, one per line, choosing from:
loaded_language, appeal_to_fear, bandwagon, false_dichotomy, scapegoating.
Then on separate lines state:
LOADED_LANGUAGE: yes or no
PROPAGANDA: yes or no

Title: {title}

Body excerpt:
{excerpt}
"""

_EXCERPT_CHARS = 2000

_KNOWN_TECHNIQUES = [
    "loaded_language",
    "appeal_to_fear",
    "bandwagon",
    "false_dichotomy",
    "scapegoating",
]

_TECHNIQUE_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _KNOWN_TECHNIQUES) + r")\b",
    re.IGNORECASE,
)
_LOADED_RE = re.compile(r"LOADED[_\s]LANGUAGE\s*[:\-]\s*(\w+)", re.IGNORECASE)
_PROPAGANDA_RE = re.compile(r"PROPAGANDA(?:[_\s]FLAG)?\s*[:\-]\s*(\w+)", re.IGNORECASE)
_TRUTHY_RE = re.compile(r"^(yes|true|1)$", re.IGNORECASE)


def _is_truthy(val: str) -> bool:
    return bool(_TRUTHY_RE.match(val.strip()))


def _parse_flags(raw: str) -> list[str]:
    seen: set[str] = set()
    flags: list[str] = []
    for m in _TECHNIQUE_RE.finditer(raw):
        t = m.group(1).lower()
        if t not in seen:
            seen.add(t)
            flags.append(t)
    return flags


def flag_article(article: Article, client: Callable[[str], str]) -> list[str]:
    excerpt = (article.body or "")[:_EXCERPT_CHARS]
    prompt = _PROMPT_TEMPLATE.format(title=article.title, excerpt=excerpt)
    try:
        raw = client(prompt)
        return _parse_flags(raw)
    except Exception:
        pass
    return []


def enrich_article(article: Article, client: Callable[[str], str]) -> None:
    """Enrich article in-place: propaganda_flags, loaded_language, propaganda_flag."""
    excerpt = (article.body or "")[:_EXCERPT_CHARS]
    prompt = _ENRICH_PROMPT_TEMPLATE.format(title=article.title, excerpt=excerpt)
    try:
        raw = client(prompt)
        flags = _parse_flags(raw)
        article.propaganda_flags = flags

        m = _LOADED_RE.search(raw)
        article.loaded_language = _is_truthy(m.group(1)) if m else False

        m = _PROPAGANDA_RE.search(raw)
        article.propaganda_flag = _is_truthy(m.group(1)) if m else bool(flags)
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

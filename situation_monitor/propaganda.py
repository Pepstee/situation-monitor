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

_KNOWN_SET = frozenset(_KNOWN_TECHNIQUES)

_TECHNIQUE_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _KNOWN_TECHNIQUES) + r")\b",
    re.IGNORECASE,
)
_LOADED_RE = re.compile(r"LOADED[_\s]LANGUAGE\s*[:\-]\s*(\w+)", re.IGNORECASE)
_PROPAGANDA_RE = re.compile(r"PROPAGANDA(?:[_\s]FLAG)?\s*[:\-]\s*(\w+)", re.IGNORECASE)
_TRUTHY_RE = re.compile(r"^(yes|true|1)$", re.IGNORECASE)
_FENCE_OPEN_RE = re.compile(r"^```[^\n]*\n?")
_FENCE_CLOSE_RE = re.compile(r"```\s*$")

# Sentinels distinguishing "response was not JSON" (→ regex fallback) from
# "JSON object had a malformed flags list" (→ leave existing flags untouched).
_NOT_JSON = object()
_INVALID = object()


def _is_truthy(val: str) -> bool:
    return bool(_TRUTHY_RE.match(val.strip()))


def _strip_fence(raw: str) -> str:
    """Remove a surrounding markdown code fence (```json … ```), if present."""
    s = raw.strip()
    if s.startswith("```"):
        s = _FENCE_OPEN_RE.sub("", s)
        s = _FENCE_CLOSE_RE.sub("", s)
    return s.strip()


def _try_json(raw: str) -> object:
    """Parse *raw* as JSON, returning ``_NOT_JSON`` when it is free-form prose."""
    try:
        return json.loads(_strip_fence(raw))
    except (ValueError, TypeError):
        return _NOT_JSON


def _flags_from_dict(data: dict) -> object:
    """Resolve canonical technique flags from a structured JSON object.

    Returns the validated list when a ``flags``/``techniques`` key holds a list
    of strings, ``_INVALID`` when such a key is present but malformed (so the
    caller leaves any existing flags untouched), or ``[]`` when no such key
    exists (a well-formed object that simply names no techniques).
    """
    for key in ("flags", "techniques"):
        if key in data:
            val = data[key]
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                return _INVALID
            seen: set[str] = set()
            out: list[str] = []
            for x in val:
                t = x.lower()
                if t in _KNOWN_SET and t not in seen:
                    seen.add(t)
                    out.append(t)
            return out
    return []


def _flags_from_text(raw: str) -> list[str]:
    """Extract canonical technique names from free-form prose via regex."""
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
    except Exception:
        return []
    if not isinstance(raw, str):
        # A backend returning a non-string (e.g. None on a degenerate reply)
        # names no techniques rather than crashing the parser.
        raw = ""

    data = _try_json(raw)
    if data is _NOT_JSON:
        return _flags_from_text(raw)
    if not isinstance(data, dict):
        return []  # valid JSON but not an object → no flags
    flags = _flags_from_dict(data)
    return [] if flags is _INVALID else flags


def enrich_article(article: Article, client: Callable[[str], str]) -> None:
    """Enrich article in-place: propaganda_flags, loaded_language, propaganda_flag."""
    excerpt = (article.body or "")[:_EXCERPT_CHARS]
    prompt = _ENRICH_PROMPT_TEMPLATE.format(title=article.title, excerpt=excerpt)
    try:
        raw = client(prompt)
    except Exception:
        return
    if not isinstance(raw, str):
        raw = ""  # non-string reply → leave article defaults untouched

    data = _try_json(raw)

    if data is _NOT_JSON:
        # Free-form prose: regex out technique names and explicit flag lines.
        flags = _flags_from_text(raw)
        article.propaganda_flags = flags
        m = _LOADED_RE.search(raw)
        article.loaded_language = _is_truthy(m.group(1)) if m else False
        m = _PROPAGANDA_RE.search(raw)
        article.propaganda_flag = _is_truthy(m.group(1)) if m else bool(flags)
        return

    if not isinstance(data, dict):
        return  # valid JSON but not an object → leave defaults

    # Structured JSON: honour explicit fields; a malformed flags list is ignored.
    flags = _flags_from_dict(data)
    if flags is not _INVALID:
        article.propaganda_flags = flags

    ll = data.get("loaded_language")
    article.loaded_language = bool(ll) if isinstance(ll, (bool, int)) else False
    pf = data.get("propaganda_flag")
    article.propaganda_flag = bool(pf) if isinstance(pf, (bool, int)) else False


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

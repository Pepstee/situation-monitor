"""Deterministic, explainable spin lexicons and scorer.

This module makes "spin made measurable" work OFFLINE, with no LLM in the loop.
It scores an article's headline and body against four curated lexicons drawn from
the spin rubric (loaded language, charged verbs, fear/emotional framing, and
endorsement framing) and returns a 0-100 spin percentage together with the exact
terms that fired — so every score is auditable, not asserted.

A neutral wire report scores near zero; a heavily framed piece scores high. The
headline carries disproportionate framing weight, so title hits count double.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Curated lexicons (rubric-aligned). Lower-cased, matched on word boundaries.
# ---------------------------------------------------------------------------

# Pejorative / emotionally charged nouns and adjectives.
LOADED_LANGUAGE: frozenset[str] = frozenset({
    "thug", "thugs", "hero", "heroes", "extremist", "extremists", "radical",
    "radicals", "regime", "elite", "elites", "mob", "chaos", "scandal",
    "shameful", "disgraceful", "outrageous", "reckless", "sweeping", "draconian",
    "tyranny", "tyrant", "corrupt", "corruption", "sinister", "rogue", "fanatic",
    "fanatics", "propaganda", "woke", "globalist", "globalists", "establishment",
    "ruthless", "brutal", "controversial", "so-called", "fearmongering",
})

# Hyperbolic / charged action verbs (headline-ese).
CHARGED_VERBS: frozenset[str] = frozenset({
    "slam", "slams", "slammed", "blast", "blasts", "blasted", "destroy",
    "destroys", "destroyed", "threaten", "threatens", "threatened", "surge",
    "surges", "surged", "plummet", "plummets", "plummeted", "soar", "soars",
    "soared", "crush", "crushes", "crushed", "erupt", "erupts", "erupted",
    "explode", "explodes", "exploded", "devastate", "devastates", "devastated",
    "hammer", "hammers", "hammered", "torch", "torches", "torched", "ravage",
    "ravages", "ravaged", "slash", "slashes", "slashed", "smash", "smashes",
    "smashed", "rip", "rips", "ripped", "hamper", "hampers", "hampered",
})

# Fear / alarm / emotional-framing terms.
FEAR_TERMS: frozenset[str] = frozenset({
    "fear", "fears", "panic", "terror", "terrifying", "alarming", "alarm",
    "dangerous", "danger", "threat", "threats", "warn", "warns", "warned",
    "warning", "dire", "grim", "devastating", "shocking", "shock", "horror",
    "horrifying", "catastrophe", "catastrophic", "crisis", "disaster",
    "disastrous", "nightmare", "doom", "doomed", "peril", "perilous",
    "spiral", "meltdown", "collapse", "collapses", "collapsed",
})

# Endorsement / virtue framing (positive spin still counts as framing).
ENDORSEMENT_TERMS: frozenset[str] = frozenset({
    "back", "backs", "backed", "endorse", "endorses", "endorsed", "praise",
    "praises", "praised", "hail", "hails", "hailed", "celebrate", "celebrates",
    "celebrated", "triumph", "triumphs", "breakthrough", "breakthroughs",
    "historic", "landmark", "groundbreaking", "visionary", "champion",
    "champions", "championed", "vindicated", "applaud", "applauds", "applauded",
})

# Per-category contribution weights. Negative framing (fear, charged verbs,
# loaded language) reads as heavier spin than positive endorsement framing.
_CATEGORY_WEIGHTS: dict[str, float] = {
    "loaded_language": 1.0,
    "charged_verbs": 1.0,
    "fear": 1.0,
    "endorsement": 0.6,
}

_CATEGORY_LEXICONS: dict[str, frozenset[str]] = {
    "loaded_language": LOADED_LANGUAGE,
    "charged_verbs": CHARGED_VERBS,
    "fear": FEAR_TERMS,
    "endorsement": ENDORSEMENT_TERMS,
}

# Title hits frame the whole story, so they count double.
_TITLE_WEIGHT = 2.0
# Density-to-percentage scale, calibrated so a single charged headline term lands
# in the mid-30s and a densely loaded piece in the 70-90 band (100 stays rare).
_SCALE = 450.0
_LABELS: dict[str, str] = {
    "loaded_language": "Loaded Language",
    "charged_verbs": "Charged Verbs",
    "fear": "Fear / Emotional Framing",
    "endorsement": "Endorsement Framing",
}


@dataclass
class SpinScore:
    """Result of a deterministic spin scoring pass."""

    spin_pct: float
    fired: dict[str, list[str]] = field(default_factory=dict)
    subscores: dict[str, float] = field(default_factory=dict)

    def receipts(self) -> str:
        """Human-readable, auditable explanation of the score."""
        if not self.fired:
            return "No charged language detected in headline or lede (neutral framing)."
        parts = [
            f"{_LABELS[cat]}: {', '.join(words)}"
            for cat, words in self.fired.items()
            if words
        ]
        return "Spin signals fired — " + "; ".join(parts) + "."


def _tokenise(text: str) -> list[str]:
    return re.findall(r"[a-z][a-z'-]*", text.lower())


def score_text(title: str, body: str = "") -> SpinScore:
    """Score *title* and *body* for spin; return a fully explainable SpinScore.

    The score is a weighted density of charged terms — independent of any LLM —
    so the same input always yields the same, auditable result.
    """
    title_tokens = _tokenise(title)
    body_tokens = _tokenise(body)

    fired: dict[str, list[str]] = {}
    subscores: dict[str, float] = {}
    weighted_hits = 0.0

    for category, lexicon in _CATEGORY_LEXICONS.items():
        words: list[str] = []
        title_hits = sum(1 for t in title_tokens if t in lexicon)
        body_hits = sum(1 for t in body_tokens if t in lexicon)
        if title_hits or body_hits:
            seen: set[str] = set()
            for t in title_tokens + body_tokens:
                if t in lexicon and t not in seen:
                    seen.add(t)
                    words.append(t)
            fired[category] = words
        cat_weight = _CATEGORY_WEIGHTS[category]
        contribution = cat_weight * (title_hits * _TITLE_WEIGHT + body_hits)
        weighted_hits += contribution
        subscores[category] = round(contribution, 4)

    effective_tokens = len(title_tokens) * _TITLE_WEIGHT + len(body_tokens)
    density = weighted_hits / effective_tokens if effective_tokens else 0.0
    spin_pct = max(0.0, min(100.0, round(density * _SCALE, 1)))

    return SpinScore(spin_pct=spin_pct, fired=fired, subscores=subscores)

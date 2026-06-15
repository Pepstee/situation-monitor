"""Curated media bias dataset, rubric-driven spin estimator, and lookup helpers."""

from __future__ import annotations

import json
import re
from typing import Callable
from urllib.parse import urlparse

from situation_monitor.config import DEFAULT_SOURCE_DEFS
from situation_monitor.models import Article, Domain, SpinResult


# ---------------------------------------------------------------------------
# Rubric constants
# ---------------------------------------------------------------------------

RUBRIC_LOADED_LANGUAGE: str = (
    "Loaded language uses emotionally charged words to frame events beyond what facts justify. "
    "Signals: pejorative nouns (thug, hero, extremist), hyperbolic verbs (slam, destroy, blast), "
    "superlative adverbs, and dog-whistle terms tied to cultural battles. Score high when the "
    "headline or opening paragraph swaps neutral vocabulary for charged synonyms."
)

RUBRIC_OMISSION: str = (
    "Omission bias omits key stakeholders, counterfactual evidence, or context that would alter "
    "the reader's conclusion. Signals: absence of the opposing view in a controversy, no data "
    "cited for quantitative claims, single-source reports on multi-actor events, and missing "
    "historical context that would contradict the narrative framing."
)

RUBRIC_SOURCING_ASYMMETRY: str = (
    "Sourcing asymmetry selectively uses credentialed or official sources only for one side of a "
    "debate. Signals: named experts quoted only for the favoured position, anonymous sourcing for "
    "unfavoured claims, institutional affiliations disclosed selectively, and disproportionate "
    "quote length between opposing sides."
)

RUBRIC_EMOTIONAL_FRAMING: str = (
    "Emotional framing elevates feelings over analysis to guide interpretation. Signals: "
    "personalised victim or hero narratives at the lede, imagery evoking fear or admiration, "
    "rhetorical questions implying an obvious answer, and sequencing that builds dread or triumph "
    "before presenting evidence."
)


# ---------------------------------------------------------------------------
# Curated bias data
# ---------------------------------------------------------------------------

CURATED_BIAS: dict[str, dict[str, str]] = {
    "foxnews.com": {"lean": "right", "reliability_tier": "mixed"},
    "cnn.com": {"lean": "left", "reliability_tier": "medium"},
    "bbc.com": {"lean": "center", "reliability_tier": "high"},
    "bbc.co.uk": {"lean": "center", "reliability_tier": "high"},
    "nytimes.com": {"lean": "left-center", "reliability_tier": "high"},
    "wsj.com": {"lean": "right-center", "reliability_tier": "high"},
    "reuters.com": {"lean": "center", "reliability_tier": "high"},
    "apnews.com": {"lean": "center", "reliability_tier": "high"},
    "theguardian.com": {"lean": "left-center", "reliability_tier": "high"},
    "washingtonpost.com": {"lean": "left-center", "reliability_tier": "high"},
    "breitbart.com": {"lean": "right", "reliability_tier": "low"},
    "huffpost.com": {"lean": "left", "reliability_tier": "medium"},
    "msnbc.com": {"lean": "left", "reliability_tier": "medium"},
    "nationalreview.com": {"lean": "right", "reliability_tier": "medium"},
    "economist.com": {"lean": "center", "reliability_tier": "high"},
    "vox.com": {"lean": "left", "reliability_tier": "medium"},
    "thehill.com": {"lean": "center", "reliability_tier": "medium"},
    "politico.com": {"lean": "center", "reliability_tier": "high"},
    "axios.com": {"lean": "center", "reliability_tier": "high"},
    "bloomberg.com": {"lean": "center", "reliability_tier": "high"},
    "ft.com": {"lean": "center", "reliability_tier": "high"},
    "aljazeera.com": {"lean": "left-center", "reliability_tier": "medium"},
    "dw.com": {"lean": "center", "reliability_tier": "high"},
    "npr.org": {"lean": "left-center", "reliability_tier": "high"},
}


# ---------------------------------------------------------------------------
# ALLSIDES_PRIORS: combined prior from DEFAULT_SOURCE_DEFS + CURATED_BIAS
# ---------------------------------------------------------------------------

def _lens_to_lean(lens: str) -> str:
    """Map SourceDef lens vocabulary to CURATED_BIAS lean vocabulary."""
    return {"centre": "center", "state": "center"}.get(lens, lens)


def _extract_domain(url: str) -> str:
    """Extract bare hostname from a URL, stripping common feed subdomains."""
    netloc = urlparse(url).netloc or url
    return re.sub(r"^(?:www|feeds|rss|m)\.", "", netloc.lower())


ALLSIDES_PRIORS: dict[str, dict[str, str]] = {
    _extract_domain(sd.url): {"lean": _lens_to_lean(sd.lens), "reliability_tier": "medium"}
    for sd in DEFAULT_SOURCE_DEFS
}
# CURATED_BIAS entries win on conflict — they are more precisely rated
ALLSIDES_PRIORS.update(CURATED_BIAS)


# ---------------------------------------------------------------------------
# Backward-compatible lookup helpers (unchanged)
# ---------------------------------------------------------------------------

def get_source_lean(source: str) -> str | None:
    """Return the political lean for a source via case-insensitive substring match."""
    source_lower = source.lower()
    for key, entry in CURATED_BIAS.items():
        if key in source_lower or source_lower in key:
            return entry["lean"]
    return None


def get_source_reliability(source: str) -> str | None:
    """Return the reliability_tier for a source via case-insensitive substring match."""
    source_lower = source.lower()
    for key, entry in CURATED_BIAS.items():
        if key in source_lower or source_lower in key:
            return entry["reliability_tier"]
    return None


# ---------------------------------------------------------------------------
# SpinEstimator internals
# ---------------------------------------------------------------------------

_RUBRIC_LABELS: dict[str, str] = {
    "loaded_language": "Loaded Language",
    "omission": "Omission",
    "sourcing_asymmetry": "Sourcing Asymmetry",
    "emotional_framing": "Emotional Framing",
}


def _as_float(value: object, default: float) -> float:
    """Coerce an arbitrary LLM-supplied value to float, falling back on bad input.

    Booleans are rejected (a JSON ``true`` is not a numeric spin score) so a
    malformed-but-valid response like ``{"spin_pct": "high"}`` degrades to the
    default instead of crashing the estimator.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _try_parse(raw: str) -> dict | None:
    """Extract the first JSON object from an LLM response string."""
    raw = raw.strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(raw[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None


def _prior_lean(source: str) -> str:
    """Substring-search ALLSIDES_PRIORS for source lean; default to 'center'."""
    source_lower = source.lower()
    for key, entry in ALLSIDES_PRIORS.items():
        if key in source_lower or source_lower in key:
            return entry["lean"]
    return "center"


# ---------------------------------------------------------------------------
# SpinEstimator
# ---------------------------------------------------------------------------

class SpinEstimator:
    """Rubric-driven spin estimator backed by a pluggable LLM client."""

    def estimate_spin(self, article: Article, llm_client: Callable[[str], str]) -> SpinResult:
        """Estimate spin for *article* using *llm_client* as the inference backend.

        Falls back to ALLSIDES_PRIORS when the LLM returns unparseable output.
        For Domain.AI articles, populates hype_vs_substance and vendor_pr; for
        all other domains those fields remain None.
        """
        is_ai = article.domain is Domain.AI
        prompt = (
            "Analyse the following article for media spin using four rubrics. "
            "Return JSON only — no prose.\n\n"
            f"RUBRIC — Loaded Language: {RUBRIC_LOADED_LANGUAGE}\n\n"
            f"RUBRIC — Omission: {RUBRIC_OMISSION}\n\n"
            f"RUBRIC — Sourcing Asymmetry: {RUBRIC_SOURCING_ASYMMETRY}\n\n"
            f"RUBRIC — Emotional Framing: {RUBRIC_EMOTIONAL_FRAMING}\n\n"
            f"Source: {article.source}\n"
            f"Title: {article.title}\n"
            f"Body (first 1500 chars): {(article.body or '')[:1500]}\n\n"
            "Respond with exactly this JSON schema and nothing else:\n"
            '{\n'
            '  "spin_pct": <float 0-100>,\n'
            '  "lens": "left|right|center|left-center|right-center",\n'
            '  "rubric": {\n'
            '    "loaded_language": <float 0-1>,\n'
            '    "omission": <float 0-1>,\n'
            '    "sourcing_asymmetry": <float 0-1>,\n'
            '    "emotional_framing": <float 0-1>\n'
            '  },\n'
            '  "hype_vs_substance": <float 0-1 or null>,\n'
            '  "vendor_pr": true|false|null\n'
            '}'
        )

        raw = llm_client(prompt)
        parsed = _try_parse(raw)

        if parsed is None:
            return self._fallback(article, is_ai)

        rubric_scores: dict[str, float] = {
            k: float(v)
            for k, v in parsed.get("rubric", {}).items()
            if isinstance(v, (int, float))
        }
        spin_pct = _as_float(parsed.get("spin_pct"), 50.0)
        lens = str(parsed.get("lens") or "center")

        fired = [k for k, s in rubric_scores.items() if s > 0.3]
        if fired:
            receipts = "Spin signals fired: " + ", ".join(
                f"{_RUBRIC_LABELS.get(k, k)} ({rubric_scores[k]:.2f})" for k in fired
            ) + "."
        else:
            receipts = "No strong spin signals detected across all four rubrics."

        hype_vs_substance: float | None = None
        vendor_pr: bool | None = None
        if is_ai:
            raw_hvs = parsed.get("hype_vs_substance")
            if isinstance(raw_hvs, (int, float)):
                hype_vs_substance = max(0.0, min(1.0, float(raw_hvs)))
            else:
                hype_vs_substance = round(spin_pct / 100.0, 4)
            raw_vpr = parsed.get("vendor_pr")
            vendor_pr = bool(raw_vpr) if raw_vpr is not None else bool(hype_vs_substance > 0.6)

        return SpinResult(
            spin_pct=spin_pct,
            lens=lens,
            rubric=rubric_scores,
            receipts=receipts,
            hype_vs_substance=hype_vs_substance,
            vendor_pr=vendor_pr,
        )

    def _fallback(self, article: Article, is_ai: bool) -> SpinResult:
        lean = _prior_lean(article.source)
        hype_vs_substance: float | None = None
        vendor_pr: bool | None = None
        if is_ai:
            hype_vs_substance = 0.5
            vendor_pr = False
        return SpinResult(
            spin_pct=50.0,
            lens=lean,
            rubric={},
            receipts=(
                f"LLM response unparseable; prior lean for '{article.source}': {lean}. "
                "Defaulting to neutral spin estimate."
            ),
            hype_vs_substance=hype_vs_substance,
            vendor_pr=vendor_pr,
        )

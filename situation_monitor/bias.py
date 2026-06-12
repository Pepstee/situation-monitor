"""Curated media bias dataset and lookup helpers."""

from __future__ import annotations

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

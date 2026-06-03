"""Curated media bias dataset and lookup helpers."""

from __future__ import annotations

CURATED_BIAS: dict[str, dict[str, str]] = {
    "foxnews.com": {"lean": "right", "reliability": "mixed"},
    "cnn.com": {"lean": "left", "reliability": "medium"},
    "bbc.com": {"lean": "center", "reliability": "high"},
    "bbc.co.uk": {"lean": "center", "reliability": "high"},
    "nytimes.com": {"lean": "left-center", "reliability": "high"},
    "wsj.com": {"lean": "right-center", "reliability": "high"},
    "reuters.com": {"lean": "center", "reliability": "high"},
    "apnews.com": {"lean": "center", "reliability": "high"},
    "theguardian.com": {"lean": "left-center", "reliability": "high"},
    "washingtonpost.com": {"lean": "left-center", "reliability": "high"},
    "breitbart.com": {"lean": "right", "reliability": "low"},
    "huffpost.com": {"lean": "left", "reliability": "medium"},
    "msnbc.com": {"lean": "left", "reliability": "medium"},
    "nationalreview.com": {"lean": "right", "reliability": "medium"},
    "economist.com": {"lean": "center", "reliability": "high"},
    "vox.com": {"lean": "left", "reliability": "medium"},
    "thehill.com": {"lean": "center", "reliability": "medium"},
    "politico.com": {"lean": "center", "reliability": "high"},
    "axios.com": {"lean": "center", "reliability": "high"},
    "bloomberg.com": {"lean": "center", "reliability": "high"},
    "ft.com": {"lean": "center", "reliability": "high"},
    "aljazeera.com": {"lean": "left-center", "reliability": "medium"},
    "dw.com": {"lean": "center", "reliability": "high"},
    "npr.org": {"lean": "left-center", "reliability": "high"},
}


def get_source_lean(source: str) -> str | None:
    """Return the political lean for a source via case-insensitive substring match."""
    source_lower = source.lower()
    for key, entry in CURATED_BIAS.items():
        if key in source_lower or source_lower in key:
            return entry["lean"]
    return None


def get_source_reliability(source: str) -> str | None:
    """Return the reliability label for a source via case-insensitive substring match."""
    source_lower = source.lower()
    for key, entry in CURATED_BIAS.items():
        if key in source_lower or source_lower in key:
            return entry["reliability"]
    return None

"""Core domain models for situation_monitor."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class SourceReliability(enum.Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class Domain(enum.Enum):
    WORLD = "world"
    MARKETS = "markets"
    AI = "ai"


@dataclass
class SpinResult:
    spin_pct: float
    lens: str
    rubric: dict[str, float]
    receipts: str
    hype_vs_substance: Optional[float] = None
    vendor_pr: Optional[bool] = None


@dataclass
class Article:
    url: str
    title: str
    source: str
    body: str = ""
    published_at: Optional[datetime] = None
    reliability: SourceReliability = SourceReliability.UNKNOWN
    tags: list[str] = field(default_factory=list)
    relevance_score: Optional[float] = None
    cluster_id: Optional[str] = None
    source_lean: Optional[str] = None
    source_reliability_label: Optional[str] = None
    reliability_tier: Optional[str] = None
    propaganda_flags: list[str] = field(default_factory=list)
    loaded_language: bool = False
    propaganda_flag: bool = False
    polymarket_odds: Optional[float] = None
    domain: Optional[Domain] = None

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("Article.url must not be empty")
        if not self.title:
            raise ValueError("Article.title must not be empty")
        if not self.source:
            raise ValueError("Article.source must not be empty")


@dataclass
class DigestEntry:
    articles: list[Article]
    summary: str
    generated_at: datetime = field(default_factory=datetime.utcnow)
    topic: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.articles, list):
            raise TypeError("DigestEntry.articles must be a list")

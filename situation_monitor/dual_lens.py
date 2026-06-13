"""Dual-lens event grouper: cluster articles by event, annotate with spin, bucket by lean."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from situation_monitor.bias import _prior_lean
from situation_monitor.models import Article, SpinResult

_STOPWORDS = frozenset({
    "the", "a", "an", "in", "of", "to", "is", "by", "on", "for", "and", "or",
    "at", "as", "it", "its", "with", "that", "this", "was", "are", "from",
    "be", "has", "had", "have", "he", "she", "they", "we", "you", "i",
    "not", "but", "new", "over", "says", "after", "will", "than", "into",
})

_MIN_OVERLAP = 2  # minimum shared significant words to merge into the same event cluster


@dataclass
class AnnotatedArticle:
    article: Article
    spin: SpinResult


@dataclass
class DualLensEvent:
    event_title: str
    left_articles: list[AnnotatedArticle] = field(default_factory=list)
    right_articles: list[AnnotatedArticle] = field(default_factory=list)
    center_articles: list[AnnotatedArticle] = field(default_factory=list)
    spin_delta: float = 0.0


def _significant_words(title: str) -> frozenset[str]:
    words = re.sub(r"[^\w\s]", "", title.lower()).split()
    return frozenset(w for w in words if w not in _STOPWORDS and len(w) > 2)


def _stub_spin(article: Article) -> SpinResult:
    lean = article.source_lean or _prior_lean(article.source)
    return SpinResult(
        spin_pct=50.0,
        lens=lean,
        rubric={},
        receipts=f"Stub spin estimate; prior lean for '{article.source}': {lean}.",
    )


def _lean_bucket(lens: str) -> str:
    if "left" in lens:
        return "left"
    if "right" in lens:
        return "right"
    return "center"


def _avg_spin(annotated: list[AnnotatedArticle]) -> float:
    if not annotated:
        return 0.0
    return sum(a.spin.spin_pct for a in annotated) / len(annotated)


def group_by_event(
    articles: list[Article],
    spin_fn: Optional[Callable[[Article], SpinResult]] = None,
) -> list[DualLensEvent]:
    """Cluster articles about the same real-world event by semantic title overlap.

    Uses multi-word intersection (>= _MIN_OVERLAP shared significant words) rather
    than the crude first-non-stopword cluster_id. Returns one DualLensEvent per
    cluster with articles pre-bucketed by political lean and inline SpinResult.

    spin_fn defaults to a bias-prior stub so tests can run without an LLM.
    """
    if spin_fn is None:
        spin_fn = _stub_spin

    annotated = [AnnotatedArticle(article=a, spin=spin_fn(a)) for a in articles]

    clusters: list[list[AnnotatedArticle]] = []
    cluster_words: list[frozenset[str]] = []

    for aa in annotated:
        words = _significant_words(aa.article.title)
        best_cluster = -1
        best_overlap = 0
        for i, cw in enumerate(cluster_words):
            overlap = len(words & cw)
            if overlap >= _MIN_OVERLAP and overlap > best_overlap:
                best_overlap = overlap
                best_cluster = i

        if best_cluster >= 0:
            clusters[best_cluster].append(aa)
            # grow the cluster vocabulary so later articles can join on any member's words
            cluster_words[best_cluster] = cluster_words[best_cluster] | words
        else:
            clusters.append([aa])
            cluster_words.append(words)

    events: list[DualLensEvent] = []
    for cluster in clusters:
        event_title = max(cluster, key=lambda aa: len(aa.article.title)).article.title

        left: list[AnnotatedArticle] = []
        right: list[AnnotatedArticle] = []
        center: list[AnnotatedArticle] = []

        for aa in cluster:
            bucket = _lean_bucket(aa.spin.lens)
            if bucket == "left":
                left.append(aa)
            elif bucket == "right":
                right.append(aa)
            else:
                center.append(aa)

        events.append(DualLensEvent(
            event_title=event_title,
            left_articles=left,
            right_articles=right,
            center_articles=center,
            spin_delta=abs(_avg_spin(left) - _avg_spin(right)),
        ))

    return events

"""Deterministic post-ingestion scoring, deduplication, clustering, and digesting."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from schemas import Article


_URGENCY_TERMS = frozenset(
    "critical urgent breaking alert error warning fail crash down outage breach "
    "incident attack vulnerability exposed leaked".split()
)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)
_TRACKING_PARAMETER = re.compile(r"^utm_", re.IGNORECASE)


@dataclass(frozen=True)
class ScoredArticle:
    """An Article with a bounded, inspectable deterministic score."""

    article: Article
    score: int
    confidence_low: int
    confidence_high: int
    signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.confidence_low <= self.score <= self.confidence_high <= 100:
            raise ValueError(
                "score bounds must satisfy "
                "0 <= confidence_low <= score <= confidence_high <= 100"
            )

    @property
    def relevance(self) -> float:
        """Expose the orphan donor's normalized relevance scale."""

        return self.score / 100


@dataclass(frozen=True)
class ArticleCluster:
    """A stable similarity cluster of scored articles."""

    cluster_id: str
    articles: tuple[ScoredArticle, ...]

    @property
    def top_score(self) -> int:
        return max((item.score for item in self.articles), default=0)


def _words(text: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z0-9]+", text.casefold()))


def score_article(article: Article) -> ScoredArticle:
    """Apply the archived deterministic urgency heuristic with a fixed 15-point CI."""

    signals = tuple(sorted(_words(f"{article.title} {article.body}") & _URGENCY_TERMS))
    score = min(20 + 12 * len(signals), 85)
    return ScoredArticle(
        article=article,
        score=score,
        confidence_low=max(0, score - 15),
        confidence_high=min(100, score + 15),
        signals=signals,
    )


def score_articles(articles: list[Article]) -> list[ScoredArticle]:
    """Score articles in input order without network, provider, or persistence effects."""

    return [score_article(article) for article in articles]


def url_fingerprint(url: str) -> str:
    """Normalize a URL for deterministic in-memory duplicate comparison."""

    parsed = urlparse(url)
    query = urlencode(
        sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not _TRACKING_PARAMETER.match(key)
        )
    )
    return urlunparse(
        (
            parsed.scheme.casefold(),
            parsed.netloc.casefold(),
            parsed.path.rstrip("/"),
            "",
            query,
            "",
        )
    )


def deduplicate_scored(items: list[ScoredArticle]) -> list[ScoredArticle]:
    """Keep the highest-scored normalized URL, with first-seen ties and order."""

    kept: list[ScoredArticle] = []
    positions: dict[str, int] = {}
    for item in items:
        fingerprint = url_fingerprint(item.article.url)
        if fingerprint not in positions:
            positions[fingerprint] = len(kept)
            kept.append(item)
            continue
        position = positions[fingerprint]
        if item.score > kept[position].score:
            kept[position] = item
    return kept


def article_tokens(article: Article) -> frozenset[str]:
    """Return stopword-filtered title and bounded-body tokens for clustering."""

    words = re.findall(r"[a-z0-9]+", f"{article.title} {article.body[:300]}".casefold())
    return frozenset(word for word in words if len(word) > 2 and word not in _STOPWORDS)


def jaccard_similarity(first: Article, second: Article) -> float:
    """Return Jaccard similarity for the canonical Article text surface."""

    first_tokens = article_tokens(first)
    second_tokens = article_tokens(second)
    union = first_tokens | second_tokens
    if not union:
        return 0.0
    return len(first_tokens & second_tokens) / len(union)


def cluster_scored_articles(
    items: list[ScoredArticle],
    similarity_threshold: float = 0.5,
) -> list[ArticleCluster]:
    """Deduplicate and greedily assign stable similarity clusters."""

    if not 0.0 <= similarity_threshold <= 1.0:
        raise ValueError("similarity_threshold must be between 0 and 1")

    unique = deduplicate_scored(items)
    assigned = [False] * len(unique)
    clusters: list[ArticleCluster] = []
    for index, seed in enumerate(unique):
        if assigned[index]:
            continue
        members = [seed]
        assigned[index] = True
        for candidate_index in range(index + 1, len(unique)):
            if assigned[candidate_index]:
                continue
            candidate = unique[candidate_index]
            if (
                jaccard_similarity(seed.article, candidate.article)
                >= similarity_threshold
            ):
                members.append(candidate)
                assigned[candidate_index] = True
        clusters.append(
            ArticleCluster(
                cluster_id=f"c{len(clusters) + 1}",
                articles=tuple(members),
            )
        )
    return clusters


def analyze_articles(
    articles: list[Article],
    similarity_threshold: float = 0.5,
) -> list[ArticleCluster]:
    """Run the admitted pure scoring → deduplication → clustering path."""

    return cluster_scored_articles(
        score_articles(articles), similarity_threshold=similarity_threshold
    )


def generate_digest(clusters: list[ArticleCluster]) -> str:
    """Render score-ranked clusters as deterministic inspectable Markdown."""

    lines = ["# Situation Monitor Digest", ""]
    ordered_clusters = [
        cluster
        for _position, cluster in sorted(
            enumerate(clusters),
            key=lambda pair: (-pair[1].top_score, pair[0]),
        )
    ]
    for cluster in ordered_clusters:
        lines.extend((f"## Cluster {cluster.cluster_id}", ""))
        ordered_articles = sorted(
            cluster.articles,
            key=lambda item: (
                -item.score,
                item.article.source.casefold(),
                item.article.title.casefold(),
                item.article.url,
            ),
        )
        for item in ordered_articles:
            article = item.article
            lines.append(
                f"- [{article.title}]({article.url}) — {article.source} | "
                f"score {item.score} CI [{item.confidence_low}-{item.confidence_high}]"
            )
            if article.body:
                lines.append(f"  {article.body[:200].replace(chr(10), ' ')}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_digest(
    articles: list[Article],
    similarity_threshold: float = 0.5,
) -> str:
    """Run the complete deterministic post-ingestion Article analysis path."""

    return generate_digest(
        analyze_articles(articles, similarity_threshold=similarity_threshold)
    )

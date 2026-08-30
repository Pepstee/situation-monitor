"""Canonical local SQLite state for Situation Monitor Articles and run receipts."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterator

from monitor.analysis import (
    ArticleCluster,
    ScoredArticle,
    rank_clusters_for_digest,
    url_fingerprint,
)
from schemas import Article, SourceReliability


SCHEMA_VERSION = 1
_DDL = f"""
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS articles (
    fingerprint      TEXT PRIMARY KEY,
    url              TEXT NOT NULL,
    title            TEXT NOT NULL,
    source           TEXT NOT NULL,
    body             TEXT NOT NULL DEFAULT '',
    published_at     TEXT,
    reliability      TEXT NOT NULL,
    tags_json        TEXT NOT NULL DEFAULT '[]',
    score            INTEGER,
    confidence_low   INTEGER,
    confidence_high  INTEGER,
    signals_json     TEXT NOT NULL DEFAULT '[]',
    cluster_id       TEXT,
    digest_rank      INTEGER,
    seen_at          REAL NOT NULL,
    CHECK (score IS NULL OR score BETWEEN 0 AND 100),
    CHECK (confidence_low IS NULL OR confidence_low BETWEEN 0 AND 100),
    CHECK (confidence_high IS NULL OR confidence_high BETWEEN 0 AND 100)
);

CREATE INDEX IF NOT EXISTS idx_articles_seen_at ON articles (seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles (source);

CREATE TABLE IF NOT EXISTS ingest_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    started_at   REAL NOT NULL,
    finished_at  REAL NOT NULL,
    item_count   INTEGER NOT NULL DEFAULT 0,
    error        TEXT
);

CREATE INDEX IF NOT EXISTS idx_ingest_runs_source_finished
    ON ingest_runs (source, finished_at DESC);

CREATE TABLE IF NOT EXISTS source_reliability (
    source            TEXT PRIMARY KEY,
    run_count         INTEGER NOT NULL DEFAULT 0,
    success_count     INTEGER NOT NULL DEFAULT 0,
    mean_latency_ms   REAL NOT NULL DEFAULT 0.0,
    last_updated      REAL NOT NULL
);

PRAGMA user_version = {SCHEMA_VERSION};
"""


@dataclass(frozen=True)
class StoredArticle:
    """Canonical Article plus its optional persisted analysis metadata."""

    article: Article
    scored: ScoredArticle | None
    cluster_id: str | None
    digest_rank: int | None
    seen_at: float


@dataclass(frozen=True)
class RunRecord:
    """An immutable local receipt for one completed source run."""

    run_id: int
    source: str
    started_at: float
    finished_at: float
    item_count: int
    error: str | None


@dataclass(frozen=True)
class ReliabilityStats:
    """Run-derived reliability and latency state for one source."""

    source: str
    run_count: int
    success_count: int
    mean_latency_ms: float
    average_score: float
    last_updated: float

    @property
    def hit_rate(self) -> float:
        return self.success_count / self.run_count


class StateStore:
    """Explicit-lifecycle SQLite owner with no import-time or default-path effects."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        self._conn: sqlite3.Connection | None = None

    def open(self) -> None:
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")

    def init_schema(self) -> None:
        self.open()
        self.conn.executescript(_DDL)
        self.conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> StateStore:
        self.init_schema()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("StateStore is not open")
        return self._conn

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.conn.cursor()
        try:
            yield cursor
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cursor.close()

    def save_article(self, article: Article, *, seen_at: float | None = None) -> None:
        """Upsert one unscored canonical Article."""

        observed_at = time.time() if seen_at is None else seen_at
        with self._transaction() as cursor:
            self._upsert_article(cursor, article, None, None, None, observed_at)

    def save_clusters(
        self,
        clusters: list[ArticleCluster],
        *,
        seen_at: float | None = None,
    ) -> int:
        """Persist a complete deterministic analysis result in one transaction."""

        observed_at = time.time() if seen_at is None else seen_at
        saved = 0
        digest_rank = 0
        with self._transaction() as cursor:
            for cluster in rank_clusters_for_digest(clusters):
                for item in cluster.articles:
                    digest_rank += 1
                    self._upsert_article(
                        cursor,
                        item.article,
                        item,
                        cluster.cluster_id,
                        digest_rank,
                        observed_at,
                    )
                    saved += 1
        return saved

    @staticmethod
    def _upsert_article(
        cursor: sqlite3.Cursor,
        article: Article,
        scored: ScoredArticle | None,
        cluster_id: str | None,
        digest_rank: int | None,
        seen_at: float,
    ) -> None:
        cursor.execute(
            """
            INSERT INTO articles (
                fingerprint, url, title, source, body, published_at, reliability,
                tags_json, score, confidence_low, confidence_high, signals_json,
                cluster_id, digest_rank, seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                url = excluded.url,
                title = excluded.title,
                source = excluded.source,
                body = excluded.body,
                published_at = excluded.published_at,
                reliability = excluded.reliability,
                tags_json = excluded.tags_json,
                score = excluded.score,
                confidence_low = excluded.confidence_low,
                confidence_high = excluded.confidence_high,
                signals_json = excluded.signals_json,
                cluster_id = excluded.cluster_id,
                digest_rank = excluded.digest_rank,
                seen_at = excluded.seen_at
            """,
            (
                url_fingerprint(article.url),
                article.url,
                article.title,
                article.source,
                article.body,
                article.published_at.isoformat() if article.published_at else None,
                article.reliability.value,
                json.dumps(article.tags, ensure_ascii=False, separators=(",", ":")),
                scored.score if scored else None,
                scored.confidence_low if scored else None,
                scored.confidence_high if scored else None,
                json.dumps(
                    scored.signals if scored else (),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                cluster_id,
                digest_rank,
                seen_at,
            ),
        )

    def recent_articles(
        self,
        window_hours: float,
        *,
        now: float | None = None,
    ) -> list[StoredArticle]:
        """Reconstruct canonical Articles seen inside a deterministic time window."""

        rows = self._recent_rows(window_hours, now=now)
        return [self._stored_article(row) for row in rows]

    def recent_fingerprints(
        self,
        window_hours: float,
        *,
        now: float | None = None,
    ) -> set[str]:
        """Return normalized URLs seen inside the requested time window."""

        return {row["fingerprint"] for row in self._recent_rows(window_hours, now=now)}

    def filter_unseen(
        self,
        articles: list[Article],
        window_hours: float = 24.0,
        *,
        now: float | None = None,
    ) -> list[Article]:
        """Filter persisted and same-batch duplicates without writing state."""

        seen = self.recent_fingerprints(window_hours, now=now)
        surviving: list[Article] = []
        for article in articles:
            fingerprint = url_fingerprint(article.url)
            if fingerprint in seen:
                continue
            seen.add(fingerprint)
            surviving.append(article)
        return surviving

    def _recent_rows(
        self,
        window_hours: float,
        *,
        now: float | None,
    ) -> list[sqlite3.Row]:
        if window_hours < 0:
            raise ValueError("window_hours must not be negative")
        current_time = time.time() if now is None else now
        cutoff = current_time - window_hours * 3600
        return self.conn.execute(
            "SELECT * FROM articles WHERE seen_at >= ? "
            "ORDER BY seen_at DESC, fingerprint",
            (cutoff,),
        ).fetchall()

    @staticmethod
    def _stored_article(row: sqlite3.Row) -> StoredArticle:
        published_at = (
            datetime.fromisoformat(row["published_at"])
            if row["published_at"] is not None
            else None
        )
        article = Article(
            url=row["url"],
            title=row["title"],
            source=row["source"],
            body=row["body"],
            published_at=published_at,
            reliability=SourceReliability(row["reliability"]),
            tags=json.loads(row["tags_json"]),
        )
        scored = None
        if row["score"] is not None:
            scored = ScoredArticle(
                article=article,
                score=row["score"],
                confidence_low=row["confidence_low"],
                confidence_high=row["confidence_high"],
                signals=tuple(json.loads(row["signals_json"])),
            )
        return StoredArticle(
            article=article,
            scored=scored,
            cluster_id=row["cluster_id"],
            digest_rank=row["digest_rank"],
            seen_at=row["seen_at"],
        )

    def record_run(
        self,
        source: str,
        started_at: float,
        finished_at: float,
        *,
        item_count: int = 0,
        error: str | None = None,
    ) -> int:
        """Persist a run receipt and update its source reliability atomically."""

        if not source.strip():
            raise ValueError("source must not be empty")
        if finished_at < started_at:
            raise ValueError("finished_at must not precede started_at")
        if item_count < 0:
            raise ValueError("item_count must not be negative")

        latency_ms = (finished_at - started_at) * 1000
        success = int(error is None)
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO ingest_runs "
                "(source, started_at, finished_at, item_count, error) "
                "VALUES (?, ?, ?, ?, ?)",
                (source, started_at, finished_at, item_count, error),
            )
            run_id = cursor.lastrowid
            cursor.execute(
                """
                INSERT INTO source_reliability (
                    source, run_count, success_count, mean_latency_ms, last_updated
                ) VALUES (?, 1, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    run_count = source_reliability.run_count + 1,
                    success_count = source_reliability.success_count
                        + excluded.success_count,
                    mean_latency_ms = (
                        source_reliability.mean_latency_ms
                        * source_reliability.run_count
                        + excluded.mean_latency_ms
                    ) / (source_reliability.run_count + 1),
                    last_updated = MAX(
                        source_reliability.last_updated,
                        excluded.last_updated
                    )
                """,
                (source, success, latency_ms, finished_at),
            )
        assert run_id is not None
        return run_id

    def list_runs(self, source: str | None = None) -> list[RunRecord]:
        """Return immutable run receipts newest-first."""

        query = (
            "SELECT id, source, started_at, finished_at, item_count, error "
            "FROM ingest_runs"
        )
        parameters: tuple[object, ...] = ()
        if source is not None:
            query += " WHERE source = ?"
            parameters = (source,)
        query += " ORDER BY finished_at DESC, id DESC"
        return [
            RunRecord(
                run_id=row["id"],
                source=row["source"],
                started_at=row["started_at"],
                finished_at=row["finished_at"],
                item_count=row["item_count"],
                error=row["error"],
            )
            for row in self.conn.execute(query, parameters).fetchall()
        ]

    def reliability(self, source: str) -> ReliabilityStats | None:
        """Return run-derived reliability for one source, if recorded."""

        row = self._reliability_rows(source)
        return self._reliability_stats(row[0]) if row else None

    def all_reliability(self) -> list[ReliabilityStats]:
        """Return all source reliability state in stable source order."""

        return [self._reliability_stats(row) for row in self._reliability_rows()]

    def hit_rate(self, source: str) -> float | None:
        """Expose the orphan reliability tracker's hit-rate contract."""

        stats = self.reliability(source)
        return stats.hit_rate if stats else None

    def all_hit_rates(self) -> dict[str, float]:
        """Return stable source-to-success-rate state."""

        return {stats.source: stats.hit_rate for stats in self.all_reliability()}

    def _reliability_rows(self, source: str | None = None) -> list[sqlite3.Row]:
        query = """
            SELECT
                sr.source,
                sr.run_count,
                sr.success_count,
                sr.mean_latency_ms,
                COALESCE(AVG(a.score), 0.0) AS average_score,
                sr.last_updated
            FROM source_reliability sr
            LEFT JOIN articles a ON a.source = sr.source
        """
        parameters: tuple[object, ...] = ()
        if source is not None:
            query += " WHERE sr.source = ?"
            parameters = (source,)
        query += " GROUP BY sr.source ORDER BY sr.source"
        return self.conn.execute(query, parameters).fetchall()

    @staticmethod
    def _reliability_stats(row: sqlite3.Row) -> ReliabilityStats:
        return ReliabilityStats(
            source=row["source"],
            run_count=row["run_count"],
            success_count=row["success_count"],
            mean_latency_ms=row["mean_latency_ms"],
            average_score=row["average_score"],
            last_updated=row["last_updated"],
        )

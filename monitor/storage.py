"""Canonical local SQLite state for Articles, source registry, and run receipts."""

from __future__ import annotations

import json
import sqlite3
import tempfile
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


SCHEMA_VERSION = 5
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
    metadata_json    TEXT NOT NULL DEFAULT '{{}}',
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

CREATE TABLE IF NOT EXISTS sources (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL UNIQUE,
    fixture_source  TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT 'feed',
    target          TEXT NOT NULL DEFAULT '',
    tags            TEXT NOT NULL DEFAULT '',
    interval_s      INTEGER NOT NULL CHECK (interval_s > 0),
    enabled         INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_sources_enabled_name
    ON sources (enabled, name);

CREATE TABLE IF NOT EXISTS source_reliability (
    source            TEXT PRIMARY KEY,
    run_count         INTEGER NOT NULL DEFAULT 0,
    success_count     INTEGER NOT NULL DEFAULT 0,
    mean_latency_ms   REAL NOT NULL DEFAULT 0.0,
    last_updated      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_name    TEXT NOT NULL,
    threshold    INTEGER NOT NULL CHECK (threshold BETWEEN 0 AND 100),
    severity     TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    fingerprint  TEXT NOT NULL REFERENCES articles(fingerprint),
    url          TEXT NOT NULL,
    title        TEXT NOT NULL,
    source       TEXT NOT NULL,
    score        INTEGER NOT NULL CHECK (score BETWEEN 0 AND 100),
    fired_at     REAL NOT NULL,
    resolved     INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1)),
    UNIQUE (rule_name, fingerprint)
);

CREATE INDEX IF NOT EXISTS idx_alert_events_open_fired
    ON alert_events (resolved, fired_at DESC, id DESC);

-- Stored conditions and their manually recorded events share the source registry.
-- They are metadata, not article threshold alerts and not executable expressions.
CREATE TABLE IF NOT EXISTS condition_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    name TEXT NOT NULL,
    condition TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('info', 'warning', 'critical')),
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1))
);
CREATE TABLE IF NOT EXISTS condition_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    check_id INTEGER NOT NULL REFERENCES condition_checks(id),
    fired_at TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    resolved INTEGER NOT NULL DEFAULT 0 CHECK (resolved IN (0, 1))
);
CREATE INDEX IF NOT EXISTS idx_condition_events_check ON condition_events (check_id);
CREATE INDEX IF NOT EXISTS idx_condition_events_fired ON condition_events (fired_at DESC);
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
class RegisteredSource:
    """A feed or metadata-only target in the single canonical source registry."""

    source_id: int
    name: str
    fixture_source: str
    interval_s: int
    enabled: bool
    kind: str = "feed"
    target: str = ""
    tags: str = ""


@dataclass(frozen=True)
class ConditionCheck:
    check_id: int
    source_id: int
    name: str
    condition: str
    severity: str
    enabled: bool


@dataclass(frozen=True)
class ConditionEvent:
    event_id: int
    check_id: int
    fired_at: str
    detail: str
    resolved: bool


@dataclass(frozen=True)
class DueSource:
    """A source whose first or next persisted check is due."""

    source: RegisteredSource
    last_finished_at: float | None
    due_at: float


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


@dataclass(frozen=True)
class AlertEvent:
    """One immutable local threshold-rule firing for a persisted article."""

    alert_id: int
    rule_name: str
    threshold: int
    severity: str
    fingerprint: str
    url: str
    title: str
    source: str
    score: int
    fired_at: float
    resolved: bool


class StateStore:
    """Explicit-lifecycle SQLite owner with no import-time or default-path effects."""

    def __init__(self, path: str | Path, *, read_only: bool = False) -> None:
        self._path = str(path)
        self._read_only = read_only
        self._conn: sqlite3.Connection | None = None
        self._snapshot_directory: tempfile.TemporaryDirectory[str] | None = None

    @staticmethod
    def _snapshot_identity(path: Path) -> tuple[int, int, int, int]:
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def _private_immutable_snapshot(self, database_path: Path) -> Path:
        before = self._snapshot_identity(database_path)
        first = database_path.read_bytes()
        middle = self._snapshot_identity(database_path)
        second = database_path.read_bytes()
        after = self._snapshot_identity(database_path)
        if before != middle or middle != after or first != second:
            raise RuntimeError("read-only StateStore source changed during snapshot")
        if (
            Path(f"{database_path}-wal").exists()
            or Path(f"{database_path}-shm").exists()
        ):
            raise RuntimeError("read-only StateStore source changed during snapshot")
        self._snapshot_directory = tempfile.TemporaryDirectory(
            prefix="situation-monitor-dashboard-"
        )
        snapshot = Path(self._snapshot_directory.name) / "state.sqlite3"
        snapshot.write_bytes(first)
        snapshot.chmod(0o600)
        return snapshot

    def open(self) -> None:
        if self._conn is not None:
            return
        if self._read_only:
            database_path = Path(self._path).absolute()
            wal_path = Path(f"{database_path}-wal")
            shm_path = Path(f"{database_path}-shm")
            if wal_path.exists() != shm_path.exists():
                raise RuntimeError(
                    "read-only StateStore refuses an incomplete WAL sidecar set"
                )
            if wal_path.exists():
                database = f"{database_path.as_uri()}?mode=ro"
            else:
                snapshot = self._private_immutable_snapshot(database_path)
                database = f"{snapshot.as_uri()}?mode=ro&immutable=1"
        else:
            database = self._path
        self._conn = sqlite3.connect(
            database,
            check_same_thread=False,
            uri=self._read_only,
        )
        self._conn.row_factory = sqlite3.Row
        if self._read_only:
            self._conn.execute("PRAGMA query_only = ON")
        self._conn.execute("PRAGMA foreign_keys = ON")

    def init_schema(self) -> None:
        if self._read_only:
            raise RuntimeError("read-only StateStore cannot initialize schema")
        self.open()
        version = self.conn.execute("PRAGMA user_version").fetchone()[0]
        tables = {row[0] for row in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table'") if not row[0].startswith("sqlite_")}
        for table, required in {"articles": {"fingerprint", "tags_json", "seen_at"},
                                "sources": {"fixture_source", "interval_s"},
                                "source_reliability": {"last_updated", "mean_latency_ms"}}.items():
            if tables and (table not in tables or not required <= {row[1] for row in self.conn.execute(f"PRAGMA table_info({table})")}):
                raise RuntimeError("incompatible prototype database; preserve it separately and select canonical state")
        if version > SCHEMA_VERSION:
            raise RuntimeError("database schema is newer than this application")
        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(articles)")}
        if columns and "metadata_json" not in columns:
            with self.conn:
                self.conn.execute("ALTER TABLE articles ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
        source_columns = {row[1] for row in self.conn.execute("PRAGMA table_info(sources)")}
        if source_columns:
            with self.conn:
                for column, default in (("kind", "feed"), ("target", ""), ("tags", "")):
                    if column not in source_columns:
                        self.conn.execute(f"ALTER TABLE sources ADD COLUMN {column} TEXT NOT NULL DEFAULT '{default}'")
        self.conn.executescript(_DDL)
        self.conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._snapshot_directory is not None:
            self._snapshot_directory.cleanup()
            self._snapshot_directory = None

    def __enter__(self) -> StateStore:
        if self._read_only:
            self.open()
        else:
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

    def register_source(
        self,
        name: str,
        fixture_source: str,
        interval_s: int,
        *,
        enabled: bool = True,
    ) -> int:
        """Register or update one source without creating a parallel state owner."""

        source_name = name.strip()
        fixture_name = fixture_source.strip()
        if not source_name:
            raise ValueError("source name must not be empty")
        if not fixture_name:
            raise ValueError("fixture_source must not be empty")
        if interval_s <= 0:
            raise ValueError("interval_s must be positive")
        existing = self.conn.execute("SELECT kind FROM sources WHERE name = ?", (source_name,)).fetchone()
        if existing is not None and existing["kind"] != "feed":
            raise ValueError("source name belongs to a metadata-only target")
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO sources (name, fixture_source, interval_s, enabled)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    fixture_source = excluded.fixture_source,
                    interval_s = excluded.interval_s,
                    enabled = excluded.enabled
                """,
                (source_name, fixture_name, interval_s, int(enabled)),
            )
            row = cursor.execute(
                "SELECT id FROM sources WHERE name = ?", (source_name,)
            ).fetchone()
        assert row is not None
        return int(row["id"])

    def list_sources(self, *, enabled_only: bool = False) -> list[RegisteredSource]:
        """Return the source registry in stable name order."""

        columns = {row[1] for row in self.conn.execute("PRAGMA table_info(sources)")}
        metadata = "kind, target, tags" if "kind" in columns else "'feed' AS kind, '' AS target, '' AS tags"
        query = f"SELECT id, name, fixture_source, interval_s, enabled, {metadata} FROM sources"
        if enabled_only:
            query += " WHERE enabled = 1"
        query += " ORDER BY name"
        return [
            RegisteredSource(
                source_id=row["id"],
                name=row["name"],
                fixture_source=row["fixture_source"],
                interval_s=row["interval_s"],
                enabled=bool(row["enabled"]),
                kind=row["kind"], target=row["target"], tags=row["tags"],
            )
            for row in self.conn.execute(query).fetchall()
        ]

    def add_source(self, name: str, kind: str, target: str, interval_s: int = 60,
                   *, enabled: bool = True, tags: str = "") -> int:
        """Retain an archived http/file/cmd definition without executing its target."""
        if kind not in {"http", "file", "cmd"}:
            raise ValueError("source kind must be http, file or cmd")
        if not name.strip() or not target.strip() or interval_s <= 0:
            raise ValueError("source name/target must be non-empty and interval positive")
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO sources (name, fixture_source, interval_s, enabled, kind, target, tags) VALUES (?, '', ?, ?, ?, ?, ?)",
                (name.strip(), interval_s, int(enabled), kind, target, tags),
            )
            return int(cursor.lastrowid)

    def add_check(self, source_id: int, name: str, condition: str, severity: str = "warning",
                  *, enabled: bool = True) -> int:
        """Store a condition as text. No condition evaluator is implied."""
        if not name.strip() or not condition.strip():
            raise ValueError("check name and condition must not be empty")
        if severity not in {"info", "warning", "critical"}:
            raise ValueError("invalid check severity")
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO condition_checks (source_id, name, condition, severity, enabled) VALUES (?, ?, ?, ?, ?)",
                (source_id, name, condition, severity, int(enabled)),
            )
            return int(cursor.lastrowid)

    def list_checks(self, source_id: int | None = None) -> list[ConditionCheck]:
        query = "SELECT * FROM condition_checks"
        parameters = ()
        if source_id is not None:
            query += " WHERE source_id = ?"
            parameters = (source_id,)
        return [ConditionCheck(row["id"], row["source_id"], row["name"], row["condition"],
                               row["severity"], bool(row["enabled"]))
                for row in self.conn.execute(query + " ORDER BY id", parameters)]

    def record_event(self, check_id: int, fired_at: str, detail: str = "", *, resolved: bool = False) -> int:
        """Record a supplied condition event, independently of article alert firing."""
        datetime.fromisoformat(fired_at.replace("Z", "+00:00"))
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO condition_events (check_id, fired_at, detail, resolved) VALUES (?, ?, ?, ?)",
                (check_id, fired_at, detail, int(resolved)),
            )
            return int(cursor.lastrowid)

    def list_events(self, check_id: int | None = None, *, unresolved_only: bool = False,
                    limit: int = 100) -> list[ConditionEvent]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        clauses, parameters = [], []
        if check_id is not None:
            clauses.append("check_id = ?")
            parameters.append(check_id)
        if unresolved_only:
            clauses.append("resolved = 0")
        query = "SELECT * FROM condition_events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        parameters.append(limit)
        return [ConditionEvent(row["id"], row["check_id"], row["fired_at"], row["detail"], bool(row["resolved"]))
                for row in self.conn.execute(query + " ORDER BY fired_at DESC, id DESC LIMIT ?", parameters)]

    def resolve_event(self, event_id: int) -> bool:
        with self._transaction() as cursor:
            cursor.execute("UPDATE condition_events SET resolved = 1 WHERE id = ? AND resolved = 0", (event_id,))
            return cursor.rowcount == 1

    def due_sources(self, *, now: float) -> list[DueSource]:
        """Return enabled sources due at ``now`` from completed run state."""

        rows = self.conn.execute(
            """
            SELECT
                s.id,
                s.name,
                s.fixture_source,
                s.interval_s,
                s.enabled,
                MAX(ir.finished_at) AS last_finished_at
            FROM sources s
            LEFT JOIN ingest_runs ir ON ir.source = s.name
            WHERE s.enabled = 1 AND s.fixture_source IN ('hackernews', 'github_trending', 'rss')
            GROUP BY s.id
            HAVING last_finished_at IS NULL
                OR last_finished_at + s.interval_s <= ?
            ORDER BY s.name
            """,
            (now,),
        ).fetchall()
        due: list[DueSource] = []
        for row in rows:
            source = RegisteredSource(
                source_id=row["id"],
                name=row["name"],
                fixture_source=row["fixture_source"],
                interval_s=row["interval_s"],
                enabled=bool(row["enabled"]),
            )
            last_finished_at = row["last_finished_at"]
            due.append(
                DueSource(
                    source=source,
                    last_finished_at=last_finished_at,
                    due_at=(
                        now
                        if last_finished_at is None
                        else last_finished_at + source.interval_s
                    ),
                )
            )
        return due

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
                cluster_id, digest_rank, seen_at, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fingerprint) DO UPDATE SET
                url = excluded.url,
                title = excluded.title,
                source = excluded.source,
                body = excluded.body,
                published_at = excluded.published_at,
                reliability = excluded.reliability,
                tags_json = excluded.tags_json,
                metadata_json = excluded.metadata_json,
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
                json.dumps(article.metadata, ensure_ascii=False, allow_nan=False, separators=(",", ":")),
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
        scored_only: bool = False,
    ) -> list[Article]:
        """Filter persisted and same-batch duplicates without writing state."""

        seen = ({row["fingerprint"] for row in self._recent_rows(window_hours, now=now) if row["score"] is not None}
                if scored_only else self.recent_fingerprints(window_hours, now=now))
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
            metadata=json.loads(row["metadata_json"]) if "metadata_json" in row.keys() else {},
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

        with self._transaction() as cursor:
            run_id = self._insert_run(
                cursor,
                source,
                started_at,
                finished_at,
                item_count=item_count,
                error=error,
            )
        assert run_id is not None
        return run_id

    def record_source_check(
        self,
        source: str,
        checked_at: float,
        *,
        articles: list[Article] | None = None,
        error: str | None = None,
        finished_at: float | None = None,
    ) -> int:
        """Atomically persist one deterministic fixture check and its Articles."""

        ended_at = checked_at if finished_at is None else finished_at
        if ended_at < checked_at:
            raise ValueError("source completion cannot precede its start")
        checked_articles = articles or []
        if error is not None and checked_articles:
            raise ValueError("failed source checks cannot persist articles")
        with self._transaction() as cursor:
            for article in checked_articles:
                self._upsert_article(cursor, article, None, None, None, checked_at)
            return self._insert_run(
                cursor,
                source,
                checked_at,
                ended_at,
                item_count=len(checked_articles),
                error=error,
            )

    @staticmethod
    def _insert_run(
        cursor: sqlite3.Cursor,
        source: str,
        started_at: float,
        finished_at: float,
        *,
        item_count: int,
        error: str | None,
    ) -> int:
        latency_ms = (finished_at - started_at) * 1000
        success = int(error is None)
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

    def evaluate_alert_rule(
        self,
        rule_name: str,
        threshold: int,
        *,
        severity: str = "warning",
        fired_at: float | None = None,
    ) -> list[AlertEvent]:
        """Persist newly fired alerts for scored articles meeting an inclusive rule."""

        normalized_rule = rule_name.strip()
        if not normalized_rule:
            raise ValueError("rule_name must not be empty")
        if isinstance(threshold, bool) or not 0 <= threshold <= 100:
            raise ValueError("threshold must be between 0 and 100")
        if severity not in {"info", "warning", "critical"}:
            raise ValueError("severity must be info, warning, or critical")
        observed_at = time.time() if fired_at is None else fired_at
        created: list[AlertEvent] = []
        with self._transaction() as cursor:
            candidates = cursor.execute(
                "SELECT fingerprint, url, title, source, score FROM articles "
                "WHERE score >= ? ORDER BY score DESC, fingerprint",
                (threshold,),
            ).fetchall()
            for row in candidates:
                cursor.execute(
                    """
                    INSERT INTO alert_events (
                        rule_name, threshold, severity, fingerprint, url, title,
                        source, score, fired_at, resolved
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(rule_name, fingerprint) DO NOTHING
                    """,
                    (
                        normalized_rule,
                        threshold,
                        severity,
                        row["fingerprint"],
                        row["url"],
                        row["title"],
                        row["source"],
                        row["score"],
                        observed_at,
                    ),
                )
                if cursor.rowcount == 0:
                    continue
                assert cursor.lastrowid is not None
                created.append(
                    AlertEvent(
                        alert_id=cursor.lastrowid,
                        rule_name=normalized_rule,
                        threshold=threshold,
                        severity=severity,
                        fingerprint=row["fingerprint"],
                        url=row["url"],
                        title=row["title"],
                        source=row["source"],
                        score=row["score"],
                        fired_at=observed_at,
                        resolved=False,
                    )
                )
        return created

    def list_alert_events(
        self,
        *,
        unresolved_only: bool = False,
        limit: int = 100,
    ) -> list[AlertEvent]:
        """Return persisted alert events newest-first with an optional open filter."""

        if limit <= 0:
            raise ValueError("limit must be positive")
        query = (
            "SELECT id, rule_name, threshold, severity, fingerprint, url, title, "
            "source, score, fired_at, resolved FROM alert_events"
        )
        if unresolved_only:
            query += " WHERE resolved = 0"
        query += " ORDER BY fired_at DESC, id DESC LIMIT ?"
        return [
            self._alert_event(row)
            for row in self.conn.execute(query, (limit,)).fetchall()
        ]

    def alert_event_counts(self) -> tuple[int, int]:
        """Return total and unresolved alert counts for a closed local snapshot."""

        row = self.conn.execute(
            "SELECT COUNT(*) AS total, "
            "COALESCE(SUM(CASE WHEN resolved = 0 THEN 1 ELSE 0 END), 0) "
            "AS unresolved FROM alert_events"
        ).fetchone()
        assert row is not None
        return int(row["total"]), int(row["unresolved"])

    def resolve_alert_event(self, alert_id: int) -> bool:
        """Resolve one alert event, returning whether a row existed."""

        if alert_id <= 0:
            raise ValueError("alert_id must be positive")
        with self._transaction() as cursor:
            cursor.execute(
                "UPDATE alert_events SET resolved = 1 WHERE id = ?",
                (alert_id,),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _alert_event(row: sqlite3.Row) -> AlertEvent:
        return AlertEvent(
            alert_id=row["id"],
            rule_name=row["rule_name"],
            threshold=row["threshold"],
            severity=row["severity"],
            fingerprint=row["fingerprint"],
            url=row["url"],
            title=row["title"],
            source=row["source"],
            score=row["score"],
            fired_at=row["fired_at"],
            resolved=bool(row["resolved"]),
        )

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

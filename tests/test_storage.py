"""Temp-state persistence tests adapted from every preserved donor lineage."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone

import pytest

from monitor.analysis import analyze_articles
from monitor.cli import main
from monitor.ingest import fetch_fixture_articles
from monitor.storage import SCHEMA_VERSION, StateStore
from schemas import Article, SourceReliability


def test_explicit_lifecycle_context_schema_and_pragmas(tmp_path):
    database_path = tmp_path / "state.sqlite3"
    store = StateStore(database_path)
    with pytest.raises(RuntimeError, match="not open"):
        _ = store.conn

    store.open()
    first_connection = store.conn
    store.open()
    assert store.conn is first_connection
    store.init_schema()
    store.init_schema()
    assert store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert store.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert store.conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    tables = {
        row[0]
        for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "alert_events",
        "articles",
        "ingest_runs",
        "source_reliability",
        "sources",
    }.issubset(tables)
    assert {"checks", "events"}.isdisjoint(tables)
    store.close()
    store.close()
    with pytest.raises(RuntimeError, match="not open"):
        _ = store.conn

    with StateStore(database_path) as reopened:
        assert reopened.conn is not None
    with pytest.raises(RuntimeError, match="not open"):
        _ = reopened.conn


def test_fixture_analysis_round_trips_canonical_types_across_reopen(tmp_path):
    database_path = tmp_path / "state.sqlite3"
    fixtures = fetch_fixture_articles("monitor/fixtures", ["rss"])
    clusters = analyze_articles(fixtures)

    with StateStore(database_path) as store:
        assert store.save_clusters(clusters, seen_at=1_000.0) == 5

    with StateStore(database_path) as store:
        stored = store.recent_articles(1, now=2_000.0)

    assert len(stored) == 5
    assert all(isinstance(item.article, Article) for item in stored)
    assert all(item.scored is not None for item in stored)
    assert all(item.cluster_id is not None for item in stored)
    assert {item.article.reliability for item in stored} == {SourceReliability.MEDIUM}
    assert all(item.article.published_at is not None for item in stored)
    assert sorted(item.digest_rank for item in stored) == [1, 2, 3, 4, 5]


def test_article_upsert_uses_normalized_url_identity_and_updates_state(tmp_path):
    database_path = tmp_path / "state.sqlite3"
    original = Article(
        url="HTTPS://Example.COM/story/?utm_source=one",
        title="Original",
        source="rss",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        tags=["first"],
    )
    updated = Article(
        url="https://example.com/story",
        title="Updated",
        source="rss",
        published_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        tags=["second"],
    )

    with StateStore(database_path) as store:
        store.save_article(original, seen_at=100.0)
        store.save_article(updated, seen_at=200.0)
        rows = store.recent_articles(1, now=300.0)

    assert len(rows) == 1
    assert rows[0].article == updated
    assert rows[0].scored is None
    assert rows[0].seen_at == 200.0


def test_time_window_dedup_filters_persisted_and_same_batch_variants(tmp_path):
    database_path = tmp_path / "state.sqlite3"
    recent = Article(url="https://example.com/recent", title="Recent", source="rss")
    old = Article(url="https://example.com/old", title="Old", source="rss")
    with StateStore(database_path) as store:
        store.save_article(recent, seen_at=9_900.0)
        store.save_article(old, seen_at=1_000.0)
        incoming = [
            Article(
                url="https://example.com/recent?utm_medium=email",
                title="Recent duplicate",
                source="rss",
            ),
            Article(url="https://example.com/old", title="Old again", source="rss"),
            Article(url="https://example.com/new", title="First new", source="rss"),
            Article(
                url="https://example.com/new/?utm_source=hn",
                title="Second new",
                source="rss",
            ),
        ]
        surviving = store.filter_unseen(incoming, window_hours=1, now=10_000.0)
        persisted_count = store.conn.execute(
            "SELECT COUNT(*) FROM articles"
        ).fetchone()[0]

    assert [item.title for item in surviving] == ["Old again", "First new"]
    assert persisted_count == 2


def test_invalid_window_and_run_inputs_fail_without_partial_rows(tmp_path):
    with StateStore(tmp_path / "state.sqlite3") as store:
        with pytest.raises(ValueError, match="window_hours"):
            store.recent_articles(-1, now=0)
        with pytest.raises(ValueError, match="source"):
            store.record_run(" ", 0.0, 1.0)
        with pytest.raises(ValueError, match="finished_at"):
            store.record_run("rss", 2.0, 1.0)
        with pytest.raises(ValueError, match="item_count"):
            store.record_run("rss", 0.0, 1.0, item_count=-1)
        assert store.list_runs() == []
        assert store.all_reliability() == []


def test_run_receipts_and_reliability_aggregate_and_persist(tmp_path):
    database_path = tmp_path / "state.sqlite3"
    with StateStore(database_path) as store:
        first_id = store.record_run("rss", 1_000.0, 1_000.1, item_count=5)
        second_id = store.record_run("rss", 2_000.0, 2_000.2, item_count=3)
        third_id = store.record_run(
            "rss", 3_000.0, 3_000.05, item_count=0, error="fixture failure"
        )
        store.record_run("github", 4_000.0, 4_000.4, item_count=2)

    with StateStore(database_path) as store:
        runs = store.list_runs("rss")
        reliability = store.reliability("rss")
        rates = store.all_hit_rates()
        unknown_rate = store.hit_rate("unknown")

    assert [record.run_id for record in runs] == [third_id, second_id, first_id]
    assert runs[0].error == "fixture failure"
    assert reliability is not None
    assert reliability.run_count == 3
    assert reliability.success_count == 2
    assert reliability.hit_rate == pytest.approx(2 / 3)
    assert reliability.mean_latency_ms == pytest.approx(116.666666, abs=0.01)
    assert reliability.last_updated == 3_000.05
    assert rates == {"github": 1.0, "rss": pytest.approx(2 / 3)}
    assert unknown_rate is None


def test_reliability_average_score_uses_persisted_canonical_analysis(tmp_path):
    fixtures = fetch_fixture_articles("monitor/fixtures", ["rss"])
    clusters = analyze_articles(fixtures)
    with StateStore(tmp_path / "state.sqlite3") as store:
        store.save_clusters(clusters, seen_at=100.0)
        store.record_run("Tech News Daily", 100.0, 100.2, item_count=5)
        reliability = store.reliability("Tech News Daily")

    assert reliability is not None
    assert reliability.average_score == 20.0


def test_sqlite_constraints_rollback_a_failed_cluster_transaction(tmp_path):
    fixtures = fetch_fixture_articles("monitor/fixtures", ["rss"])
    clusters = analyze_articles(fixtures)
    with StateStore(tmp_path / "state.sqlite3") as store:
        store.conn.execute(
            "CREATE TRIGGER reject_second BEFORE INSERT ON articles "
            "WHEN NEW.digest_rank = 2 BEGIN SELECT RAISE(ABORT, 'reject'); END"
        )
        store.conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="reject"):
            store.save_clusters(clusters, seen_at=100.0)
        count = store.conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]
    assert count == 0


def test_inclusive_alert_rule_persists_canonical_article_snapshots(tmp_path):
    fixtures = fetch_fixture_articles("monitor/fixtures", ["rss"])
    clusters = analyze_articles(fixtures)
    with StateStore(tmp_path / "state.sqlite3") as store:
        store.save_clusters(clusters, seen_at=1_000.0)
        created = store.evaluate_alert_rule(
            "high-score", 20, severity="critical", fired_at=1_001.0
        )
        below = store.evaluate_alert_rule("too-high", 21, fired_at=1_002.0)

    assert len(created) == 5
    assert below == []
    assert all(event.score == event.threshold == 20 for event in created)
    assert all(event.severity == "critical" for event in created)
    assert {event.title for event in created} == {article.title for article in fixtures}
    assert all(event.resolved is False for event in created)


def test_alert_rule_dedup_and_event_lifecycle_survive_reopen(tmp_path):
    database_path = tmp_path / "state.sqlite3"
    clusters = analyze_articles(fetch_fixture_articles("monitor/fixtures", ["rss"]))
    with StateStore(database_path) as store:
        store.save_clusters(clusters, seen_at=1_000.0)
        created = store.evaluate_alert_rule("high-score", 20, fired_at=1_001.0)
        first_id = created[0].alert_id

    with StateStore(database_path) as store:
        assert store.evaluate_alert_rule("high-score", 20, fired_at=2_000.0) == []
        assert store.resolve_alert_event(first_id) is True
        assert store.resolve_alert_event(999_999) is False
        all_events = store.list_alert_events(limit=3)
        open_events = store.list_alert_events(unresolved_only=True)

    assert len(all_events) == 3
    assert [event.alert_id for event in all_events] == sorted(
        (event.alert_id for event in all_events), reverse=True
    )
    assert len(open_events) == 4
    assert first_id not in {event.alert_id for event in open_events}


def test_alert_rule_and_event_inputs_fail_closed_without_rows(tmp_path):
    with StateStore(tmp_path / "state.sqlite3") as store:
        for rule, threshold, severity, message in (
            (" ", 20, "warning", "rule_name"),
            ("x", -1, "warning", "threshold"),
            ("x", 101, "warning", "threshold"),
            ("x", 20, "urgent", "severity"),
        ):
            with pytest.raises(ValueError, match=message):
                store.evaluate_alert_rule(rule, threshold, severity=severity)
        with pytest.raises(ValueError, match="limit"):
            store.list_alert_events(limit=0)
        with pytest.raises(ValueError, match="alert_id"):
            store.resolve_alert_event(0)
        assert store.list_alert_events() == []


def test_existing_fetch_and_digest_outputs_remain_byte_exact(capsys):
    assert main(["fetch", "--dry-run"]) == 0
    fetch_output = capsys.readouterr().out.encode()
    assert hashlib.sha256(fetch_output).hexdigest() == (
        "56e638279c60375416fc253c787dfec40ede1f96294de779ce18447451668029"
    )

    assert main(["fetch", "--dry-run", "--digest"]) == 0
    digest_output = capsys.readouterr().out.encode()
    assert hashlib.sha256(digest_output).hexdigest() == (
        "ee09ec2b6a35ca8c75401d3a97fd49ef4a8a61a08324cb15fb11772020f1a4dd"
    )


def test_schema_contains_no_external_effect_configuration(tmp_path):
    with StateStore(tmp_path / "state.sqlite3") as store:
        schema = "\n".join(
            row[0]
            for row in store.conn.execute(
                "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
            ).fetchall()
        ).casefold()
    assert all(
        forbidden not in schema
        for forbidden in (
            "http",
            "endpoint",
            "provider",
            "scheduler",
            "webhook",
            "email",
            "sms",
        )
    )

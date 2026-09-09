"""Fixture-only lifecycle tests adapted from all preserved scheduler lineages."""

from __future__ import annotations

import json
import socket
import sqlite3
import urllib.request

import pytest

from monitor.cli import main
from monitor.ingest import fetch_fixture_articles
from monitor.scheduler import run_due_source_checks
from monitor.storage import StateStore


def test_registry_is_stable_idempotent_and_validated(tmp_path):
    with StateStore(tmp_path / "state.sqlite3") as store:
        beta_id = store.register_source("beta", "rss", 120, enabled=False)
        alpha_id = store.register_source(" alpha ", "hackernews", 60)
        assert store.register_source("alpha", "github_trending", 90) == alpha_id

        assert [
            (source.name, source.fixture_source) for source in store.list_sources()
        ] == [
            ("alpha", "github_trending"),
            ("beta", "rss"),
        ]
        assert [
            source.source_id for source in store.list_sources(enabled_only=True)
        ] == [alpha_id]
        assert beta_id != alpha_id

        with pytest.raises(ValueError, match="source name"):
            store.register_source(" ", "rss", 60)
        with pytest.raises(ValueError, match="fixture_source"):
            store.register_source("rss", " ", 60)
        with pytest.raises(ValueError, match="interval_s"):
            store.register_source("rss", "rss", 0)


def test_first_check_is_due_and_completed_state_survives_restart(tmp_path):
    database_path = tmp_path / "state.sqlite3"
    with StateStore(database_path) as store:
        store.register_source("rss", "rss", 60)
        due = store.due_sources(now=1_000.0)
        assert [
            (item.source.name, item.last_finished_at, item.due_at) for item in due
        ] == [("rss", None, 1_000.0)]
        results = run_due_source_checks(
            store,
            lambda source: fetch_fixture_articles("monitor/fixtures", [source]),
            checked_at=1_000.0,
        )
        assert [
            (result.source, result.status, result.item_count) for result in results
        ] == [("rss", "succeeded", 5)]

    with StateStore(database_path) as reopened:
        assert reopened.due_sources(now=1_059.999) == []
        due = reopened.due_sources(now=1_060.0)
        assert [
            (item.source.name, item.last_finished_at, item.due_at) for item in due
        ] == [("rss", 1_000.0, 1_060.0)]
        assert len(reopened.recent_articles(1, now=1_001.0)) == 5
        assert reopened.list_runs("rss")[0].item_count == 5


def test_one_shot_records_failure_and_continues_in_stable_source_order(tmp_path):
    calls: list[str] = []

    def collect(source: str):
        calls.append(source)
        if source == "hackernews":
            raise RuntimeError("broken fixture")
        return fetch_fixture_articles("monitor/fixtures", [source])

    with StateStore(tmp_path / "state.sqlite3") as store:
        store.register_source("a-failing", "hackernews", 60)
        store.register_source("b-healthy", "rss", 60)
        results = run_due_source_checks(store, collect, checked_at=2_000.0)
        runs = store.list_runs()

    assert calls == ["hackernews", "rss"]
    assert [
        (result.source, result.status, result.item_count) for result in results
    ] == [
        ("a-failing", "failed", 0),
        ("b-healthy", "succeeded", 5),
    ]
    assert results[0].error == "RuntimeError: broken fixture"
    assert {run.source: run.error for run in runs} == {
        "a-failing": "RuntimeError: broken fixture",
        "b-healthy": None,
    }


def test_invalid_collector_output_is_recorded_as_failure(tmp_path):
    with StateStore(tmp_path / "state.sqlite3") as store:
        store.register_source("rss", "rss", 60)
        results = run_due_source_checks(store, lambda _source: None, checked_at=2_500.0)

    assert len(results) == 1
    assert results[0].status == "failed"
    assert results[0].error == "TypeError: fixture collector must return list[Article]"


def test_article_and_completed_check_receipt_commit_atomically(tmp_path):
    articles = fetch_fixture_articles("monitor/fixtures", ["rss"])
    with StateStore(tmp_path / "state.sqlite3") as store:
        store.conn.execute(
            "CREATE TRIGGER reject_article BEFORE INSERT ON articles "
            "BEGIN SELECT RAISE(ABORT, 'reject'); END"
        )
        store.conn.commit()
        with pytest.raises(sqlite3.IntegrityError, match="reject"):
            store.record_source_check("rss", 3_000.0, articles=articles)
        assert store.list_runs("rss") == []
        assert store.reliability("rss") is None


def test_fixture_tick_is_one_shot_offline_and_requires_explicit_state(
    tmp_path, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            f"network function called: args={args!r} kwargs={kwargs!r}"
        )

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    state_path = tmp_path / "state.sqlite3"

    assert (
        main(
            [
                "tick",
                "--state",
                str(state_path),
                "--at",
                "4000",
                "--source",
                "rss",
                "--interval-seconds",
                "60",
            ]
        )
        == 0
    )
    first = json.loads(capsys.readouterr().out)
    assert first == {
        "checked_at": 4000.0,
        "due_count": 1,
        "mode": "fixture-one-shot",
        "network_attempted": False,
        "results": [
            {
                "checked_at": 4000.0,
                "error": None,
                "fixture_source": "rss",
                "item_count": 5,
                "run_id": 1,
                "source": "rss",
                "status": "succeeded",
            }
        ],
    }

    assert (
        main(
            [
                "tick",
                "--state",
                str(state_path),
                "--at",
                "4059",
                "--source",
                "rss",
                "--interval-seconds",
                "60",
            ]
        )
        == 0
    )
    second = json.loads(capsys.readouterr().out)
    assert second["due_count"] == 0
    assert second["results"] == []


def test_fixture_tick_missing_fixture_persists_failure_and_returns_one(
    tmp_path, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            f"network function called: args={args!r} kwargs={kwargs!r}"
        )

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    state_path = tmp_path / "state.sqlite3"

    assert (
        main(
            [
                "tick",
                "--state",
                str(state_path),
                "--at",
                "4500",
                "--fixture-dir",
                str(tmp_path / "missing-fixtures"),
                "--source",
                "rss",
            ]
        )
        == 1
    )
    output = json.loads(capsys.readouterr().out)
    assert output["due_count"] == 1
    assert output["network_attempted"] is False
    assert output["results"] == [
        {
            "checked_at": 4500.0,
            "error": output["results"][0]["error"],
            "fixture_source": "rss",
            "item_count": 0,
            "run_id": 1,
            "source": "rss",
            "status": "failed",
        }
    ]
    assert output["results"][0]["error"].startswith("FileNotFoundError:")

    with StateStore(state_path) as store:
        runs = store.list_runs("rss")
        assert len(runs) == 1
        assert runs[0].item_count == 0
        assert runs[0].error == output["results"][0]["error"]
        assert store.recent_articles(1, now=4_501.0) == []


def test_fixture_tick_rejects_implicit_state_and_invalid_interval(capsys):
    with pytest.raises(SystemExit) as missing_state:
        main(["tick", "--at", "1"])
    assert missing_state.value.code == 2
    assert "--state" in capsys.readouterr().err

    with pytest.raises(SystemExit) as invalid_interval:
        main(
            [
                "tick",
                "--state",
                ":memory:",
                "--at",
                "1",
                "--interval-seconds",
                "0",
            ]
        )
    assert invalid_interval.value.code == 2
    assert "must be positive" in capsys.readouterr().err


def test_archived_json_and_ini_configuration_are_loaded(tmp_path):
    from monitor.config import load_config
    legacy = tmp_path / "legacy.json"
    legacy.write_text(json.dumps({"db_path": "explicit.db", "interval": 17,
                                  "sources": ["hn", "github"], "alert_threshold": 0.8,
                                  "alert_log": "alerts.log", "llm_endpoint": "http://localhost:11434"}))
    config = load_config(legacy)
    assert config.db_path == "explicit.db" and config.poll_interval_s == 17
    assert config.sources == ("hackernews", "github_trending")
    assert config.alert_threshold == 0.8 and config.alert_log == "alerts.log"
    assert config.llm_endpoint == "http://localhost:11434"
    ini = tmp_path / "legacy.ini"
    ini.write_text("[database]\npath=other.db\n[monitor]\npoll_interval_s=7\nlog_level=debug\n")
    config = load_config(ini)
    assert (config.db_path, config.poll_interval_s, config.log_level) == ("other.db", 7, "DEBUG")
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "missing.ini")


def test_recurring_loop_records_repeated_checks_and_stops(tmp_path):
    import threading
    from monitor.scheduler import run_source_loop
    stop = threading.Event()
    times = iter([100.0, 102.0, 104.0])
    with StateStore(tmp_path / "loop.db") as store:
        store.register_source("hackernews", "hackernews", 1)
        store.register_source("unadmitted", "rss", 1)
        rows = list(run_source_loop(store, lambda source: fetch_fixture_articles(
            __import__("pathlib").Path(__file__).parents[1] / "monitor/fixtures", [source]
        ), poll_interval_s=0.001, max_cycles=3, clock=lambda: next(times),
            source_names=["hackernews"], stop_event=stop))
        assert len(rows) == 3
        assert [r[1][0].item_count for r in rows] == [5, 5, 5]
        assert len(store.list_runs()) == 3
        stop.set()
        assert list(run_source_loop(store, lambda source: [], poll_interval_s=1, stop_event=stop)) == []


def test_watch_uses_explicit_config_and_preserves_live_registration(tmp_path, monkeypatch, capsys):
    state = tmp_path / "watch.db"
    with StateStore(state) as store:
        store.register_source("live:hackernews", "hackernews", 1)
    config = tmp_path / "watch.json"
    config.write_text(json.dumps({"db_path": str(state), "interval": 1, "sources": ["hn"]}))
    def forbidden(*args, **kwargs):
        raise AssertionError("offline watch attempted network")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    assert main(["watch", "--config", str(config), "--cycles", "1"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["mode"] == "fixture-watch"
    assert [r["source"] for r in output["results"]] == ["hackernews"]
    with StateStore(state) as store:
        assert [r.source for r in store.list_runs()] == ["hackernews"]
    assert main(["watch", "--config", str(config), "--cycles", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["results"] == []


def test_watch_rejects_invalid_config_before_creating_state(tmp_path, capsys):
    state = tmp_path / "must-not-exist.db"
    config = tmp_path / "bad.json"
    config.write_text(json.dumps({"db_path": str(state), "interval": 0}))
    assert main(["watch", "--config", str(config), "--cycles", "1"]) == 1
    assert not state.exists()
    assert "positive" in capsys.readouterr().err


def test_watch_scores_and_delivers_alerts_with_fractional_legacy_threshold(tmp_path, capsys):
    import json
    from monitor.cli import main
    config = tmp_path / 'config.json'
    log = tmp_path / 'alerts.jsonl'
    config.write_text(json.dumps({'db_path': str(tmp_path / 'state.sqlite3'),
        'sources': ['hn'], 'alert_threshold': 0.2, 'alert_log': str(log)}))
    assert main(['watch', '--config', str(config), '--cycles', '1']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['scored_count'] == 5
    assert output['created_alerts'] == 5 and output['delivery_errors'] == []
    lines = log.read_text().splitlines()
    assert len(lines) == 5
    assert all(json.loads(line)['threshold'] == 20 for line in lines)
    assert main(['watch', '--config', str(config), '--cycles', '1']) == 0
    output = json.loads(capsys.readouterr().out)
    assert output['created_alerts'] == 0 and output['delivery_errors'] == []
    assert log.read_text().splitlines() == lines


def test_measured_source_latency_is_preserved_for_success_and_failure(tmp_path):
    from monitor.scheduler import run_due_source_checks
    from monitor.storage import StateStore
    times = iter([10.0, 10.25, 11.0, 11.75])
    def collect(source):
        if source == 'rss':
            raise OSError('observed source failure')
        return []
    with StateStore(tmp_path / 'state.sqlite3') as store:
        store.register_source('a', 'hackernews', 30)
        store.register_source('b', 'rss', 30)
        results = run_due_source_checks(store, collect, checked_at=100, elapsed_clock=lambda: next(times))
        assert [r.status for r in results] == ['succeeded', 'failed']
        stats = {r.source: r for r in store.all_reliability()}
        assert stats['a'].mean_latency_ms == 250
        assert stats['b'].mean_latency_ms == 750
        assert stats['b'].hit_rate == 0
        assert store.due_sources(now=130) == []
        assert [s.source.name for s in store.due_sources(now=130.5)] == ['a']

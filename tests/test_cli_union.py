"""Executable regressions for the bounded canonical capability union."""

from __future__ import annotations

import json
import hashlib
import socket
import urllib.request

import pytest

from monitor.cli import main
from monitor.storage import StateStore


def test_fetch_dry_run_is_deterministic_and_offline(monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            f"network function called: args={args!r} kwargs={kwargs!r}"
        )

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    assert main(["fetch", "--dry-run"]) == 0
    first = capsys.readouterr().out
    assert main(["fetch", "--dry-run"]) == 0
    second = capsys.readouterr().out
    assert first == second

    result = json.loads(first)
    assert result["mode"] == "fixture-dry-run"
    assert result["network_attempted"] is False
    assert result["count"] == 15
    assert result["source_counts"] == {
        "Tech News Daily": 5,
        "github_trending": 5,
        "hackernews": 5,
    }


def test_fetch_can_select_one_fixture_source(capsys):
    assert main(["fetch", "--dry-run", "--source", "rss"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["count"] == 5
    assert result["source_counts"] == {"Tech News Daily": 5}


def test_fetch_without_dry_run_fails_closed(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["fetch"])
    assert exc_info.value.code == 2
    assert "requires --dry-run" in capsys.readouterr().err


def test_existing_local_json_summary_behavior(tmp_path, monkeypatch, capsys):
    fixture = tmp_path / "events.json"
    fixture.write_text(
        json.dumps(
            [
                {
                    "id": "1",
                    "title": "Database timeout",
                    "source": "app",
                    "timestamp": "2026-06-01T10:00:00Z",
                    "category": "error",
                    "severity": "high",
                    "summary": "DB timeout",
                },
                {
                    "id": "2",
                    "title": "Slow query",
                    "source": "app",
                    "timestamp": "2026-06-01T10:01:00Z",
                    "category": "warning",
                    "severity": "medium",
                    "summary": "Slow query",
                },
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr("monitor.cli.DEFAULT_EVENTS", fixture)
    assert main([]) == 0
    assert capsys.readouterr().out == (
        "1 error event detected; 1 warning event detected; "
        "1 high-severity event; 1 medium-severity event.\n"
    )


def test_alert_cli_evaluates_deduplicates_lists_and_resolves_offline(
    tmp_path, monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            f"network function called: args={args!r} kwargs={kwargs!r}"
        )

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)
    state_path = tmp_path / "state.sqlite3"
    evaluate = [
        "alerts",
        "evaluate",
        "--state",
        str(state_path),
        "--at",
        "5000",
        "--rule",
        "rss-score",
        "--threshold",
        "20",
        "--severity",
        "critical",
        "--source",
        "rss",
    ]

    assert main(evaluate) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["analyzed_count"] == 5
    assert first["created_count"] == 5
    assert first["network_attempted"] is False
    assert all(event["score"] == event["threshold"] == 20 for event in first["events"])
    assert all(event["severity"] == "critical" for event in first["events"])

    assert main(evaluate) == 0
    assert json.loads(capsys.readouterr().out)["created_count"] == 0

    first_alert_id = first["events"][0]["alert_id"]
    assert (
        main(["alerts", "resolve", str(first_alert_id), "--state", str(state_path)])
        == 0
    )
    resolved = json.loads(capsys.readouterr().out)
    assert resolved["resolved"] is True

    assert main(["alerts", "resolve", "999999", "--state", str(state_path)]) == 1
    missing = json.loads(capsys.readouterr().out)
    assert missing == {
        "alert_id": 999999,
        "mode": "local-alert-resolution",
        "network_attempted": False,
        "resolved": False,
    }

    assert main(["alerts", "list", "--state", str(state_path), "--unresolved"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["count"] == 4
    assert all(event["resolved"] is False for event in listed["events"])
    assert first_alert_id not in {event["alert_id"] for event in listed["events"]}


def test_alert_cli_rejects_invalid_rule_threshold_limit_and_identifier(capsys):
    invalid_commands = (
        (
            [
                "alerts",
                "evaluate",
                "--state",
                ":memory:",
                "--at",
                "1",
                "--rule",
                " ",
                "--threshold",
                "20",
            ],
            "--rule",
        ),
        (
            [
                "alerts",
                "evaluate",
                "--state",
                ":memory:",
                "--at",
                "1",
                "--threshold",
                "101",
            ],
            "--threshold",
        ),
        (["alerts", "list", "--state", ":memory:", "--limit", "0"], "--limit"),
        (["alerts", "resolve", "0", "--state", ":memory:"], "alert_id"),
    )
    for command, message in invalid_commands:
        with pytest.raises(SystemExit) as exc_info:
            main(command)
        assert exc_info.value.code == 2
        assert message in capsys.readouterr().err


def test_dashboard_is_deterministic_read_only_and_covers_local_lifecycle(
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
                "1000",
                "--source",
                "rss",
                "--interval-seconds",
                "60",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "alerts",
                "evaluate",
                "--state",
                str(state_path),
                "--at",
                "1001",
                "--rule",
                "rss-score",
                "--threshold",
                "20",
                "--source",
                "rss",
            ]
        )
        == 0
    )
    evaluated = json.loads(capsys.readouterr().out)
    assert (
        main(
            [
                "alerts",
                "resolve",
                str(evaluated["events"][0]["alert_id"]),
                "--state",
                str(state_path),
            ]
        )
        == 0
    )
    capsys.readouterr()

    state_files_before = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.iterdir()
        if path.is_file()
    }
    command = [
        "dashboard",
        "--state",
        str(state_path),
        "--at",
        "1059",
        "--window-hours",
        "24",
        "--limit",
        "2",
    ]
    assert main(command) == 0
    first = capsys.readouterr().out
    assert main(command) == 0
    second = capsys.readouterr().out
    assert first == second
    assert {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in tmp_path.iterdir()
        if path.is_file()
    } == state_files_before

    snapshot = json.loads(first)
    assert snapshot["schema"] == "situation-monitor.dashboard.v1"
    assert snapshot["generated_at"] == 1059.0
    assert snapshot["network_attempted"] is False
    assert snapshot["articles"]["total_count"] == 5
    assert snapshot["articles"]["shown_count"] == 2
    assert all(item["score"] == 20 for item in snapshot["articles"]["items"])
    assert snapshot["run_receipts"] == {
        "failed_count": 0,
        "items": [
            {
                "error": None,
                "finished_at": 1000.0,
                "item_count": 5,
                "run_id": 1,
                "source": "rss",
                "started_at": 1000.0,
                "status": "succeeded",
            }
        ],
        "shown_count": 1,
        "succeeded_count": 1,
        "total_count": 1,
    }
    assert snapshot["sources"]["due_count"] == 0
    assert snapshot["sources"]["items"] == [
        {
            "due": False,
            "due_at": 1060.0,
            "enabled": True,
            "fixture_source": "rss",
            "hit_rate": 1.0,
            "mean_latency_ms": 0.0,
            "interval_seconds": 60,
            "last_finished_at": 1000.0,
            "last_run_id": 1,
            "last_status": "succeeded",
            "name": "rss",
            "run_count": 1,
            "success_count": 1,
        }
    ]
    assert snapshot["alerts"]["total_count"] == 5
    assert snapshot["alerts"]["unresolved_count"] == 4
    assert snapshot["alerts"]["resolved_count"] == 1
    assert snapshot["alerts"]["shown_count"] == 2

    due_command = [*command]
    due_command[due_command.index("1059")] = "1060"
    assert main(due_command) == 0
    due_snapshot = json.loads(capsys.readouterr().out)
    assert due_snapshot["sources"]["due_count"] == 1
    assert due_snapshot["sources"]["items"][0]["due"] is True


def test_dashboard_refuses_missing_state(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["dashboard", "--state", "missing.sqlite3", "--at", "1"])
    assert exc_info.value.code == 2
    assert "--state" in capsys.readouterr().err


def test_dashboard_rejects_nonfinite_time_and_invalid_bounds(tmp_path, capsys):
    state_path = tmp_path / "state.sqlite3"
    with StateStore(state_path):
        pass
    invalid_commands = (
        (["--at", "nan"], "--at"),
        (["--at", "1", "--window-hours", "inf"], "--window-hours"),
        (["--at", "1", "--window-hours", "-1"], "--window-hours"),
        (["--at", "1", "--limit", "0"], "--limit"),
    )
    for arguments, message in invalid_commands:
        with pytest.raises(SystemExit) as exc_info:
            main(["dashboard", "--state", str(state_path), *arguments])
        assert exc_info.value.code == 2
        assert message in capsys.readouterr().err


def test_bundled_default_summary_is_runnable(capsys):
    assert main([]) == 0
    result = capsys.readouterr()
    assert result.err == ""
    assert "3 economic events detected" in result.out
    assert "2 geopolitical events detected" in result.out
    assert "2 weather events detected" in result.out


def test_missing_summary_input_is_not_reported_as_success(tmp_path, capsys):
    assert main(["summary", str(tmp_path / "missing.json")]) == 1
    result = capsys.readouterr()
    assert "File not found" in result.err


def test_valid_empty_event_stream_remains_successful(tmp_path, capsys):
    path = tmp_path / "empty.json"
    path.write_text("[]")
    assert main(["summary", str(path)]) == 0
    assert capsys.readouterr().out == "No events detected.\n"

"""Executable regressions for the bounded canonical capability union."""

from __future__ import annotations

import json
import socket
import urllib.request

import pytest

from monitor.cli import main


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

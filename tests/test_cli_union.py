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

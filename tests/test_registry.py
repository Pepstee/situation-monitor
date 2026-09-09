"""Condition-registry integration, separate from article alert evaluation tests.

This file covers the restored metadata lifecycle across actual CLI processes and
schema upgrades. Existing storage tests own article/run/alert persistence.
"""
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from monitor.scheduler import run_due_source_checks
from monitor.storage import SCHEMA_VERSION, StateStore


def test_registry_cli_reopens_relationships_without_executing_targets(tmp_path):
    state = tmp_path / "state.db"
    marker = tmp_path / "must-not-exist"

    def cli(*args):
        result = subprocess.run(
            [sys.executable, "-m", "monitor", *args, "--state", str(state)],
            cwd=Path(__file__).resolve().parents[1], text=True, capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)

    source_id = cli("sources", "add", "command definition", "cmd", f"touch {marker}", "--tags", "test,metadata")["source_id"]
    source = cli("sources", "list")[0]
    assert source["target"] == f"touch {marker}"
    assert source["tags"] == "test,metadata"
    check_id = cli("checks", "add", str(source_id), "error", "contains:ERROR")["check_id"]
    assert cli("checks", "list", "--source-id", str(source_id))[0]["condition"] == "contains:ERROR"
    event_id = cli("events", "record", str(check_id), "2026-09-09T12:00:00Z", "manual observation")["event_id"]
    assert cli("events", "list", "--unresolved")[0]["detail"] == "manual observation"
    assert cli("events", "resolve", str(event_id)) == {"resolved": True}
    assert cli("events", "list", "--unresolved") == []
    assert cli("events", "list")[0]["resolved"] is True
    with StateStore(state) as store:
        assert run_due_source_checks(store, lambda _: pytest.fail("metadata source executed"), checked_at=1) == []
        assert store.list_alert_events() == []
        with pytest.raises(sqlite3.IntegrityError):
            store.add_check(999, "orphan", "anything")
        with pytest.raises(sqlite3.IntegrityError):
            store.record_event(999, "2026-09-09T12:00:00Z")
        with pytest.raises(ValueError, match="metadata-only"):
            store.register_source("command definition", "hackernews", 60)
    assert not marker.exists()


@pytest.mark.parametrize("old_version", [3, 4])
def test_registry_upgrade_preserves_canonical_state(tmp_path, old_version):
    state = tmp_path / "old.db"
    with StateStore(state) as store:
        original_id = store.register_source("original", "hackernews", 60)
        store.record_run("original", 1, 2, item_count=3)
    # Reconstruct the pre-registry canonical layout, retaining its real data.
    with sqlite3.connect(state) as conn:
        conn.execute("DROP TABLE condition_events")
        conn.execute("DROP TABLE condition_checks")
        for column in ("kind", "target", "tags"):
            conn.execute(f"ALTER TABLE sources DROP COLUMN {column}")
        if old_version == 3:
            conn.execute("ALTER TABLE articles DROP COLUMN metadata_json")
        conn.execute(f"PRAGMA user_version = {old_version}")
    from monitor.cli import dashboard_snapshot
    snapshot = dashboard_snapshot(str(state), snapshot_at=100, window_hours=24, limit=100)
    assert snapshot["sources"]["items"][0]["fixture_source"] == "hackernews"
    with StateStore(state) as store:
        assert store.conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert store.list_sources()[0].source_id == original_id
        assert store.list_sources()[0].kind == "feed"
        assert store.list_runs()[0].item_count == 3
        store.add_source("local file", "file", "/not-opened", tags="archive")
        assert [item.source.name for item in store.due_sources(now=100)] == ["original"]
        assert store.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"

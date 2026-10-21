"""Independent CLI-process restart and retry coverage for alert delivery.

Each check runs the real ``python -m monitor`` entry point in its own
subprocess against offline fixture data only, exercising restart suppression
after successful delivery and retry of failed or unknown delivery on the next
run. No network is attempted.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = PROJECT_ROOT / "monitor" / "fixtures"


def run_cli(state: Path, alert_log: Path | None, *, cycles: int = 1, interval_seconds: int | None = None):
    command = [
        sys.executable,
        "-m",
        "monitor",
        "watch",
        "--state",
        str(state),
        "--alert-threshold",
        "0",
        "--cycles",
        str(cycles),
        "--fixture-dir",
        str(FIXTURE_DIR),
    ]
    if interval_seconds is not None:
        command += ["--interval-seconds", str(interval_seconds)]
    if alert_log is not None:
        command += ["--alert-log", str(alert_log)]
    return subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )


def parse_report(result: subprocess.CompletedProcess) -> dict:
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert lines, result.stdout + result.stderr
    return json.loads(lines[-1])


def log_alert_ids(alert_log: Path) -> set[int]:
    if not alert_log.exists():
        return set()
    return {
        json.loads(line)["alert_id"]
        for line in alert_log.read_text().splitlines()
        if line.strip()
    }


@pytest.fixture()
def offline_state(tmp_path) -> Path:
    return tmp_path / "state.sqlite"


def test_successful_delivery_suppresses_repeated_alert_after_cli_restart(
    offline_state, tmp_path, capsys
):
    alert_log = tmp_path / "alerts.jsonl"

    first = run_cli(offline_state, alert_log)
    assert first.returncode == 0, first.stdout + first.stderr
    report = parse_report(first)
    assert report["delivery_errors"] == []
    assert report["created_alerts"] >= 1
    delivered_first = log_alert_ids(alert_log)
    assert delivered_first
    assert "[ALERT]" in first.stderr

    # Fresh CLI process restarts against the same state and delivered log.
    capsys.readouterr()
    second = run_cli(offline_state, alert_log)
    assert second.returncode == 0, second.stdout + second.stderr
    report = parse_report(second)
    assert report["delivery_errors"] == []
    assert report["created_alerts"] == 0
    assert log_alert_ids(alert_log) == delivered_first
    assert "[ALERT]" not in second.stderr


def test_failed_delivery_is_retried_on_next_cli_run(offline_state, tmp_path):
    undeliverable = tmp_path / "missing-directory" / "alerts.jsonl"

    failed = run_cli(offline_state, undeliverable)
    assert failed.returncode == 1, failed.stdout + failed.stderr
    report = parse_report(failed)
    assert report["created_alerts"] >= 1
    assert report["delivery_errors"], "failed delivery must be reported"
    assert not undeliverable.exists()

    # Next run: the persisted event is still unknown to any delivery receipt,
    # so the same alert is retried against a working log path and delivered.
    alert_log = tmp_path / "alerts.jsonl"
    retried = run_cli(offline_state, alert_log)
    assert retried.returncode == 0, retried.stdout + retried.stderr
    report = parse_report(retried)
    assert report["delivery_errors"] == []
    assert report["created_alerts"] == 0
    assert log_alert_ids(alert_log)
    assert "[ALERT]" in retried.stderr


def cycle_reports(result: subprocess.CompletedProcess) -> list[dict]:
    payloads = []
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "created_alerts" in obj:
            payloads.append(obj)
    return payloads


def test_finite_cycles_run_exactly_requested_cycles_then_stop(offline_state, tmp_path):
    """``--cycles`` bounds the watch loop: exactly that many cycle reports
    are emitted, the process exits 0, and delivery is deduplicated across
    cycles inside the single finite process."""

    alert_log = tmp_path / "alerts.jsonl"

    finite = run_cli(offline_state, alert_log, cycles=3, interval_seconds=1)
    assert finite.returncode == 0, finite.stdout + finite.stderr
    reports = cycle_reports(finite)
    assert len(reports) == 3, finite.stdout
    assert all(report["delivery_errors"] == [] for report in reports)
    total_created = sum(report["created_alerts"] for report in reports)
    assert total_created >= 1
    # In-process deduplication across cycles: each firing is delivered to
    # stderr and the receipt log exactly once, never once per cycle.
    assert finite.stderr.count("[ALERT]") == total_created
    assert len(log_alert_ids(alert_log)) == total_created

    # The finite process having stopped, a further run is a plain restart
    # and stays fully suppressed.
    restart = run_cli(offline_state, alert_log)
    assert restart.returncode == 0, restart.stdout + restart.stderr
    assert cycle_reports(restart)[-1]["created_alerts"] == 0
    assert "[ALERT]" not in restart.stderr
    assert len(log_alert_ids(alert_log)) == total_created


def run_cli_from(cwd: Path, state: Path, alert_log: Path | None):
    """Run ``python -m monitor watch`` with ``cwd`` as the working directory.

    The extracted package is made importable through PYTHONPATH, never
    through an implicit current-directory import, so this distinguishes a
    genuine declaration of the ``monitor`` package from cwd luck.
    """

    command = [
        sys.executable,
        "-m",
        "monitor",
        "watch",
        "--state",
        str(state),
        "--alert-threshold",
        "0",
        "--cycles",
        "1",
        "--fixture-dir",
        str(FIXTURE_DIR),
    ]
    if alert_log is not None:
        command += ["--alert-log", str(alert_log)]
    env = dict(os.environ)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(PROJECT_ROOT)
        if not existing
        else os.pathsep.join([str(PROJECT_ROOT), existing])
    )
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


def test_declaration_registrations_root_and_foreign_cwd(tmp_path):
    """The declared entry point works from the project root and from a
    completely different working directory, with identical delivery
    semantics (receipts persisted, restart suppression)."""

    alert_log = tmp_path / "alerts.jsonl"
    root_state = tmp_path / "root-state.sqlite"
    from_root = run_cli_from(PROJECT_ROOT, root_state, alert_log)
    assert from_root.returncode == 0, from_root.stdout + from_root.stderr
    report = parse_report(from_root)
    assert report["delivery_errors"] == []
    assert report["created_alerts"] >= 1
    delivered_ids = log_alert_ids(alert_log)
    assert delivered_ids
    assert "[ALERT]" in from_root.stderr

    # Direct execution from another working directory: a fresh state must
    # start from a fresh receipt log too, because alert ids restart per state
    # and reusing the root run's log would collide with its receipts.
    foreign_cwd = tmp_path / "unrelated-cwd"
    foreign_cwd.mkdir()
    foreign_state = tmp_path / "foreign-state.sqlite"
    foreign_log = tmp_path / "foreign-alerts.jsonl"
    from_foreign = run_cli_from(foreign_cwd, foreign_state, foreign_log)
    assert from_foreign.returncode == 0, from_foreign.stdout + from_foreign.stderr
    report = parse_report(from_foreign)
    assert report["delivery_errors"] == []
    assert report["created_alerts"] >= 1
    foreign_ids = log_alert_ids(foreign_log)
    assert foreign_ids
    assert "[ALERT]" in from_foreign.stderr

    # Restart from the foreign working directory against the same state and
    # receipt log: persisted receipts suppress every unchanged firing.
    restart = run_cli_from(foreign_cwd, foreign_state, foreign_log)
    assert restart.returncode == 0, restart.stdout + restart.stderr
    report = parse_report(restart)
    assert report["delivery_errors"] == []
    assert report["created_alerts"] == 0
    assert log_alert_ids(foreign_log) == foreign_ids
    assert "[ALERT]" not in restart.stderr

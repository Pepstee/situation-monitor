#!/usr/bin/env python3
"""Offline acceptance runner: fixture RSS only, no network.

Commands run in sequence:
  1. once           -- full digest with WORLD/MARKETS/AI sections, dual-lens events, spin_pct
  2. digest-dry-run -- Telegram-formatted digest (independent subprocess)
  3. carrier once   -- validates a discourse-carrier line; equivalent of: | grep "^discourse-carrier"
  4. check_server.py -- Flask smoke test (web-server-smoke: PASS)

Primary fixture: rss_sample.xml (via SM_SOURCES).
Domain fixtures: rss_markets.xml and rss_ai.xml (via acceptance_source_defs.json).
# SM_LLM_BACKEND=offline is set in each subprocess env for reproducible offline runs.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent
_FIXTURES = _ROOT / "tests" / "fixtures"
_SOURCE_DEFS = str(_FIXTURES / "acceptance_source_defs.json")
# rss_sample.xml is the primary offline fixture (used via SM_SOURCES)
_RSS_SAMPLE = str(_FIXTURES / "rss_sample.xml")
_RSS_CARRIER = str(_FIXTURES / "rss_carrier.xml")

_ENV: dict = {
    **os.environ,
    "SM_LLM_BACKEND": "offline",  # SM_LLM_BACKEND=offline
    "SM_SOURCES": _RSS_SAMPLE,
}


def _run(*args: str, env: dict | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    kw: dict = dict(env=env or _ENV, cwd=str(_ROOT))
    if capture:
        kw["capture_output"] = True
        kw["text"] = True
    return subprocess.run(
        [sys.executable, "-m", "situation_monitor", *args, "--config", _SOURCE_DEFS],
        **kw,
    )


def main() -> None:
    # Cmd 1: once — full digest (WORLD / MARKETS / AI + dual-lens events + spin_pct annotations)
    r1 = _run("once", capture=True)
    if r1.stdout:
        sys.stdout.write(r1.stdout)
        sys.stdout.flush()
    if r1.returncode != 0:
        if r1.stderr:
            sys.stderr.write(r1.stderr)
        sys.exit(r1.returncode)

    # Scan once stdout for verdict markers; write verdict_brief.txt
    dual_lens_ok = "DUAL-LENS EVENTS" in r1.stdout
    spin_pct_ok = "spin_pct:" in r1.stdout
    market_ok = "## MARKETS" in r1.stdout
    (_ROOT / "verdict_brief.txt").write_text(
        f"DUAL_LENS: {'Y' if dual_lens_ok else 'N'}\n"
        f"SPIN_PCT: {'Y' if spin_pct_ok else 'N'}\n"
        f"MARKET: {'Y' if market_ok else 'N'}\n"
    )
    if not (dual_lens_ok and spin_pct_ok and market_ok):
        failed = [
            k for k, ok in [
                ("DUAL_LENS", dual_lens_ok),
                ("SPIN_PCT", spin_pct_ok),
                ("MARKET", market_ok),
            ] if not ok
        ]
        print(f"ERROR: verdict checks failed: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)

    # Cmd 2: digest-dry-run — Telegram format (independent subprocess)
    r2 = _run("digest-dry-run")
    if r2.returncode != 0:
        sys.exit(r2.returncode)

    # Cmd 3: carrier once — stdout must include a line starting with "discourse-carrier"
    # equivalent of: python3 -m situation_monitor once ... | grep "^discourse-carrier"
    carrier_env: dict = {
        **_ENV,
        "SM_CARRIER_FEEDS": json.dumps(
            [{"url": "tests/fixtures/rss_carrier.xml", "country": "US", "lean": "centre"}]
        ),
    }
    r3 = _run("once", env=carrier_env, capture=True)
    if r3.returncode != 0:
        sys.exit(r3.returncode)
    carrier_lines = [ln for ln in r3.stdout.splitlines() if ln.startswith("discourse-carrier")]
    if not carrier_lines:
        print("ERROR: no 'discourse-carrier' line in carrier once output", file=sys.stderr)
        sys.exit(1)
    print(carrier_lines[0])
    sys.stdout.flush()

    # Cmd 4: check_server.py — Flask smoke test
    r4 = subprocess.run(
        [sys.executable, str(_ROOT / "check_server.py")],
        env=_ENV,
        cwd=str(_ROOT),
    )
    if r4.returncode != 0:
        sys.exit(r4.returncode)


if __name__ == "__main__":
    main()

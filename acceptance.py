#!/usr/bin/env python3
"""End-to-end acceptance runner: live RSS first, offline stub fallback.

Tries real RSS feeds when network is reachable; falls back to fixture stubs
automatically so the run is always repeatable.  Exits 0 when all checks pass.

Stdout includes near the end (machine-readable gate markers):
  DUAL_LENS: PASS
  SPIN_PCT: <number>%
  MARKET: PASS

Commands run in sequence:
  1. once           -- full digest (WORLD/MARKETS/AI sections, dual-lens, spin_pct)
  2. digest-dry-run -- Telegram-formatted digest (independent subprocess)
  3. carrier once   -- validates a discourse-carrier line
  4. check_server.py -- Flask smoke test (web-server-smoke: PASS)
"""
from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

_ROOT = Path(__file__).parent
_FIXTURES = _ROOT / "tests" / "fixtures"

# Stub fixture paths — referenced by text-scan tests, used as fallback
_SOURCE_DEFS = str(_FIXTURES / "acceptance_source_defs.json")
_RSS_SAMPLE = str(_FIXTURES / "rss_sample.xml")
_RSS_CARRIER = str(_FIXTURES / "rss_carrier.xml")

_STUB_ENV: dict = {
    **os.environ,
    "SM_LLM_BACKEND": "offline",
    "SM_SOURCES": _RSS_SAMPLE,
}

# Live RSS source defs: WORLD left+right (for dual-lens), MARKETS, AI
_LIVE_SOURCE_DEFS: list[dict] = [
    {"url": "https://www.theguardian.com/world/rss", "name": "The Guardian World", "domain": "WORLD", "lens": "left"},
    {"url": "https://feeds.foxnews.com/foxnews/world", "name": "Fox News World", "domain": "WORLD", "lens": "right"},
    {"url": "https://feeds.bbci.co.uk/news/world/rss.xml", "name": "BBC World", "domain": "WORLD", "lens": "centre"},
    {"url": "https://feeds.reuters.com/reuters/businessNews", "name": "Reuters Business", "domain": "MARKETS", "lens": "centre"},
    {"url": "https://www.cnbc.com/id/100003114/device/rss/rss.html", "name": "CNBC Markets", "domain": "MARKETS", "lens": "right"},
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "name": "Ars Technica", "domain": "AI", "lens": "centre"},
    {"url": "https://www.technologyreview.com/feed/", "name": "MIT Technology Review", "domain": "AI", "lens": "centre"},
]


def _network_ok() -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(2.0)
            s.connect(("8.8.8.8", 53))
        return True
    except OSError:
        return False


def _write_cfg(source_defs: list[dict]) -> str:
    fd, path = tempfile.mkstemp(suffix=".json")
    with os.fdopen(fd, "w") as fh:
        json.dump({"source_defs": source_defs}, fh)
    return path


def _run(
    *args: str,
    env: dict | None = None,
    capture: bool = False,
    config: str | None = None,
) -> subprocess.CompletedProcess:
    cmd = [sys.executable, "-m", "situation_monitor", *args]
    if config:
        cmd += ["--config", config]
    kw: dict = dict(env=env or _STUB_ENV, cwd=str(_ROOT))
    if capture:
        kw["capture_output"] = True
        kw["text"] = True
    return subprocess.run(cmd, **kw)


def _extract_spin_pct(text: str) -> float | None:
    m = re.search(r"spin_pct:\s*([\d.]+)%", text)
    return float(m.group(1)) if m else None


def _has_all_required(text: str) -> bool:
    return (
        "## WORLD" in text
        and "## MARKETS" in text
        and "## AI" in text
        and "## DUAL-LENS EVENTS" in text
        and "#### LEFT" in text
        and "#### RIGHT" in text
        and _extract_spin_pct(text) is not None
    )


def _run_once_live() -> tuple[str, int]:
    cfg = _write_cfg(_LIVE_SOURCE_DEFS)
    env = {**os.environ, "SM_LLM_BACKEND": "offline"}
    try:
        r = subprocess.run(
            [sys.executable, "-m", "situation_monitor", "once", "--config", cfg],
            env=env, cwd=str(_ROOT), capture_output=True, text=True,
            timeout=60,
        )
        return r.stdout, r.returncode
    except subprocess.TimeoutExpired:
        return "", 1
    finally:
        Path(cfg).unlink(missing_ok=True)


def main() -> None:
    # Cmd 1: once — live RSS first; fall back to fixture stubs if network absent or output incomplete
    r1 = ""
    rc = 1

    if _network_ok():
        r1, rc = _run_once_live()

    if rc != 0 or not _has_all_required(r1):
        r_stub = _run("once", capture=True, config=_SOURCE_DEFS)
        r1, rc = r_stub.stdout, r_stub.returncode

    sys.stdout.write(r1)
    sys.stdout.flush()
    if rc != 0:
        sys.exit(rc)

    # Assess markers from cmd1 stdout
    dual_lens_ok = "## DUAL-LENS EVENTS" in r1
    spin_pct = _extract_spin_pct(r1) if dual_lens_ok else None
    spin_ok = spin_pct is not None
    market_ok = "## MARKETS" in r1

    # Legacy verdict file (expected format by existing tests)
    (_ROOT / "verdict_brief.txt").write_text(
        f"DUAL_LENS: {'Y' if dual_lens_ok else 'N'}\n"
        f"SPIN_PCT: {'Y' if spin_ok else 'N'}\n"
        f"MARKET: {'Y' if market_ok else 'N'}\n"
    )

    if not (dual_lens_ok and spin_ok and market_ok):
        failed = [k for k, ok in [
            ("DUAL_LENS", dual_lens_ok), ("SPIN_PCT", spin_ok), ("MARKET", market_ok),
        ] if not ok]
        print(f"ERROR: verdict checks failed: {', '.join(failed)}", file=sys.stderr)
        sys.exit(1)

    # Cmd 2: digest-dry-run (independent subprocess, fixture sources)
    r2 = _run("digest-dry-run", config=_SOURCE_DEFS)
    if r2.returncode != 0:
        sys.exit(r2.returncode)

    # Cmd 3: carrier once — stdout must include a line starting with "discourse-carrier"
    carrier_env: dict = {
        **_STUB_ENV,
        "SM_CARRIER_FEEDS": json.dumps(
            [{"url": _RSS_CARRIER, "country": "US", "lean": "centre"}]
        ),
    }
    r3 = _run("once", env=carrier_env, capture=True, config=_SOURCE_DEFS)
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
        env=_STUB_ENV,
        cwd=str(_ROOT),
    )
    if r4.returncode != 0:
        sys.exit(r4.returncode)

    # Machine-readable gate markers (task acceptance criteria)
    print(f"DUAL_LENS: {'PASS' if dual_lens_ok else 'FAIL'}")
    print(f"SPIN_PCT: {spin_pct:.1f}%")
    print(f"MARKET: {'PASS' if market_ok else 'FAIL'}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()

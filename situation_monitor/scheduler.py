"""Daily 07:00 Europe/London digest scheduler.

Run as a module:  python3 -m situation_monitor.scheduler

Env vars:
  DIGEST_CLOUD=1          — enable cloud LLM calls (default: ollama only)
  TELEGRAM_BOT_TOKEN      — required to send; absent → print to stdout
  TELEGRAM_CHAT_ID        — required to send
  BREAKING_THRESHOLD      — relevance threshold for breaking pings (default 0.85)
"""

from __future__ import annotations

import logging
import os
import sys

_log = logging.getLogger(__name__)


def _build_config():
    from situation_monitor.config import Config
    from situation_monitor.__main__ import _apply_env

    config = Config.from_defaults()
    cloud_enabled = os.environ.get("DIGEST_CLOUD", "") == "1"
    if not cloud_enabled:
        config.llm_backend = "ollama"
        _log.info("DIGEST_CLOUD not set; forcing ollama backend")
    else:
        _log.info("DIGEST_CLOUD=1; using configured cloud backend")
    _apply_env(config)
    return config


def _run_digest() -> None:
    """Ingest, assemble, and deliver the daily digest."""
    from situation_monitor.__main__ import _ingest_and_enrich
    from situation_monitor.digest import breaking_ping, daily_digest, _send_telegram
    from situation_monitor.dual_lens import group_by_event
    from situation_monitor.practical import fetch_practical_movers

    config = _build_config()

    try:
        articles = _ingest_and_enrich(config)
    except Exception as exc:
        _log.error("Digest ingestion failed: %s", exc)
        return

    events = group_by_event(articles)

    try:
        movers = fetch_practical_movers()
    except Exception:
        movers = []

    text = daily_digest(events, movers)

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if token and chat_id:
        _send_telegram(token, chat_id, text)
        _log.info("Daily digest sent to Telegram chat %s", chat_id)
    else:
        print(text)
        _log.info("Telegram creds not set; digest printed to stdout")

    breaking_ping(articles)


def run_scheduler(digest_hour: int = 7) -> None:
    """Block forever, firing the daily digest at *digest_hour* Europe/London."""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler()
    scheduler.add_job(
        _run_digest,
        CronTrigger(hour=digest_hour, timezone="Europe/London"),
        name="daily_digest",
        misfire_grace_time=300,
    )
    _log.info(
        "Digest scheduler started; daily run at %02d:00 Europe/London", digest_hour
    )
    scheduler.start()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    run_scheduler()

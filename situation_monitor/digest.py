"""Telegram digest assembly and breaking-event ping."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from situation_monitor.dual_lens import DualLensEvent
from situation_monitor.models import Domain
from situation_monitor.practical import PracticalMover
from situation_monitor.urls import safe_url

_log = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# Telegram's legacy "Markdown" parse_mode treats these as entity delimiters.
# An unescaped one in interpolated text — e.g. a lone '*' in a headline like
# "Profits up 5* this year", or an underscore in a handle — leaves the markup
# unbalanced, so Telegram rejects the WHOLE message with HTTP 400 and the digest
# or breaking alert is silently lost. Escape every occurrence in untrusted text;
# structural markers (the '*' we emit deliberately) are written literally.
_MD_SPECIALS = ("_", "*", "`", "[", "]")


def _md_escape(text: str) -> str:
    """Backslash-escape Telegram-Markdown delimiters in interpolated text."""
    for ch in _MD_SPECIALS:
        text = text.replace(ch, "\\" + ch)
    return text


def daily_digest(
    events: list[DualLensEvent],
    movers: list[PracticalMover],
    top_n: int = 10,
    as_of: Optional[datetime] = None,
) -> str:
    """Assemble a Telegram-ready daily digest message.

    Accepts prebuilt event and mover lists — no live I/O performed here.
    """
    if as_of is None:
        as_of = datetime.now(timezone.utc)

    lines: list[str] = [
        f"*Situation Monitor* — {as_of.strftime('%Y-%m-%d %H:%M')} UTC\n",
    ]

    top_events = events[:top_n]
    if top_events:
        lines.append("*Top Stories*")
        for event in top_events:
            delta_str = f" ↕{event.spin_delta:.0f}%" if event.spin_delta > 5 else ""
            parts = []
            if event.left_articles:
                parts.append(f"L:{len(event.left_articles)}")
            if event.center_articles:
                parts.append(f"C:{len(event.center_articles)}")
            if event.right_articles:
                parts.append(f"R:{len(event.right_articles)}")
            lens_str = f" [{', '.join(parts)}]" if parts else ""
            lines.append(f"• {_md_escape(event.event_title)}{delta_str}{lens_str}")
    else:
        lines.append("_No events found._")

    if movers:
        lines.append("\n*Market Movers*")
        for mover in movers[:5]:
            arrow = "▲" if mover.direction == "up" else ("▼" if mover.direction == "down" else "→")
            lines.append(f"• {_md_escape(mover.asset)} {arrow} {abs(mover.change_pct):.1f}%")

    ai_articles = []
    seen_titles: set[str] = set()
    for event in events:
        for aa in event.left_articles + event.center_articles + event.right_articles:
            if aa.article.domain is Domain.AI and aa.article.title not in seen_titles:
                seen_titles.add(aa.article.title)
                ai_articles.append(aa.article)

    if ai_articles:
        lines.append("\n*🤖 AI News*")
        for art in ai_articles[:5]:
            lines.append(f"• {_md_escape(art.title)}")

    return "\n".join(lines)


def breaking_ping(
    articles: list,
    threshold: Optional[float] = None,
    bot_token: Optional[str] = None,
    chat_id: Optional[str] = None,
) -> None:
    """Send a Telegram message for articles above the significance threshold.

    No-op (logs only) when TELEGRAM_BOT_TOKEN is unset — zero side-effects in CI.
    Threshold, chat_id, and bot_token are also env-var driven:
      BREAKING_THRESHOLD  (default 0.85)
      TELEGRAM_BOT_TOKEN
      TELEGRAM_CHAT_ID
    """
    if threshold is None:
        try:
            threshold = float(os.environ.get("BREAKING_THRESHOLD", "0.85"))
        except (ValueError, TypeError):
            threshold = 0.85

    token = bot_token or os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        _log.debug("TELEGRAM_BOT_TOKEN not set; breaking_ping is a no-op")
        return

    chat = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
    if not chat:
        _log.warning("TELEGRAM_CHAT_ID not set; skipping breaking ping")
        return

    hot = [a for a in articles if (a.relevance_score or 0.0) >= threshold]
    if not hot:
        return

    lines = [f"🚨 *Breaking* — {len(hot)} high-significance event(s)\n"]
    for art in hot[:5]:
        score = f"{art.relevance_score:.2f}" if art.relevance_score is not None else "?"
        title = _md_escape(art.title)
        source = _md_escape(art.source)
        lines.append(f"• [{title}]({safe_url(art.url)}) — {source} ({score})")

    _send_telegram(token, chat, "\n".join(lines))


def _send_telegram(token: str, chat_id: str, text: str) -> None:
    url = _TELEGRAM_API.format(token=token)
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            _log.info("Telegram message sent: status=%d", resp.status)
    except Exception as exc:
        _log.error("Telegram send failed: %s", exc)

"""One configuration loader for the archived JSON and INI project formats."""

from __future__ import annotations

import configparser
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    db_path: str | None = None
    poll_interval_s: int = 30
    log_level: str = "INFO"
    sources: tuple[str, ...] = ()
    alert_threshold: float = 0.7
    alert_log: str | None = None
    llm_endpoint: str | None = None


def load_config(path: str | Path | None = None) -> Config:
    """Load explicit configuration without silently selecting a writable database."""
    if path is None:
        return Config()
    source = Path(path)
    text = source.read_text(encoding="utf-8")
    if source.suffix.lower() == ".json":
        values = json.loads(text)
        if not isinstance(values, dict):
            raise ValueError("configuration must be an object")
    else:
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(text)
        values = {
            "db_path": parser.get("database", "path", fallback=None),
            "poll_interval_s": parser.get("monitor", "poll_interval_s", fallback="30"),
            "log_level": parser.get("monitor", "log_level", fallback="INFO"),
        }
    interval = int(values.get("poll_interval_s", values.get("interval", 30)))
    if interval <= 0:
        raise ValueError("poll interval must be positive")
    raw_sources = values.get("sources", [])
    if not isinstance(raw_sources, list) or not all(isinstance(s, str) for s in raw_sources):
        raise ValueError("sources must be a list of source names")
    aliases = {"hn": "hackernews", "github": "github_trending"}
    sources = tuple(dict.fromkeys(aliases.get(s, s) for s in raw_sources))
    if set(sources) - {"hackernews", "github_trending", "rss"}:
        raise ValueError("unknown configured source")
    threshold = float(values.get("alert_threshold", 0.7))
    if not 0 <= threshold <= 1:
        raise ValueError("legacy alert_threshold must be in [0, 1]")
    for key in ("db_path", "alert_log", "llm_endpoint"):
        value = values.get(key)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"{key} must be a non-empty string")
    return Config(
        db_path=values.get("db_path"), poll_interval_s=interval,
        log_level=str(values.get("log_level", "INFO")).upper(), sources=sources,
        alert_threshold=threshold, alert_log=values.get("alert_log"),
        llm_endpoint=values.get("llm_endpoint"),
    )

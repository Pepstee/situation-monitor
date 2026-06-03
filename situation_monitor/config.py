"""Configuration loading for situation_monitor."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Config:
    sources: list[str] = field(default_factory=list)
    fetch_interval_seconds: int = 3600
    max_articles_per_digest: int = 20
    digest_output_dir: str = "digests"
    log_level: str = "INFO"
    anthropic_model: str = "claude-sonnet-4-6"
    state_file: Optional[str] = None
    poll_interval_seconds: int = 600
    alert_threshold: float = 0.8
    llm_backend: str = "claude"
    ollama_model: str = "llama3"
    ollama_url: str = "http://localhost:11434"
    polymarket_markets: list = field(default_factory=list)
    dashboard_port: int = 8080

    def __repr__(self) -> str:
        return (
            f"Config(sources={self.sources!r}, "
            f"fetch_interval_seconds={self.fetch_interval_seconds}, "
            f"max_articles_per_digest={self.max_articles_per_digest}, "
            f"digest_output_dir={self.digest_output_dir!r}, "
            f"log_level={self.log_level!r}, "
            f"anthropic_model={self.anthropic_model!r})"
        )

    @classmethod
    def from_defaults(cls) -> "Config":
        return cls()

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        path = Path(path)
        with path.open() as fh:
            data: dict = json.load(fh)
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_env(cls) -> "Config":
        kwargs: dict = {}
        if (v := os.environ.get("SM_FETCH_INTERVAL")):
            kwargs["fetch_interval_seconds"] = int(v)
        if (v := os.environ.get("SM_MAX_ARTICLES")):
            kwargs["max_articles_per_digest"] = int(v)
        if (v := os.environ.get("SM_DIGEST_DIR")):
            kwargs["digest_output_dir"] = v
        if (v := os.environ.get("SM_LOG_LEVEL")):
            kwargs["log_level"] = v
        if (v := os.environ.get("SM_MODEL")):
            kwargs["anthropic_model"] = v
        if (v := os.environ.get("SM_STATE_FILE")):
            kwargs["state_file"] = v
        if (v := os.environ.get("SM_SOURCES")):
            kwargs["sources"] = [s.strip() for s in v.split(",") if s.strip()]
        if (v := os.environ.get("SM_POLL_INTERVAL")):
            kwargs["poll_interval_seconds"] = int(v)
        if (v := os.environ.get("SM_ALERT_THRESHOLD")):
            kwargs["alert_threshold"] = float(v)
        if (v := os.environ.get("SM_LLM_BACKEND")):
            kwargs["llm_backend"] = v
        if (v := os.environ.get("SM_OLLAMA_MODEL")):
            kwargs["ollama_model"] = v
        if (v := os.environ.get("SM_OLLAMA_URL")):
            kwargs["ollama_url"] = v
        if (v := os.environ.get("SM_DASHBOARD_PORT")):
            kwargs["dashboard_port"] = int(v)
        if (v := os.environ.get("SM_POLYMARKET_MARKETS")):
            kwargs["polymarket_markets"] = [s.strip() for s in v.split(",") if s.strip()]
        return cls(**kwargs)

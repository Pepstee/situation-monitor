"""Situation Monitor: Event ingestion and summarization package.

Provides core functionality for loading, processing, and summarizing events.
"""

from monitor.analysis import analyze_articles, build_digest
from monitor.ingest import fetch_fixture_articles, load_events
from monitor.storage import StateStore
from monitor.summarize import summarize

__all__ = [
    "analyze_articles",
    "build_digest",
    "fetch_fixture_articles",
    "load_events",
    "StateStore",
    "summarize",
]

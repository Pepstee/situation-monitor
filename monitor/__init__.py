"""Situation Monitor: Event ingestion and summarization package.

Provides core functionality for loading, processing, and summarizing events.
"""

from monitor.ingest import fetch_fixture_articles, load_events
from monitor.summarize import summarize

__all__ = ["fetch_fixture_articles", "load_events", "summarize"]

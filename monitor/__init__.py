"""Situation Monitor: Event ingestion and summarization package.

Provides core functionality for loading, processing, and summarizing events.
"""

from monitor.ingest import load_events
from monitor.summarize import summarize

__all__ = ["load_events", "summarize"]

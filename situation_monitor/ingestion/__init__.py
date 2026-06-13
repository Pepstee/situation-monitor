"""Ingestion layer — fetchers for various news sources."""

from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.ingestion.rss import RSSFetcher

__all__ = ["HNFetcher", "RSSFetcher"]

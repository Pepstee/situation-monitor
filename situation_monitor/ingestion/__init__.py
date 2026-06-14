"""Ingestion layer — fetchers for various news sources."""

from situation_monitor.ingestion.discourse_carrier import DiscourseCarrierFetcher
from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.ingestion.rss import RSSFetcher

__all__ = ["DiscourseCarrierFetcher", "HNFetcher", "RSSFetcher"]

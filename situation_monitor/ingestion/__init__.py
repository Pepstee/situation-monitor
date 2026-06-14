"""Ingestion layer — fetchers for various news sources."""

from situation_monitor.ingestion.bluesky import BlueskyFetcher
from situation_monitor.ingestion.discourse_carrier import DiscourseCarrierFetcher
from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.ingestion.nitter import NitterFetcher
from situation_monitor.ingestion.rss import RSSFetcher

__all__ = ["BlueskyFetcher", "DiscourseCarrierFetcher", "HNFetcher", "NitterFetcher", "RSSFetcher"]

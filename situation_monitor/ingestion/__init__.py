"""Ingestion layer — fetchers for various news sources."""

from situation_monitor.ingestion.bluesky import BlueskyFetcher
from situation_monitor.ingestion.crypto import CryptoRSSFetcher
from situation_monitor.ingestion.discourse_carrier import DiscourseCarrierFetcher
from situation_monitor.ingestion.github_trending import GitHubTrendingFetcher
from situation_monitor.ingestion.hn import HNFetcher
from situation_monitor.ingestion.mastodon import MastodonFetcher
from situation_monitor.ingestion.nitter import NitterFetcher
from situation_monitor.ingestion.reddit import RedditScraper
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.ingestion.yahoo_finance import YahooFinanceScraper

__all__ = [
    "BlueskyFetcher",
    "CryptoRSSFetcher",
    "DiscourseCarrierFetcher",
    "GitHubTrendingFetcher",
    "HNFetcher",
    "MastodonFetcher",
    "NitterFetcher",
    "RedditScraper",
    "RSSFetcher",
    "YahooFinanceScraper",
]


def _select_fetcher(source: str, client=None):
    if "hn.algolia.com" in source or source.startswith("hn://"):
        return HNFetcher(client=client)
    if "github.com/trending" in source or source.startswith("github_trending://"):
        return GitHubTrendingFetcher(client=client)
    if "coindesk" in source or "cointelegraph" in source:
        return CryptoRSSFetcher(client=client)
    return RSSFetcher(client=client)

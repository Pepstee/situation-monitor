"""Discourse carrier fetcher — national-media RSS feeds stamped with country and lean."""

from __future__ import annotations

from typing import NamedTuple

from situation_monitor.ingestion.base import Fetcher, HttpClient
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.models import Article


class CarrierDef(NamedTuple):
    url: str
    country: str
    lean: str


CARRIER_ROSTER: list[CarrierDef] = [
    CarrierDef("https://feeds.bbci.co.uk/news/world/rss.xml", "GB", "centre"),
    CarrierDef("https://www.france24.com/en/rss", "FR", "state"),
    CarrierDef("https://rss.dw.com/rdf/rss-en-all", "DE", "state"),
    CarrierDef("https://www.rt.com/rss/", "RU", "state"),
    CarrierDef("http://www.xinhuanet.com/english/rss/worldnews.xml", "CN", "state"),
    CarrierDef("https://www.aljazeera.com/xml/rss/all.xml", "QA", "left"),
    CarrierDef("https://en.irna.ir/rss", "IR", "state"),
    CarrierDef("https://timesofindia.indiatimes.com/rssfeedstopstories.cms", "IN", "centre"),
    CarrierDef("https://feeds.reuters.com/Reuters/worldNews", "US", "centre"),
    CarrierDef("https://feeds.foxnews.com/foxnews/world", "US", "right"),
]


class DiscourseCarrierFetcher(Fetcher):
    """Fetches articles from national-media carrier feeds and stamps each with country and lean.

    The ``roster`` drives fetching; the ``url`` argument to :meth:`fetch` is
    unused (kept for interface compatibility with :class:`~.Fetcher`).
    """

    def __init__(
        self,
        roster: list[CarrierDef] | None = None,
        client: HttpClient | None = None,
    ) -> None:
        super().__init__(client)
        self._roster = roster if roster is not None else CARRIER_ROSTER

    def fetch(self, url: str = "") -> list[Article]:
        all_articles: list[Article] = []
        rss = RSSFetcher(client=self._client)
        for carrier in self._roster:
            try:
                fetched = rss.fetch(carrier.url)
                for article in fetched:
                    article.source_lean = carrier.lean
                    if "carrier" not in article.tags:
                        article.tags.append("carrier")
                    country_tag = f"country:{carrier.country}"
                    if country_tag not in article.tags:
                        article.tags.append(country_tag)
                all_articles.extend(fetched)
            except Exception:
                pass
        return all_articles

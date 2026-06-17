"""Entity dossier: per-entity intelligence aggregation across sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from situation_monitor.config import DEFAULT_SOURCE_DEFS, Config, SourceDef
from situation_monitor.dedup import deduplicate
from situation_monitor.ingestion.base import HttpClient
from situation_monitor.ingestion.rss import RSSFetcher
from situation_monitor.models import Article, Domain


@dataclass
class EntityDossier:
    entity: str
    sources_checked: int
    articles_found: int
    summaries: list[str] = field(default_factory=list)
    fabrication_flags: list[str] = field(default_factory=list)
    outage_sources: list[str] = field(default_factory=list)


# At least 8 sources with ≥3 non-English outlets.
_SOURCE_NAMES = {
    "BBC World",          # EN — centre
    "Reuters World",      # EN — centre
    "Al Jazeera",         # EN — left
    "RT",                 # EN — state
    # non-English
    "Le Monde",           # FR — left
    "Frankfurter Rundschau",  # DE — left
    "ANSA",               # IT — centre
    "Handelsblatt",       # DE — right
    "Heise Online",       # DE — centre
}

ENTITY_ROSTER: list[SourceDef] = [
    sd for sd in DEFAULT_SOURCE_DEFS if sd.name in _SOURCE_NAMES
]


def build_dossier(
    entity_name: str,
    config: Config,
    llm: Callable[[str], str],
    *,
    _client: HttpClient | None = None,
) -> EntityDossier:
    fetcher = RSSFetcher(client=_client)
    all_articles: list[Article] = []
    outage_sources: list[str] = []

    for source_def in ENTITY_ROSTER:
        try:
            articles = fetcher.fetch(source_def.url, source_def)
            all_articles.extend(articles)
        except Exception:
            outage_sources.append(source_def.name)

    deduped = deduplicate(all_articles)

    entity_lower = entity_name.strip().lower()
    # A blank entity must never match (empty substring matches everything,
    # which would otherwise feed unrelated articles to the summariser and
    # invite fabrication). No entity → no relevant articles, no summary.
    relevant = [
        a for a in deduped
        if entity_lower and (
            entity_lower in a.title.lower() or entity_lower in a.body.lower()
        )
    ]

    summaries: list[str] = []
    fabrication_flags: list[str] = []

    if relevant:
        snippets = "\n".join(
            f"- [{a.source}] {a.title}: {a.body[:200]}" for a in relevant[:20]
        )
        prompt = (
            f"You are a factual intelligence analyst. Do not fabricate any information.\n"
            f"Summarise what is known about '{entity_name}' based solely on the following "
            f"news excerpts. If there is insufficient information, say so explicitly.\n\n"
            f"{snippets}"
        )
        try:
            response = llm(prompt)
            if response and response.strip():
                summaries = [response.strip()]
            else:
                fabrication_flags.append("llm_unavailable")
        except Exception:
            fabrication_flags.append("llm_unavailable")

    return EntityDossier(
        entity=entity_name,
        sources_checked=len(ENTITY_ROSTER),
        articles_found=len(deduped),
        summaries=summaries,
        fabrication_flags=fabrication_flags,
        outage_sources=outage_sources,
    )

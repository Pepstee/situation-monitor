"""Entity dossier: per-entity intelligence aggregation across sources."""

from __future__ import annotations

from dataclasses import dataclass, field

from situation_monitor.config import DEFAULT_SOURCE_DEFS, Config, SourceDef
from situation_monitor.models import Domain


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


def build_dossier(entity_name: str, config: Config, llm) -> EntityDossier:
    raise NotImplementedError

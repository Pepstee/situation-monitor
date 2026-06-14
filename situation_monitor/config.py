"""Configuration loading for situation_monitor."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from situation_monitor.auth import CredentialRegistry
from situation_monitor.models import Domain


@dataclass
class SourceDef:
    url: str
    name: str
    domain: Domain
    lens: str
    description: str = ""
    auth_platform: str | None = None


DEFAULT_SOURCE_DEFS: list[SourceDef] = [
    # WORLD — left
    SourceDef("https://www.theguardian.com/world/rss", "The Guardian World", Domain.WORLD, "left", "Left-liberal UK broadsheet world coverage"),
    SourceDef("https://www.democracynow.org/democracynow.rss", "Democracy Now", Domain.WORLD, "left", "Progressive US independent news"),
    SourceDef("https://www.aljazeera.com/xml/rss/all.xml", "Al Jazeera", Domain.WORLD, "left", "Qatar-based international news network"),
    # WORLD — right
    SourceDef("https://feeds.foxnews.com/foxnews/world", "Fox News World", Domain.WORLD, "right", "Conservative US cable news world section"),
    SourceDef("https://feeds.feedburner.com/breitbart", "Breitbart", Domain.WORLD, "right", "Right-nationalist US news aggregator"),
    SourceDef("https://www.washingtontimes.com/rss/headlines/news/world/", "Washington Times World", Domain.WORLD, "right", "Conservative US daily world coverage"),
    # WORLD — centre
    SourceDef("https://feeds.bbci.co.uk/news/world/rss.xml", "BBC World", Domain.WORLD, "centre", "British public broadcaster world news"),
    SourceDef("https://feeds.reuters.com/Reuters/worldNews", "Reuters World", Domain.WORLD, "centre", "Global wire service world feed"),
    SourceDef("https://feeds.npr.org/1004/rss.xml", "NPR World", Domain.WORLD, "centre", "US public radio world coverage"),
    # WORLD — state
    SourceDef("https://www.rt.com/rss/", "RT", Domain.WORLD, "state", "Russian state-funded international broadcaster"),
    SourceDef("https://tass.com/rss/v2.xml", "TASS", Domain.WORLD, "state", "Russian state news agency"),
    SourceDef("http://www.xinhuanet.com/english/rss/worldnews.xml", "Xinhua World", Domain.WORLD, "state", "Chinese state news agency world feed"),
    # MARKETS — left
    SourceDef("https://www.thenation.com/subject/economy/feed/", "The Nation Economy", Domain.MARKETS, "left", "Progressive US political magazine economy section"),
    SourceDef("https://www.commondreams.org/rss.xml", "Common Dreams", Domain.MARKETS, "left", "Progressive US news and opinion"),
    SourceDef("https://inthesetimes.com/feeds/recent_stories.rss", "In These Times", Domain.MARKETS, "left", "Independent US socialist magazine"),
    # MARKETS — right
    SourceDef("https://www.cnbc.com/id/100003114/device/rss/rss.html", "CNBC Markets", Domain.MARKETS, "right", "US business cable network markets feed"),
    SourceDef("https://feeds.marketwatch.com/marketwatch/topstories/", "MarketWatch", Domain.MARKETS, "right", "Dow Jones market news and analysis"),
    SourceDef("https://www.investors.com/category/market-trend/stock-market-today/feed/", "Investor's Business Daily", Domain.MARKETS, "right", "Equity-focused conservative market coverage"),
    # MARKETS — centre
    SourceDef("https://feeds.reuters.com/reuters/businessNews", "Reuters Business", Domain.MARKETS, "centre", "Reuters wire service business feed"),
    SourceDef("https://finance.yahoo.com/news/rssindex", "Yahoo Finance", Domain.MARKETS, "centre", "Aggregated financial news headlines"),
    SourceDef("https://rss.nytimes.com/services/xml/rss/nyt/Business.xml", "NYT Business", Domain.MARKETS, "centre", "New York Times business section"),
    # MARKETS — state
    SourceDef("https://www.rt.com/rss/business/", "RT Business", Domain.MARKETS, "state", "Russian state broadcaster business feed"),
    SourceDef("http://en.people.cn/rss/90778.xml", "People's Daily Economy", Domain.MARKETS, "state", "Chinese Communist Party organ economy feed"),
    SourceDef("https://www.chinadaily.com.cn/rss/bizchina_rss.xml", "China Daily Business", Domain.MARKETS, "state", "Chinese state English-language business"),
    # AI — left
    SourceDef("https://www.eff.org/rss/updates.xml", "EFF Updates", Domain.AI, "left", "Electronic Frontier Foundation civil-liberties tech coverage"),
    SourceDef("https://algorithmwatch.org/en/feed/", "AlgorithmWatch", Domain.AI, "left", "Critical algorithmic-accountability journalism"),
    SourceDef("https://theintercept.com/feed/?rss", "The Intercept Tech", Domain.AI, "left", "Investigative left-leaning tech and surveillance coverage"),
    # AI — right
    SourceDef("https://reason.com/feed/", "Reason", Domain.AI, "right", "Libertarian magazine — pro-market tech and AI policy"),
    SourceDef("https://www.forbes.com/technology/feed/", "Forbes Tech", Domain.AI, "right", "Business-conservative US tech and AI news"),
    SourceDef("https://www.washingtonexaminer.com/tag/technology/feed/", "Washington Examiner Tech", Domain.AI, "right", "Conservative US political outlet tech section"),
    # AI — centre
    SourceDef("https://feeds.arstechnica.com/arstechnica/index", "Ars Technica", Domain.AI, "centre", "In-depth tech journalism and AI coverage"),
    SourceDef("https://www.technologyreview.com/feed/", "MIT Technology Review", Domain.AI, "centre", "MIT-affiliated technology and AI research journalism"),
    SourceDef("https://venturebeat.com/feed/", "VentureBeat", Domain.AI, "centre", "Enterprise AI and tech startup news"),
    # AI — state
    SourceDef("https://www.rt.com/rss/technology/", "RT Technology", Domain.AI, "state", "Russian state broadcaster technology feed"),
    SourceDef("https://www.globaltimes.cn/rss/outbrain.xml", "Global Times", Domain.AI, "state", "Chinese state-backed English tabloid"),
    SourceDef("https://www.cgtn.com/subscribe/rss/section/sci-tech.xml", "CGTN Sci-Tech", Domain.AI, "state", "Chinese state television science and tech feed"),
    # WORLD — left (multilingual)
    SourceDef("https://www.lemonde.fr/rss/une.xml", "Le Monde", Domain.WORLD, "left", "French centre-left broadsheet world edition"),
    SourceDef("https://www.fr.de/rssfeed.rdf", "Frankfurter Rundschau", Domain.WORLD, "left", "German centre-left daily newspaper"),
    # WORLD — right (multilingual)
    SourceDef("https://www.lefigaro.fr/rss/figaro_actualites.xml", "Le Figaro", Domain.WORLD, "right", "French right-wing daily newspaper"),
    SourceDef("https://www.elmundo.es/rss/portada.xml", "El Mundo", Domain.WORLD, "right", "Spanish right-wing daily newspaper"),
    # WORLD — centre (multilingual)
    SourceDef("https://www.spiegel.de/international/index.rss", "Der Spiegel International", Domain.WORLD, "centre", "German liberal news magazine English edition"),
    SourceDef("https://www.japantimes.co.jp/feed/", "The Japan Times", Domain.WORLD, "centre", "Japanese English-language centre daily"),
    SourceDef("https://www.ansa.it/sito/ansait_rss.xml", "ANSA", Domain.WORLD, "centre", "Italian state wire agency general news feed"),
    # WORLD — state (multilingual)
    SourceDef("https://www.france24.com/en/rss", "France 24", Domain.WORLD, "state", "French state international broadcaster"),
    SourceDef("https://en.irna.ir/rss", "IRNA", Domain.WORLD, "state", "Persian/Iranian state news agency English feed"),
    # MARKETS — left (multilingual)
    SourceDef("https://www.cartacapital.com.br/feed/", "Carta Capital", Domain.MARKETS, "left", "Brazilian Portuguese left-wing political and economic weekly"),
    SourceDef("https://www.lamarea.com/feed/", "La Marea", Domain.MARKETS, "left", "Spanish independent left-wing weekly"),
    # MARKETS — right (multilingual)
    SourceDef("https://feeds.cms.handelsblatt.com/schlagzeilen", "Handelsblatt", Domain.MARKETS, "right", "German pro-business daily newspaper"),
    SourceDef("https://asia.nikkei.com/rss/feed/nar", "Nikkei Asia", Domain.MARKETS, "right", "Japanese financial newspaper Asia edition"),
    # MARKETS — centre (multilingual)
    SourceDef("https://feeds.folha.uol.com.br/mercado/rss091.xml", "Folha de S.Paulo Mercado", Domain.MARKETS, "centre", "Brazilian Portuguese centre daily business section"),
    SourceDef("https://www.dailysabah.com/rss/economy", "Daily Sabah Economy", Domain.MARKETS, "centre", "Turkish state-aligned newspaper economy section"),
    # MARKETS — state (multilingual)
    SourceDef("https://www.arabnews.com/rss.xml", "Arab News", Domain.MARKETS, "state", "Arabic Saudi-based state-affiliated English news"),
    SourceDef("https://rss.dw.com/rdf/rss-en-business", "DW Business", Domain.MARKETS, "state", "German state international broadcaster business feed"),
    # AI — left (multilingual)
    SourceDef("https://netzpolitik.org/feed/", "Netzpolitik.org", Domain.AI, "left", "German digital-rights journalism and policy"),
    SourceDef("https://www.laquadrature.net/feed/", "La Quadrature du Net", Domain.AI, "left", "French digital civil liberties advocacy organisation"),
    # AI — right (multilingual)
    SourceDef("https://www.lefigaro.fr/rss/figaro_sciences.xml", "Le Figaro Sciences", Domain.AI, "right", "French right-wing daily science and technology section"),
    SourceDef("https://rss.elconfidencial.com/tecnologia/", "El Confidencial Tech", Domain.AI, "right", "Spanish centre-right digital newspaper technology section"),
    # AI — centre (multilingual)
    SourceDef("https://www.heise.de/rss/heise.rdf", "Heise Online", Domain.AI, "centre", "German technology journalism and IT news"),
    SourceDef("https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/tecnologia/portada", "El País Tecnología", Domain.AI, "centre", "Spanish centre-left broadsheet technology section"),
    # AI — state (multilingual)
    SourceDef("https://rss.dw.com/rdf/rss-en-sci_tech", "DW Sci-Tech", Domain.AI, "state", "German state international broadcaster science and technology"),
    SourceDef("https://www.dailysabah.com/rss/technology", "Daily Sabah Tech", Domain.AI, "state", "Turkish state-aligned newspaper technology section"),
]


@dataclass
class Config:
    sources: list[str] = field(default_factory=list)
    fetch_interval_seconds: int = 3600
    max_articles_per_digest: int = 20
    digest_output_dir: str = "digests"
    log_level: str = "INFO"
    anthropic_model: str = "claude-sonnet-4-6"
    state_file: Optional[str] = None
    poll_interval_seconds: int = 600
    alert_threshold: float = 0.8
    llm_backend: str = "claude"
    ollama_model: str = "llama3"
    ollama_url: str = "http://localhost:11434"
    polymarket_markets: list = field(default_factory=list)
    polymarket_slugs: list[str] = field(default_factory=list)
    dashboard_port: int = 8080
    topics: list[str] = field(default_factory=list)
    source_defs: list[SourceDef] = field(default_factory=list)
    telegram_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    def __repr__(self) -> str:
        return (
            f"Config(sources={self.sources!r}, "
            f"fetch_interval_seconds={self.fetch_interval_seconds}, "
            f"max_articles_per_digest={self.max_articles_per_digest}, "
            f"digest_output_dir={self.digest_output_dir!r}, "
            f"log_level={self.log_level!r}, "
            f"anthropic_model={self.anthropic_model!r})"
        )

    @classmethod
    def from_defaults(cls) -> "Config":
        return cls()

    @classmethod
    def from_file(cls, path: str | Path) -> "Config":
        path = Path(path)
        with path.open() as fh:
            data: dict = json.load(fh)
        if "source_defs" in data:
            data["source_defs"] = [
                SourceDef(
                    url=sd["url"],
                    name=sd["name"],
                    domain=Domain[sd["domain"].upper()],
                    lens=sd["lens"],
                    description=sd.get("description", ""),
                    auth_platform=sd.get("auth_platform"),
                )
                for sd in data["source_defs"]
            ]
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def credential_registry(self) -> CredentialRegistry:
        return CredentialRegistry.load_from_env()

    @classmethod
    def from_env(cls) -> "Config":
        kwargs: dict = {}
        if (v := os.environ.get("SM_FETCH_INTERVAL")):
            kwargs["fetch_interval_seconds"] = int(v)
        if (v := os.environ.get("SM_MAX_ARTICLES")):
            kwargs["max_articles_per_digest"] = int(v)
        if (v := os.environ.get("SM_DIGEST_DIR")):
            kwargs["digest_output_dir"] = v
        if (v := os.environ.get("SM_LOG_LEVEL")):
            kwargs["log_level"] = v
        if (v := os.environ.get("SM_MODEL")):
            kwargs["anthropic_model"] = v
        if (v := os.environ.get("SM_STATE_FILE")):
            kwargs["state_file"] = v
        if (v := os.environ.get("SM_SOURCES")):
            kwargs["sources"] = [s.strip() for s in v.split(",") if s.strip()]
        if (v := os.environ.get("SM_POLL_INTERVAL")):
            kwargs["poll_interval_seconds"] = int(v)
        if (v := os.environ.get("SM_ALERT_THRESHOLD")):
            kwargs["alert_threshold"] = float(v)
        if (v := os.environ.get("SM_LLM_BACKEND")):
            kwargs["llm_backend"] = v
        if (v := os.environ.get("SM_OLLAMA_MODEL")):
            kwargs["ollama_model"] = v
        if (v := os.environ.get("SM_OLLAMA_URL")):
            kwargs["ollama_url"] = v
        if (v := os.environ.get("SM_DASHBOARD_PORT")):
            kwargs["dashboard_port"] = int(v)
        if (v := os.environ.get("SM_POLYMARKET_MARKETS")):
            kwargs["polymarket_markets"] = [s.strip() for s in v.split(",") if s.strip()]
        if (v := os.environ.get("SM_POLYMARKET_SLUGS")):
            kwargs["polymarket_slugs"] = [s.strip() for s in v.split(",") if s.strip()]
        if (v := os.environ.get("SM_TELEGRAM_TOKEN")):
            kwargs["telegram_token"] = v
        if (v := os.environ.get("SM_TELEGRAM_CHAT_ID")):
            kwargs["telegram_chat_id"] = v
        return cls(**kwargs)

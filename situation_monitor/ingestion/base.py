"""Abstract Fetcher base and default HTTP client."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from situation_monitor.models import Article
from situation_monitor.ingestion.http_client import ScrapingClient


class HttpClient(Protocol):
    def get(self, url: str) -> bytes: ...


class Fetcher(ABC):
    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client if client is not None else ScrapingClient()

    @abstractmethod
    def fetch(self, url: str) -> list[Article]: ...

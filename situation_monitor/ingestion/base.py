"""Abstract Fetcher base and default HTTP client."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Protocol

from situation_monitor.models import Article


class HttpClient(Protocol):
    def get(self, url: str) -> bytes: ...


class _DefaultClient:
    def get(self, url: str) -> bytes:
        import urllib.request

        with urllib.request.urlopen(url, timeout=30) as resp:
            return resp.read()


class Fetcher(ABC):
    def __init__(self, client: HttpClient | None = None) -> None:
        self._client = client if client is not None else _DefaultClient()

    @abstractmethod
    def fetch(self, url: str) -> list[Article]: ...

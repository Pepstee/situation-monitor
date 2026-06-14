"""Scraping HTTP client with retry logic and browser-like headers."""

from __future__ import annotations

import time

import httpx

_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_RETRYABLE = frozenset({429, 500, 502, 503, 504})


class ScrapingClient:
    def __init__(self, timeout: float = 30.0, max_retries: int = 3) -> None:
        self._timeout = timeout
        self._max_retries = max_retries

    def get(self, url: str) -> bytes:
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = httpx.get(url, headers=headers, timeout=self._timeout, follow_redirects=True)
                if resp.status_code in _RETRYABLE and attempt < self._max_retries:
                    time.sleep(2**attempt)
                    continue
                resp.raise_for_status()
                return resp.content
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code in _RETRYABLE and attempt < self._max_retries:
                    last_exc = exc
                    time.sleep(2**attempt)
                else:
                    raise
            except httpx.TransportError as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    time.sleep(2**attempt)
                else:
                    raise
        raise RuntimeError(f"All retries exhausted for {url}") from last_exc

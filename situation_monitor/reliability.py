"""Per-source reliability tracker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


class ReliabilityTracker:
    """Track fetch counts per source and derive a reliability label."""

    def __init__(self) -> None:
        # source -> [fetch_count, total_articles]
        self._data: dict[str, list[int]] = {}

    def record_fetch(self, source: str, count: int) -> None:
        if source not in self._data:
            self._data[source] = [0, 0]
        self._data[source][0] += 1
        self._data[source][1] += count

    def get_tracked_reliability(self, source: str) -> Optional[str]:
        if source not in self._data:
            return None
        fetches, total = self._data[source]
        if fetches == 0:
            return None
        avg = total / fetches
        if avg >= 5:
            return "high"
        if avg >= 1:
            return "medium"
        return "low"

    def load(self, path: str) -> None:
        try:
            raw = json.loads(Path(path).read_text())
            self._data = {k: list(v) for k, v in raw.items()}
        except (FileNotFoundError, json.JSONDecodeError, TypeError, ValueError):
            pass

    def save(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._data, indent=2))

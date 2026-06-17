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
        entry = self._data.get(source)
        if not isinstance(entry, list) or len(entry) != 2:
            return None
        fetches, total = entry
        if not isinstance(fetches, (int, float)) or not isinstance(total, (int, float)):
            return None
        if fetches == 0:
            return None
        avg = total / fetches
        if avg >= 5:
            return "high"
        if avg >= 1:
            return "medium"
        return "low"

    @staticmethod
    def _coerce_pair(value: object) -> Optional[list[int]]:
        """Accept only a clean [fetch_count, total_articles] integer pair."""
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return None
        fetches, total = value
        # Reject bools and non-numerics; coerce clean numerics to int.
        if isinstance(fetches, bool) or isinstance(total, bool):
            return None
        if not isinstance(fetches, (int, float)) or not isinstance(total, (int, float)):
            return None
        return [int(fetches), int(total)]

    def load(self, path: str) -> None:
        try:
            raw = json.loads(Path(path).read_text())
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return
        if not isinstance(raw, dict):
            return
        cleaned: dict[str, list[int]] = {}
        for key, value in raw.items():
            if not isinstance(key, str):
                continue
            pair = self._coerce_pair(value)
            if pair is not None:
                cleaned[key] = pair
        self._data = cleaned

    def save(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self._data, indent=2))

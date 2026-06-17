from __future__ import annotations

import os

from situation_monitor.auth.platforms import KNOWN_PLATFORMS


class CredentialRegistry:
    def __init__(self, presence: dict[str, set[str]]) -> None:
        # only stores which vars are present, not their values
        self._presence = presence

    @classmethod
    def load_from_env(cls) -> "CredentialRegistry":
        presence: dict[str, set[str]] = {}
        for platform_id, platform in KNOWN_PLATFORMS.items():
            all_vars = platform.required_env_vars + platform.optional_env_vars
            present = {v for v in all_vars if os.environ.get(v)}
            presence[platform_id] = present
        return cls(presence)

    def has(self, platform_id: str) -> bool:
        platform = KNOWN_PLATFORMS.get(platform_id)
        if platform is None:
            return False
        required = set(platform.required_env_vars)
        return required.issubset(self._presence.get(platform_id, set()))

    def get_env_values(self, platform_id: str) -> dict[str, str | None]:
        platform = KNOWN_PLATFORMS.get(platform_id)
        if platform is None:
            return {}
        all_vars = platform.required_env_vars + platform.optional_env_vars
        return {v: os.environ.get(v) for v in all_vars}

    def status_report(self) -> list[dict]:
        report = []
        for platform_id, platform in KNOWN_PLATFORMS.items():
            present_vars = self._presence.get(platform_id, set())
            missing = [v for v in platform.required_env_vars if v not in present_vars]
            report.append(
                {
                    "platform": platform_id,
                    "present": len(missing) == 0,
                    "missing_vars": missing,
                }
            )
        return report

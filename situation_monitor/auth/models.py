from __future__ import annotations

import enum
from dataclasses import dataclass, field


class AuthType(enum.Enum):
    BEARER_TOKEN = "bearer_token"
    SESSION_COOKIE = "session_cookie"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"


@dataclass(frozen=True)
class PlatformDef:
    platform_id: str
    display_name: str
    auth_type: AuthType
    required_env_vars: list[str] = field(default_factory=list)
    optional_env_vars: list[str] = field(default_factory=list)
    description: str = ""

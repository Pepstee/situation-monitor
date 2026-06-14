from __future__ import annotations

from situation_monitor.auth.models import AuthType, PlatformDef

KNOWN_PLATFORMS: dict[str, PlatformDef] = {
    "twitter": PlatformDef(
        platform_id="twitter",
        display_name="Twitter / X",
        auth_type=AuthType.BEARER_TOKEN,
        required_env_vars=["SM_AUTH_TWITTER_BEARER_TOKEN"],
        optional_env_vars=[
            "SM_AUTH_TWITTER_API_KEY",
            "SM_AUTH_TWITTER_API_SECRET",
            "SM_AUTH_TWITTER_ACCESS_TOKEN",
            "SM_AUTH_TWITTER_ACCESS_TOKEN_SECRET",
        ],
        description="Twitter/X API v2 bearer token authentication.",
    ),
    "threads": PlatformDef(
        platform_id="threads",
        display_name="Threads",
        auth_type=AuthType.OAUTH2,
        required_env_vars=[
            "SM_AUTH_THREADS_ACCESS_TOKEN",
            "SM_AUTH_THREADS_APP_ID",
            "SM_AUTH_THREADS_APP_SECRET",
        ],
        optional_env_vars=[],
        description="Threads API OAuth2 access token.",
    ),
    "instagram": PlatformDef(
        platform_id="instagram",
        display_name="Instagram",
        auth_type=AuthType.OAUTH2,
        required_env_vars=[
            "SM_AUTH_INSTAGRAM_ACCESS_TOKEN",
            "SM_AUTH_INSTAGRAM_APP_ID",
            "SM_AUTH_INSTAGRAM_APP_SECRET",
        ],
        optional_env_vars=["SM_AUTH_INSTAGRAM_USER_ID"],
        description="Instagram Graph API OAuth2 access token.",
    ),
    "facebook": PlatformDef(
        platform_id="facebook",
        display_name="Facebook",
        auth_type=AuthType.OAUTH2,
        required_env_vars=[
            "SM_AUTH_FACEBOOK_ACCESS_TOKEN",
            "SM_AUTH_FACEBOOK_APP_ID",
            "SM_AUTH_FACEBOOK_APP_SECRET",
        ],
        optional_env_vars=["SM_AUTH_FACEBOOK_PAGE_ID"],
        description="Facebook Graph API OAuth2 access token.",
    ),
    "linkedin": PlatformDef(
        platform_id="linkedin",
        display_name="LinkedIn",
        auth_type=AuthType.OAUTH2,
        required_env_vars=[
            "SM_AUTH_LINKEDIN_ACCESS_TOKEN",
            "SM_AUTH_LINKEDIN_CLIENT_ID",
            "SM_AUTH_LINKEDIN_CLIENT_SECRET",
        ],
        optional_env_vars=["SM_AUTH_LINKEDIN_ORG_ID"],
        description="LinkedIn API OAuth2 access token.",
    ),
}

"""Adversarial tests for situation_monitor.auth.models and auth.platforms.

Covers:
- AuthType enum exhaustiveness and values
- PlatformDef construction, immutability, and field defaults
- KNOWN_PLATFORMS: presence of all five required platforms, non-empty required_env_vars
"""
from __future__ import annotations

import pytest

from situation_monitor.auth.models import AuthType, PlatformDef
from situation_monitor.auth.platforms import KNOWN_PLATFORMS

REQUIRED_PLATFORMS = {"twitter", "threads", "instagram", "facebook", "linkedin"}


# ---------------------------------------------------------------------------
# AuthType
# ---------------------------------------------------------------------------


def test_auth_type_has_bearer_token():
    assert AuthType.BEARER_TOKEN.value == "bearer_token"


def test_auth_type_has_session_cookie():
    assert AuthType.SESSION_COOKIE.value == "session_cookie"


def test_auth_type_has_api_key():
    assert AuthType.API_KEY.value == "api_key"


def test_auth_type_has_oauth2():
    assert AuthType.OAUTH2.value == "oauth2"


def test_auth_type_exhaustive_values():
    values = {m.value for m in AuthType}
    assert values == {"bearer_token", "session_cookie", "api_key", "oauth2"}


def test_auth_type_members_are_distinct():
    members = list(AuthType)
    assert len(members) == len(set(members))


def test_auth_type_lookup_by_value():
    assert AuthType("bearer_token") is AuthType.BEARER_TOKEN
    assert AuthType("oauth2") is AuthType.OAUTH2


def test_auth_type_invalid_value_raises():
    with pytest.raises(ValueError):
        AuthType("nonexistent")


# ---------------------------------------------------------------------------
# PlatformDef construction
# ---------------------------------------------------------------------------


def test_platform_def_minimal_construction():
    p = PlatformDef(
        platform_id="test",
        display_name="Test",
        auth_type=AuthType.API_KEY,
    )
    assert p.platform_id == "test"
    assert p.display_name == "Test"
    assert p.auth_type is AuthType.API_KEY
    assert p.required_env_vars == []
    assert p.optional_env_vars == []
    assert p.description == ""


def test_platform_def_full_construction():
    p = PlatformDef(
        platform_id="myplatform",
        display_name="My Platform",
        auth_type=AuthType.BEARER_TOKEN,
        required_env_vars=["MY_TOKEN"],
        optional_env_vars=["MY_EXTRA"],
        description="Test platform.",
    )
    assert p.required_env_vars == ["MY_TOKEN"]
    assert p.optional_env_vars == ["MY_EXTRA"]
    assert p.description == "Test platform."


def test_platform_def_is_frozen():
    p = PlatformDef(
        platform_id="frozen",
        display_name="Frozen",
        auth_type=AuthType.OAUTH2,
    )
    with pytest.raises((AttributeError, TypeError)):
        p.platform_id = "modified"  # type: ignore[misc]


def test_platform_def_default_lists_are_independent():
    # Two instances must not share the same list object.
    p1 = PlatformDef(platform_id="a", display_name="A", auth_type=AuthType.API_KEY)
    p2 = PlatformDef(platform_id="b", display_name="B", auth_type=AuthType.API_KEY)
    assert p1.required_env_vars is not p2.required_env_vars
    assert p1.optional_env_vars is not p2.optional_env_vars


def test_platform_def_equality_is_value_based():
    p1 = PlatformDef(platform_id="x", display_name="X", auth_type=AuthType.OAUTH2)
    p2 = PlatformDef(platform_id="x", display_name="X", auth_type=AuthType.OAUTH2)
    assert p1 == p2


def test_platform_def_inequality_on_different_id():
    p1 = PlatformDef(platform_id="a", display_name="Same", auth_type=AuthType.OAUTH2)
    p2 = PlatformDef(platform_id="b", display_name="Same", auth_type=AuthType.OAUTH2)
    assert p1 != p2


# ---------------------------------------------------------------------------
# KNOWN_PLATFORMS
# ---------------------------------------------------------------------------


def test_known_platforms_contains_all_five():
    assert REQUIRED_PLATFORMS.issubset(KNOWN_PLATFORMS.keys()), (
        f"Missing platforms: {REQUIRED_PLATFORMS - KNOWN_PLATFORMS.keys()}"
    )


@pytest.mark.parametrize("platform_id", sorted(REQUIRED_PLATFORMS))
def test_known_platforms_each_has_non_empty_required_env_vars(platform_id):
    platform = KNOWN_PLATFORMS[platform_id]
    assert platform.required_env_vars, (
        f"Platform '{platform_id}' has no required_env_vars"
    )


@pytest.mark.parametrize("platform_id", sorted(REQUIRED_PLATFORMS))
def test_known_platforms_platform_id_matches_key(platform_id):
    platform = KNOWN_PLATFORMS[platform_id]
    assert platform.platform_id == platform_id


@pytest.mark.parametrize("platform_id", sorted(REQUIRED_PLATFORMS))
def test_known_platforms_each_has_display_name(platform_id):
    platform = KNOWN_PLATFORMS[platform_id]
    assert platform.display_name.strip()


@pytest.mark.parametrize("platform_id", sorted(REQUIRED_PLATFORMS))
def test_known_platforms_env_var_names_are_strings(platform_id):
    platform = KNOWN_PLATFORMS[platform_id]
    for var in platform.required_env_vars + platform.optional_env_vars:
        assert isinstance(var, str) and var.strip()


def test_twitter_uses_bearer_token_auth():
    assert KNOWN_PLATFORMS["twitter"].auth_type is AuthType.BEARER_TOKEN


def test_threads_uses_oauth2():
    assert KNOWN_PLATFORMS["threads"].auth_type is AuthType.OAUTH2


def test_instagram_uses_oauth2():
    assert KNOWN_PLATFORMS["instagram"].auth_type is AuthType.OAUTH2


def test_facebook_uses_oauth2():
    assert KNOWN_PLATFORMS["facebook"].auth_type is AuthType.OAUTH2


def test_linkedin_uses_oauth2():
    assert KNOWN_PLATFORMS["linkedin"].auth_type is AuthType.OAUTH2


def test_known_platforms_env_vars_have_no_duplicates_per_platform():
    for platform_id, platform in KNOWN_PLATFORMS.items():
        all_vars = platform.required_env_vars + platform.optional_env_vars
        assert len(all_vars) == len(set(all_vars)), (
            f"Platform '{platform_id}' has duplicate env var names"
        )


def test_known_platforms_all_values_are_platform_defs():
    for key, value in KNOWN_PLATFORMS.items():
        assert isinstance(value, PlatformDef), f"Value for '{key}' is not a PlatformDef"

"""Adversarial tests for situation_monitor.auth.registry.CredentialRegistry.

Covers:
- load_from_env: detects credential when required env var is present (monkeypatch)
- has(): True only when ALL required vars present, False otherwise, False for unknown platform
- status_report(): lists missing required vars, reports per-platform presence
- No secret values appear in status_report output
"""
from __future__ import annotations

import os

import pytest

from situation_monitor.auth.models import PlatformDef, AuthType
from situation_monitor.auth.platforms import KNOWN_PLATFORMS
from situation_monitor.auth.registry import CredentialRegistry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TWITTER_REQUIRED = KNOWN_PLATFORMS["twitter"].required_env_vars   # ["SM_AUTH_TWITTER_BEARER_TOKEN"]
THREADS_REQUIRED = KNOWN_PLATFORMS["threads"].required_env_vars   # three vars
LINKEDIN_REQUIRED = KNOWN_PLATFORMS["linkedin"].required_env_vars


# ---------------------------------------------------------------------------
# load_from_env
# ---------------------------------------------------------------------------


def test_load_from_env_detects_present_twitter_credential(monkeypatch):
    for var in TWITTER_REQUIRED:
        monkeypatch.setenv(var, "secret-value")
    registry = CredentialRegistry.load_from_env()
    assert registry.has("twitter"), "Expected twitter credentials to be detected"


def test_load_from_env_absent_when_no_vars_set(monkeypatch):
    for var in TWITTER_REQUIRED:
        monkeypatch.delenv(var, raising=False)
    registry = CredentialRegistry.load_from_env()
    assert not registry.has("twitter")


def test_load_from_env_partial_required_vars_means_absent(monkeypatch):
    # threads needs three vars; only set two
    required = THREADS_REQUIRED
    assert len(required) >= 2, "test assumption: threads has >=2 required vars"
    for var in required:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv(required[0], "partial-value")
    monkeypatch.setenv(required[1], "partial-value")
    # leave required[2] absent
    registry = CredentialRegistry.load_from_env()
    assert not registry.has("threads")


def test_load_from_env_all_platforms_present_when_all_vars_set(monkeypatch):
    for platform in KNOWN_PLATFORMS.values():
        for var in platform.required_env_vars:
            monkeypatch.setenv(var, "x")
    registry = CredentialRegistry.load_from_env()
    for pid in KNOWN_PLATFORMS:
        assert registry.has(pid), f"Expected {pid} to be detected"


def test_load_from_env_does_not_store_values():
    # CredentialRegistry only stores which vars ARE present, not their contents.
    # The _presence attribute should be a dict of sets of var names, not values.
    registry = CredentialRegistry.load_from_env()
    for pid, present_set in registry._presence.items():
        for item in present_set:
            assert isinstance(item, str), "presence set should hold var names, not values"
            # A var name should look like an env var identifier (uppercase, underscores)
            assert item.upper() == item or "_" in item, (
                f"Suspicious presence value: {item!r}"
            )


# ---------------------------------------------------------------------------
# has()
# ---------------------------------------------------------------------------


def test_has_returns_false_for_unknown_platform():
    registry = CredentialRegistry.load_from_env()
    assert not registry.has("nonexistent_platform_xyz")


def test_has_returns_false_for_empty_string_platform():
    registry = CredentialRegistry.load_from_env()
    assert not registry.has("")


def test_has_returns_true_only_when_all_required_present(monkeypatch):
    required = LINKEDIN_REQUIRED
    for var in required:
        monkeypatch.delenv(var, raising=False)
    # Set all but last
    for var in required[:-1]:
        monkeypatch.setenv(var, "v")
    registry = CredentialRegistry.load_from_env()
    assert not registry.has("linkedin"), "Should be False when one required var is missing"

    monkeypatch.setenv(required[-1], "v")
    registry2 = CredentialRegistry.load_from_env()
    assert registry2.has("linkedin"), "Should be True when all required vars are set"


def test_has_is_not_satisfied_by_optional_var_alone(monkeypatch):
    # Twitter has optional vars but they should NOT satisfy has() without the required token.
    optional = KNOWN_PLATFORMS["twitter"].optional_env_vars
    required = TWITTER_REQUIRED
    for var in required:
        monkeypatch.delenv(var, raising=False)
    for var in optional:
        monkeypatch.setenv(var, "something")
    registry = CredentialRegistry.load_from_env()
    assert not registry.has("twitter"), "Optional vars alone must not satisfy has()"


def test_has_with_empty_string_env_var_does_not_count(monkeypatch):
    # os.environ.get(v) is truthy; empty string is falsy — should not count as present.
    for var in TWITTER_REQUIRED:
        monkeypatch.setenv(var, "")
    registry = CredentialRegistry.load_from_env()
    assert not registry.has("twitter"), "Empty env var must not satisfy has()"


# ---------------------------------------------------------------------------
# status_report()
# ---------------------------------------------------------------------------


def test_status_report_lists_all_known_platforms(monkeypatch):
    # Clear all auth vars so every platform appears in the report
    for platform in KNOWN_PLATFORMS.values():
        for var in platform.required_env_vars + platform.optional_env_vars:
            monkeypatch.delenv(var, raising=False)
    registry = CredentialRegistry.load_from_env()
    report = registry.status_report()
    reported_platforms = {entry["platform"] for entry in report}
    assert set(KNOWN_PLATFORMS.keys()).issubset(reported_platforms)


def test_status_report_missing_vars_listed_when_absent(monkeypatch):
    for var in TWITTER_REQUIRED:
        monkeypatch.delenv(var, raising=False)
    registry = CredentialRegistry.load_from_env()
    report = registry.status_report()
    twitter_entry = next(e for e in report if e["platform"] == "twitter")
    assert not twitter_entry["present"]
    assert set(TWITTER_REQUIRED).issubset(set(twitter_entry["missing_vars"]))


def test_status_report_no_missing_vars_when_all_present(monkeypatch):
    for var in TWITTER_REQUIRED:
        monkeypatch.setenv(var, "real-token")
    registry = CredentialRegistry.load_from_env()
    report = registry.status_report()
    twitter_entry = next(e for e in report if e["platform"] == "twitter")
    assert twitter_entry["present"]
    assert twitter_entry["missing_vars"] == []


def test_status_report_present_field_is_bool():
    registry = CredentialRegistry.load_from_env()
    for entry in registry.status_report():
        assert isinstance(entry["present"], bool)


def test_status_report_missing_vars_field_is_list():
    registry = CredentialRegistry.load_from_env()
    for entry in registry.status_report():
        assert isinstance(entry["missing_vars"], list)


def test_status_report_contains_no_secret_values(monkeypatch):
    secret = "SUPER_SECRET_TOKEN_VALUE_XYZ_12345"
    for var in TWITTER_REQUIRED:
        monkeypatch.setenv(var, secret)
    registry = CredentialRegistry.load_from_env()
    report = registry.status_report()
    # Stringify the entire report and check the secret does not appear
    report_str = str(report)
    assert secret not in report_str, (
        "Secret credential value must not appear in status_report output"
    )


def test_status_report_missing_vars_only_contains_var_names_not_values(monkeypatch):
    secret = "LEAK_CHECK_VALUE_ABC"
    for var in TWITTER_REQUIRED:
        monkeypatch.setenv(var, secret)
    # Now clear them to make them appear in missing_vars
    for var in TWITTER_REQUIRED:
        monkeypatch.delenv(var, raising=False)
    registry = CredentialRegistry.load_from_env()
    report = registry.status_report()
    twitter_entry = next(e for e in report if e["platform"] == "twitter")
    for item in twitter_entry["missing_vars"]:
        assert secret not in item


def test_status_report_missing_vars_are_actual_env_var_names(monkeypatch):
    for platform in KNOWN_PLATFORMS.values():
        for var in platform.required_env_vars + platform.optional_env_vars:
            monkeypatch.delenv(var, raising=False)
    registry = CredentialRegistry.load_from_env()
    for entry in registry.status_report():
        for var_name in entry["missing_vars"]:
            assert var_name.startswith("SM_AUTH_"), (
                f"Missing var {var_name!r} doesn't look like an SM_AUTH_ var"
            )


# ---------------------------------------------------------------------------
# Direct construction of CredentialRegistry (unit-level)
# ---------------------------------------------------------------------------


def test_registry_direct_construction_has_returns_true():
    required_vars = KNOWN_PLATFORMS["twitter"].required_env_vars
    presence = {"twitter": set(required_vars)}
    registry = CredentialRegistry(presence)
    assert registry.has("twitter")


def test_registry_direct_construction_has_returns_false_when_subset_missing():
    required_vars = KNOWN_PLATFORMS["threads"].required_env_vars
    # Only put first var in presence
    presence = {"threads": {required_vars[0]}}
    registry = CredentialRegistry(presence)
    assert not registry.has("threads")


def test_registry_direct_construction_empty_presence_all_false():
    registry = CredentialRegistry({})
    for pid in KNOWN_PLATFORMS:
        assert not registry.has(pid)

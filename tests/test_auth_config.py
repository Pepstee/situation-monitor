"""Adversarial tests for Config.from_file integration with SourceDef.auth_platform.

Covers:
- SourceDef round-trips auth_platform=None through Config.from_file
- SourceDef round-trips auth_platform='twitter' through Config.from_file
- source_defs absent from JSON still produces a Config (uses default empty list)
- Unknown domain in JSON raises KeyError
- auth_platform value is preserved exactly (no normalisation)
- Config.credential_registry() returns a CredentialRegistry (no network calls)
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from situation_monitor.config import Config, SourceDef
from situation_monitor.auth import CredentialRegistry
from situation_monitor.models import Domain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_json(data: dict) -> Path:
    """Write data to a temp JSON file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    )
    json.dump(data, tmp)
    tmp.close()
    return Path(tmp.name)


MINIMAL_SOURCE = {
    "url": "https://example.com/feed",
    "name": "Example",
    "domain": "world",
    "lens": "centre",
    "description": "A test source",
}


# ---------------------------------------------------------------------------
# auth_platform=None round-trip
# ---------------------------------------------------------------------------


def test_source_def_auth_platform_none_round_trips():
    source = {**MINIMAL_SOURCE, "auth_platform": None}
    path = _write_json({"source_defs": [source]})
    config = Config.from_file(path)
    assert len(config.source_defs) == 1
    sd = config.source_defs[0]
    assert sd.auth_platform is None


def test_source_def_auth_platform_absent_defaults_to_none():
    # auth_platform not present in JSON at all — should default to None
    path = _write_json({"source_defs": [MINIMAL_SOURCE]})
    config = Config.from_file(path)
    sd = config.source_defs[0]
    assert sd.auth_platform is None


# ---------------------------------------------------------------------------
# auth_platform='twitter' round-trip
# ---------------------------------------------------------------------------


def test_source_def_auth_platform_twitter_round_trips():
    source = {**MINIMAL_SOURCE, "auth_platform": "twitter"}
    path = _write_json({"source_defs": [source]})
    config = Config.from_file(path)
    assert len(config.source_defs) == 1
    sd = config.source_defs[0]
    assert sd.auth_platform == "twitter"


def test_source_def_auth_platform_preserves_value_exactly():
    # The config must not normalise or validate the auth_platform string —
    # it stores whatever the JSON says.
    for platform_id in ("threads", "instagram", "facebook", "linkedin"):
        source = {**MINIMAL_SOURCE, "auth_platform": platform_id}
        path = _write_json({"source_defs": [source]})
        config = Config.from_file(path)
        assert config.source_defs[0].auth_platform == platform_id


# ---------------------------------------------------------------------------
# Mixed sources (None and 'twitter' together)
# ---------------------------------------------------------------------------


def test_mixed_auth_platform_sources_round_trip():
    sources = [
        {**MINIMAL_SOURCE, "url": "https://a.example/", "auth_platform": None},
        {**MINIMAL_SOURCE, "url": "https://b.example/", "auth_platform": "twitter"},
    ]
    path = _write_json({"source_defs": sources})
    config = Config.from_file(path)
    assert len(config.source_defs) == 2
    assert config.source_defs[0].auth_platform is None
    assert config.source_defs[1].auth_platform == "twitter"


# ---------------------------------------------------------------------------
# Other SourceDef fields are also round-tripped correctly
# ---------------------------------------------------------------------------


def test_source_def_url_and_name_preserved():
    source = {
        "url": "https://unique-url.example/rss",
        "name": "Unique Name",
        "domain": "ai",
        "lens": "left",
        "auth_platform": "linkedin",
    }
    path = _write_json({"source_defs": [source]})
    config = Config.from_file(path)
    sd = config.source_defs[0]
    assert sd.url == "https://unique-url.example/rss"
    assert sd.name == "Unique Name"
    assert sd.domain is Domain.AI
    assert sd.lens == "left"
    assert sd.auth_platform == "linkedin"


def test_source_def_domain_case_insensitive():
    # The config does Domain[sd["domain"].upper()] so lower/mixed case should work.
    for domain_str in ("world", "World", "WORLD", "markets", "ai"):
        source = {**MINIMAL_SOURCE, "domain": domain_str}
        path = _write_json({"source_defs": [source]})
        config = Config.from_file(path)
        assert config.source_defs[0].domain in Domain


# ---------------------------------------------------------------------------
# source_defs absent → empty list (default)
# ---------------------------------------------------------------------------


def test_config_from_file_no_source_defs_key_gives_empty_list():
    path = _write_json({})
    config = Config.from_file(path)
    assert config.source_defs == []


def test_config_from_file_empty_source_defs_array():
    path = _write_json({"source_defs": []})
    config = Config.from_file(path)
    assert config.source_defs == []


# ---------------------------------------------------------------------------
# Other config fields round-trip alongside source_defs
# ---------------------------------------------------------------------------


def test_config_from_file_other_fields_alongside_source_defs():
    data = {
        "fetch_interval_seconds": 1800,
        "log_level": "DEBUG",
        "source_defs": [
            {**MINIMAL_SOURCE, "auth_platform": "facebook"},
        ],
    }
    path = _write_json(data)
    config = Config.from_file(path)
    assert config.fetch_interval_seconds == 1800
    assert config.log_level == "DEBUG"
    assert config.source_defs[0].auth_platform == "facebook"


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


def test_config_from_file_bad_domain_raises():
    source = {**MINIMAL_SOURCE, "domain": "INVALID_DOMAIN_XYZ"}
    path = _write_json({"source_defs": [source]})
    with pytest.raises(KeyError):
        Config.from_file(path)


def test_config_from_file_missing_required_source_field_raises():
    # 'url' is required; omitting it should raise TypeError from SourceDef()
    source = {"name": "No URL", "domain": "world", "lens": "left"}
    path = _write_json({"source_defs": [source]})
    with pytest.raises((TypeError, KeyError)):
        Config.from_file(path)


def test_config_from_file_nonexistent_path_raises():
    with pytest.raises((FileNotFoundError, OSError)):
        Config.from_file("/tmp/definitely_does_not_exist_xyzabc123.json")


# ---------------------------------------------------------------------------
# credential_registry() integration (no network calls)
# ---------------------------------------------------------------------------


def test_config_credential_registry_returns_registry():
    config = Config.from_defaults()
    registry = config.credential_registry()
    assert isinstance(registry, CredentialRegistry)


def test_config_credential_registry_can_call_status_report():
    config = Config.from_defaults()
    registry = config.credential_registry()
    report = registry.status_report()
    assert isinstance(report, list)
    assert len(report) > 0


def test_config_credential_registry_no_platform_has_if_no_env_vars(monkeypatch):
    # Strip all SM_AUTH_* env vars to guarantee all platforms are absent.
    from situation_monitor.auth.platforms import KNOWN_PLATFORMS
    for platform in KNOWN_PLATFORMS.values():
        for var in platform.required_env_vars + platform.optional_env_vars:
            monkeypatch.delenv(var, raising=False)
    config = Config.from_defaults()
    registry = config.credential_registry()
    for pid in KNOWN_PLATFORMS:
        assert not registry.has(pid)

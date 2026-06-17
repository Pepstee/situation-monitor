"""Tests for build_dossier() in situation_monitor/dossier.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from situation_monitor.config import Config
from situation_monitor.dossier import ENTITY_ROSTER, EntityDossier, build_dossier
from situation_monitor.models import Article


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _article(
    title: str,
    source: str = "Test Source",
    body: str = "",
    url: str | None = None,
) -> Article:
    safe_url = url or f"https://example.com/{abs(hash(title)) % 10**9}"
    return Article(url=safe_url, title=title, source=source, body=body)


def _rss_bytes(title: str, link: str, source_title: str = "Test Feed") -> bytes:
    return (
        f'<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<title>{source_title}</title>"
        f"<item><title>{title}</title><link>{link}</link></item>"
        f"</channel></rss>"
    ).encode()


def _stub_llm(prompt: str) -> str:
    return "Acme Corp is a major industrial conglomerate."


def _config() -> Config:
    return Config()


# ---------------------------------------------------------------------------
# Acceptance criterion 1: returns EntityDossier without raising
# ---------------------------------------------------------------------------


class TestBuildDossierReturnsEntityDossier:
    def test_returns_entity_dossier_instance(self):
        cfg = _config()
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier("Acme Corp", cfg, _stub_llm)
        assert isinstance(result, EntityDossier)

    def test_entity_name_preserved(self):
        cfg = _config()
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier("Acme Corp", cfg, _stub_llm)
        assert result.entity == "Acme Corp"

    def test_sources_checked_equals_roster_size(self):
        cfg = _config()
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier("Acme Corp", cfg, _stub_llm)
        assert result.sources_checked == len(ENTITY_ROSTER)

    def test_does_not_raise_when_all_sources_return_empty(self):
        cfg = _config()
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier("Acme Corp", cfg, _stub_llm)
        assert result.articles_found == 0
        assert result.summaries == []


# ---------------------------------------------------------------------------
# Acceptance criterion 2: deduplicate() called on all fetched articles
# ---------------------------------------------------------------------------


class TestDeduplicateCalled:
    def test_deduplicate_called_before_summarisation(self):
        cfg = _config()
        articles = [_article("Acme Corp Q3 results beat expectations")]

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = articles
            with patch("situation_monitor.dossier.deduplicate", wraps=lambda x: x) as mock_dedup:
                build_dossier("Acme Corp", cfg, _stub_llm)
        mock_dedup.assert_called_once()

    def test_deduplicate_receives_all_articles_from_all_sources(self):
        cfg = _config()
        n_sources = len(ENTITY_ROSTER)
        articles_per_source = [
            _article(f"Acme Corp article from source {i}", url=f"https://src{i}.example.com/acme")
            for i in range(n_sources)
        ]

        call_count = 0

        def _fetch_one_per_source(url, source_def=None):
            nonlocal call_count
            idx = call_count % n_sources
            call_count += 1
            return [articles_per_source[idx]]

        collected: list[list[Article]] = []

        def _spy_dedup(arts):
            collected.append(list(arts))
            return arts

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = _fetch_one_per_source
            with patch("situation_monitor.dossier.deduplicate", side_effect=_spy_dedup):
                build_dossier("Acme Corp", cfg, _stub_llm)

        assert len(collected) == 1
        assert len(collected[0]) == n_sources

    def test_duplicate_articles_removed_before_count(self):
        cfg = _config()
        # Both sources return the same URL → dedup should collapse to 1
        dup = _article("Acme Corp merger announced today", url="https://example.com/acme-merger")

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = [dup]
            result = build_dossier("Acme Corp", cfg, _stub_llm)

        # articles_found reflects deduped count (URL seen many times = 1 unique)
        assert result.articles_found == 1


# ---------------------------------------------------------------------------
# Acceptance criterion 3: LLM failure → summaries=[], 'llm_unavailable' in flags
# ---------------------------------------------------------------------------


class TestLLMFailureHandling:
    def _articles_with_entity(self) -> list[Article]:
        return [_article("Acme Corp expands into Asian markets today")]

    def test_llm_raises_summaries_empty(self):
        cfg = _config()

        def _raising_llm(prompt: str) -> str:
            raise ConnectionError("ollama offline")

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier("Acme Corp", cfg, _raising_llm)

        assert result.summaries == []

    def test_llm_raises_llm_unavailable_in_flags(self):
        cfg = _config()

        def _raising_llm(prompt: str) -> str:
            raise RuntimeError("model not found")

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier("Acme Corp", cfg, _raising_llm)

        assert "llm_unavailable" in result.fabrication_flags

    def test_llm_returns_empty_string_summaries_empty(self):
        cfg = _config()

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier("Acme Corp", cfg, lambda p: "")

        assert result.summaries == []

    def test_llm_returns_empty_string_llm_unavailable_in_flags(self):
        cfg = _config()

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier("Acme Corp", cfg, lambda p: "")

        assert "llm_unavailable" in result.fabrication_flags

    def test_llm_returns_whitespace_only_treated_as_empty(self):
        cfg = _config()

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier("Acme Corp", cfg, lambda p: "   \n  ")

        assert result.summaries == []
        assert "llm_unavailable" in result.fabrication_flags

    def test_llm_success_populates_summaries(self):
        cfg = _config()

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier("Acme Corp", cfg, _stub_llm)

        assert len(result.summaries) == 1
        assert "Acme Corp" in result.summaries[0]

    def test_llm_success_no_fabrication_flags(self):
        cfg = _config()

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier("Acme Corp", cfg, _stub_llm)

        assert result.fabrication_flags == []


# ---------------------------------------------------------------------------
# Acceptance criterion 4: per-source failures caught; outage_sources accumulates
# ---------------------------------------------------------------------------


class TestPerSourceFailureHandling:
    def test_single_failing_source_in_outage_sources(self):
        cfg = _config()
        roster = list(ENTITY_ROSTER)
        fail_name = roster[0].name

        def _fetch(url, source_def=None):
            if source_def is not None and source_def.name == fail_name:
                raise OSError("connection refused")
            return []

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = _fetch
            result = build_dossier("Acme Corp", cfg, _stub_llm)

        assert fail_name in result.outage_sources

    def test_remaining_sources_processed_after_one_failure(self):
        cfg = _config()
        roster = list(ENTITY_ROSTER)
        fail_name = roster[0].name
        good_article = _article("Acme Corp good article from working source")

        def _fetch(url, source_def=None):
            if source_def is not None and source_def.name == fail_name:
                raise OSError("timeout")
            return [good_article]

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = _fetch
            result = build_dossier("Acme Corp", cfg, _stub_llm)

        # Only the one failing source in outage_sources
        assert result.outage_sources == [fail_name]
        # Remaining sources still contributed articles
        assert result.articles_found > 0

    def test_multiple_failing_sources_all_in_outage_sources(self):
        cfg = _config()
        roster = list(ENTITY_ROSTER)
        fail_names = {roster[0].name, roster[1].name}

        def _fetch(url, source_def=None):
            if source_def is not None and source_def.name in fail_names:
                raise ConnectionError("down")
            return []

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = _fetch
            result = build_dossier("Acme Corp", cfg, _stub_llm)

        for name in fail_names:
            assert name in result.outage_sources

    def test_all_sources_failing_returns_empty_dossier_not_raises(self):
        cfg = _config()

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = OSError("network down")
            result = build_dossier("Acme Corp", cfg, _stub_llm)

        assert isinstance(result, EntityDossier)
        assert len(result.outage_sources) == len(ENTITY_ROSTER)
        assert result.articles_found == 0
        assert result.summaries == []

    def test_no_outage_sources_when_all_succeed(self):
        cfg = _config()

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier("Acme Corp", cfg, _stub_llm)

        assert result.outage_sources == []

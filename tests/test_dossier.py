"""Adversarial tests for dossier.py: never-fabricate, dedup, total-outage, happy-path.

Covers all four acceptance criteria:
  1. LLM raises RuntimeError → summaries==[], 'llm_unavailable' in fabrication_flags
  2. Duplicate URLs → articles_found equals number of unique URLs
  3. All fetchers fail (total outage) → outage_sources==all names, articles_found==0
  4. Fixture RSS with entity name → articles_found>0 and summaries non-empty
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from situation_monitor.config import Config
from situation_monitor.dossier import ENTITY_ROSTER, EntityDossier, build_dossier
from situation_monitor.models import Article


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ENTITY = "Northgate Industries"


def _article(
    title: str,
    url: str | None = None,
    body: str = "",
    source: str = "Test Source",
) -> Article:
    safe_url = url or f"https://example.com/{abs(hash(title + source)) % 10**9}"
    return Article(url=safe_url, title=title, source=source, body=body)


def _rss_bytes(items: list[tuple[str, str]], feed_title: str = "Test Feed") -> bytes:
    """Minimal valid RSS 2.0 XML for a list of (title, link) pairs."""
    items_xml = "".join(
        f"<item><title>{t}</title><link>{l}</link></item>" for t, l in items
    )
    return (
        f'<?xml version="1.0"?><rss version="2.0"><channel>'
        f"<title>{feed_title}</title>"
        f"{items_xml}"
        f"</channel></rss>"
    ).encode()


def _stub_llm(prompt: str) -> str:
    return f"{_ENTITY} is a major infrastructure conglomerate with global operations."


def _config() -> Config:
    return Config()


class _StubHttpClient:
    """Returns identical RSS bytes for every URL — lets the real XML parser run."""

    def __init__(self, content: bytes) -> None:
        self._content = content

    def get(self, url: str) -> bytes:
        return self._content


# ---------------------------------------------------------------------------
# Blank-entity guard: an empty/whitespace entity must never match every
# article (empty substring matches everything) and must never be summarised —
# that would feed unrelated articles to the LLM and invite fabrication.
# ---------------------------------------------------------------------------


class TestBlankEntityNeverFabricates:
    def _unrelated_articles(self) -> list[Article]:
        return [
            _article("Totally unrelated headline", body="no entity here"),
            _article("Another off-topic story", body="still nothing relevant"),
        ]

    @pytest.mark.parametrize("blank", ["", "   ", "\t", "\n  \n"])
    def test_blank_entity_yields_no_summary(self, blank):
        def _would_fabricate(prompt: str) -> str:
            return "FABRICATED SUMMARY OF NOTHING"

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._unrelated_articles()
            result = build_dossier(blank, _config(), _would_fabricate)

        assert result.summaries == [], "blank entity must not be summarised"
        assert result.fabrication_flags == []


# ---------------------------------------------------------------------------
# Criterion 1: LLM raises RuntimeError → summaries==[], 'llm_unavailable' in flags
# ---------------------------------------------------------------------------


class TestLLMRuntimeError:
    """LLM failure must not fabricate content."""

    def _articles_with_entity(self) -> list[Article]:
        return [_article(f"{_ENTITY} signs record infrastructure deal")]

    def test_runtime_error_summaries_empty_and_flag_set(self):
        """Combined check: RuntimeError → summaries==[] AND 'llm_unavailable' flagged."""

        def _raising(prompt: str) -> str:
            raise RuntimeError("model not found")

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier(_ENTITY, _config(), _raising)

        assert result.summaries == [], "must not fabricate when LLM raises"
        assert "llm_unavailable" in result.fabrication_flags

    def test_runtime_error_returns_entity_dossier_not_raises(self):
        """RuntimeError from LLM must not propagate out of build_dossier."""

        def _raising(prompt: str) -> str:
            raise RuntimeError("GPU OOM")

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier(_ENTITY, _config(), _raising)

        assert isinstance(result, EntityDossier)

    def test_llm_empty_response_sets_unavailable_flag(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier(_ENTITY, _config(), lambda p: "")

        assert result.summaries == []
        assert "llm_unavailable" in result.fabrication_flags

    def test_llm_whitespace_response_sets_unavailable_flag(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier(_ENTITY, _config(), lambda p: "   \n\t  ")

        assert result.summaries == []
        assert "llm_unavailable" in result.fabrication_flags

    def test_success_no_fabrication_flags(self):
        """When LLM succeeds, fabrication_flags must remain empty."""
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert result.fabrication_flags == []

    def test_success_single_summary_entry(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert len(result.summaries) == 1
        assert result.summaries[0].strip() != ""

    def test_summary_is_stripped_of_surrounding_whitespace(self):
        def _padded(prompt: str) -> str:
            return f"  \n  {_ENTITY} operates in 40 countries.  \n  "

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = self._articles_with_entity()
            result = build_dossier(_ENTITY, _config(), _padded)

        assert result.summaries == [f"{_ENTITY} operates in 40 countries."]


# ---------------------------------------------------------------------------
# Criterion 2: Duplicate URLs → articles_found equals number of unique URLs
# ---------------------------------------------------------------------------


class TestDeduplication:
    """articles_found must count post-dedup articles, not raw fetched total."""

    def test_exact_url_duplicates_collapsed(self):
        """Two articles sharing a URL count as one."""
        shared_url = "https://news.example.com/ng-merger"
        original = _article(f"{_ENTITY} completes merger deal", url=shared_url)
        duplicate = _article(f"{_ENTITY} completes merger deal — update", url=shared_url)

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = [original, duplicate]
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert result.articles_found == 1

    def test_articles_found_equals_unique_url_count(self):
        """Three articles, one duplicate URL → articles_found == 2."""
        a = _article("First story", url="https://news.example.com/1")
        b = _article("Second story", url="https://news.example.com/2")
        b_dup = _article("Second story (copy)", url="https://news.example.com/2")

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = [a, b, b_dup]
            result = build_dossier("story", _config(), _stub_llm)

        assert result.articles_found == 2

    def test_all_unique_urls_none_collapsed(self):
        """Five articles with distinct URLs must all be counted."""
        articles = [
            _article(f"Story {i}", url=f"https://news.example.com/story-{i}")
            for i in range(5)
        ]
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = articles
            result = build_dossier("story", _config(), _stub_llm)

        assert result.articles_found == 5

    def test_near_duplicate_titles_also_deduplicated(self):
        """Same first-6-words title, different URLs → dedup treats as one."""
        base_title = f"{_ENTITY} reports record quarterly profits for investors"
        a = _article(base_title, url="https://src-a.com/ng")
        b = _article(base_title + " globally", url="https://src-b.com/ng")

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = [a, b]
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert result.articles_found == 1

    def test_many_identical_articles_across_sources(self):
        """When every source returns the same URL, articles_found must be 1."""
        same_url = "https://wire.example.com/ng-announcement"
        article = _article(f"{_ENTITY} major announcement", url=same_url)

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = [article]
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert result.articles_found == 1


# ---------------------------------------------------------------------------
# Criterion 3: Total outage → outage_sources == all source names, articles_found == 0
# ---------------------------------------------------------------------------


class TestTotalOutage:
    """Complete source failure must degrade gracefully without fabricating."""

    def test_all_sources_raise_outage_sources_equals_all_source_names(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = OSError("network unavailable")
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        expected_names = {sd.name for sd in ENTITY_ROSTER}
        assert set(result.outage_sources) == expected_names

    def test_all_sources_raise_articles_found_zero(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = ConnectionError("unreachable")
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert result.articles_found == 0

    def test_all_sources_raise_no_exception_propagates(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = RuntimeError("total outage")
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert isinstance(result, EntityDossier)

    def test_all_sources_raise_summaries_empty(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = OSError("down")
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert result.summaries == []

    def test_all_fetchers_return_empty_list_no_outage_sources(self):
        """Returning [] is a successful (empty) fetch — NOT an outage."""
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert result.outage_sources == []
        assert result.articles_found == 0

    def test_partial_outage_remaining_sources_still_contribute(self):
        """A single failing source must not block the rest."""
        roster = list(ENTITY_ROSTER)
        failing_name = roster[0].name
        good_article = _article(f"{_ENTITY} good article from working source")

        def _selective_fetch(url: str, source_def=None) -> list[Article]:
            if source_def is not None and source_def.name == failing_name:
                raise OSError("timeout")
            return [good_article]

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = _selective_fetch
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert result.outage_sources == [failing_name]
        assert result.articles_found > 0


# ---------------------------------------------------------------------------
# Criterion 4: Fixture RSS articles with entity name → articles_found>0, summaries non-empty
# ---------------------------------------------------------------------------


class TestHappyPathRSSFixture:
    """End-to-end: real XML parsing + real dedup + LLM stub → populated dossier."""

    def _rss_with_entity(self) -> bytes:
        return _rss_bytes([
            (f"{_ENTITY} secures major infrastructure contract", "https://news.com/ng-1"),
            (f"{_ENTITY} CEO addresses annual summit", "https://news.com/ng-2"),
            ("Unrelated story about renewable energy trends", "https://news.com/other-1"),
        ])

    def test_fixture_rss_articles_found_positive(self):
        """Real HTTP client mock + real RSS parser must produce articles_found > 0."""
        result = build_dossier(
            _ENTITY, _config(), _stub_llm, _client=_StubHttpClient(self._rss_with_entity())
        )
        assert result.articles_found > 0

    def test_fixture_rss_summaries_nonempty(self):
        """Entity-matching articles must trigger LLM and populate summaries."""
        result = build_dossier(
            _ENTITY, _config(), _stub_llm, _client=_StubHttpClient(self._rss_with_entity())
        )
        assert isinstance(result.summaries, list)
        assert len(result.summaries) > 0
        assert result.summaries[0].strip() != ""

    def test_fixture_rss_unrelated_articles_excluded_from_llm_prompt(self):
        """LLM prompt must contain entity-relevant articles only, not unrelated ones."""
        captured: list[str] = []

        def _capturing_llm(prompt: str) -> str:
            captured.append(prompt)
            return f"{_ENTITY} summary."

        build_dossier(
            _ENTITY,
            _config(),
            _capturing_llm,
            _client=_StubHttpClient(self._rss_with_entity()),
        )

        assert len(captured) == 1
        prompt = captured[0]
        assert _ENTITY.lower() in prompt.lower()
        assert "renewable energy trends" not in prompt.lower()

    def test_fixture_rss_no_entity_articles_summaries_empty(self):
        """RSS with no entity-mentioning articles → summaries stays empty."""
        no_match_rss = _rss_bytes([
            ("Global markets weekly roundup", "https://news.com/m-1"),
            ("Weather forecast for the week", "https://news.com/m-2"),
        ])
        result = build_dossier(
            _ENTITY, _config(), _stub_llm, _client=_StubHttpClient(no_match_rss)
        )
        assert result.summaries == []

    def test_fixture_rss_malformed_xml_does_not_raise(self):
        """Malformed RSS bytes must be silently discarded, not crash build_dossier."""
        result = build_dossier(
            _ENTITY,
            _config(),
            _stub_llm,
            _client=_StubHttpClient(b"<not valid xml at all >>>"),
        )
        assert isinstance(result, EntityDossier)
        assert result.articles_found == 0


# ---------------------------------------------------------------------------
# Adversarial: never-fabricate contract
# ---------------------------------------------------------------------------


class TestNeverFabricate:
    """The LLM must only be called when there is genuine entity-matching source material."""

    def test_no_relevant_articles_llm_never_called(self):
        call_count = 0

        def _counting_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return "Fabricated summary"

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = [
                _article("Unrelated article about widget markets")
            ]
            build_dossier(_ENTITY, _config(), _counting_llm)

        assert call_count == 0, "LLM must not be called with no entity-relevant articles"

    def test_empty_fetch_result_llm_never_called(self):
        call_count = 0

        def _counting_llm(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return "Fabricated"

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            build_dossier(_ENTITY, _config(), _counting_llm)

        assert call_count == 0

    def test_entity_match_in_body_only_still_triggers_llm(self):
        """Entity name in article body (not title) must still reach LLM."""
        article = _article(
            title="Infrastructure sector weekly overview",
            body=f"{_ENTITY} announced plans for a major expansion this quarter.",
        )
        called = False

        def _tracking_llm(prompt: str) -> str:
            nonlocal called
            called = True
            return f"{_ENTITY} summary."

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = [article]
            build_dossier(_ENTITY, _config(), _tracking_llm)

        assert called, "body-only match must trigger LLM"

    def test_entity_name_match_is_case_insensitive(self):
        """Entity matching must fold case before comparing."""
        article = _article(f"{_ENTITY.upper()} DOMINATES QUARTERLY RESULTS")

        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = [article]
            result = build_dossier(_ENTITY, _config(), _stub_llm)

        assert len(result.summaries) > 0, "uppercase entity title must still be matched"


# ---------------------------------------------------------------------------
# Output-format invariants
# ---------------------------------------------------------------------------


class TestOutputFormat:
    """EntityDossier fields must be correctly typed and populated regardless of scenario."""

    def test_entity_field_preserved_exactly(self):
        entity = "Acme-Northgate Holdings"
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier(entity, _config(), _stub_llm)
        assert result.entity == entity

    def test_sources_checked_equals_entity_roster_length(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier(_ENTITY, _config(), _stub_llm)
        assert result.sources_checked == len(ENTITY_ROSTER)

    def test_sources_checked_invariant_with_total_outage(self):
        """sources_checked reflects ATTEMPTED sources, not successful ones."""
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = OSError("all down")
            result = build_dossier(_ENTITY, _config(), _stub_llm)
        assert result.sources_checked == len(ENTITY_ROSTER)

    def test_summaries_is_list_of_strings(self):
        article = _article(f"{_ENTITY} Q2 earnings beat expectations")
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = [article]
            result = build_dossier(_ENTITY, _config(), _stub_llm)
        assert isinstance(result.summaries, list)
        for s in result.summaries:
            assert isinstance(s, str)

    def test_fabrication_flags_is_list(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier(_ENTITY, _config(), _stub_llm)
        assert isinstance(result.fabrication_flags, list)

    def test_outage_sources_is_list_of_strings(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.side_effect = OSError("down")
            result = build_dossier(_ENTITY, _config(), _stub_llm)
        assert all(isinstance(s, str) for s in result.outage_sources)

    def test_articles_found_is_non_negative_integer(self):
        with patch("situation_monitor.dossier.RSSFetcher") as mock_cls:
            mock_cls.return_value.fetch.return_value = []
            result = build_dossier(_ENTITY, _config(), _stub_llm)
        assert isinstance(result.articles_found, int)
        assert result.articles_found >= 0

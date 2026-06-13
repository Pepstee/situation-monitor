"""Tests for DEFAULT_SOURCE_DEFS: coverage, integrity, and lens/domain completeness."""
from __future__ import annotations

from collections import defaultdict

import pytest

from situation_monitor.config import DEFAULT_SOURCE_DEFS, SourceDef
from situation_monitor.models import Domain

EXPECTED_LENSES = {"left", "right", "centre", "state"}
EXPECTED_DOMAINS = {Domain.WORLD, Domain.MARKETS, Domain.AI}


class TestDefaultSourceDefsBasic:
    def test_is_a_list(self) -> None:
        assert isinstance(DEFAULT_SOURCE_DEFS, list)

    def test_all_entries_are_source_def_instances(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert isinstance(sd, SourceDef), f"Expected SourceDef, got {type(sd)}"

    def test_has_at_least_36_entries(self) -> None:
        # 3 domains × 4 lenses × >=3 entries each = at least 36
        assert len(DEFAULT_SOURCE_DEFS) >= 36


class TestDomainLensCoverage:
    """Every (domain, lens) pair must have >=3 SourceDef entries."""

    @pytest.fixture(autouse=True)
    def _build_index(self) -> None:
        self._index: dict[tuple, list[SourceDef]] = defaultdict(list)
        for sd in DEFAULT_SOURCE_DEFS:
            self._index[(sd.domain, sd.lens)].append(sd)

    def test_world_left_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.WORLD, "left")]) >= 3

    def test_world_right_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.WORLD, "right")]) >= 3

    def test_world_centre_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.WORLD, "centre")]) >= 3

    def test_world_state_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.WORLD, "state")]) >= 3

    def test_markets_left_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.MARKETS, "left")]) >= 3

    def test_markets_right_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.MARKETS, "right")]) >= 3

    def test_markets_centre_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.MARKETS, "centre")]) >= 3

    def test_markets_state_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.MARKETS, "state")]) >= 3

    def test_ai_left_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.AI, "left")]) >= 3

    def test_ai_right_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.AI, "right")]) >= 3

    def test_ai_centre_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.AI, "centre")]) >= 3

    def test_ai_state_has_at_least_three(self) -> None:
        assert len(self._index[(Domain.AI, "state")]) >= 3


class TestAllLensesPresentPerDomain:
    """Each of the 3 domains must expose all four lenses."""

    @pytest.fixture(autouse=True)
    def _build_lens_sets(self) -> None:
        self._domain_lenses: dict[Domain, set[str]] = defaultdict(set)
        for sd in DEFAULT_SOURCE_DEFS:
            self._domain_lenses[sd.domain].add(sd.lens)

    def test_world_has_all_four_lenses(self) -> None:
        assert self._domain_lenses[Domain.WORLD] == EXPECTED_LENSES

    def test_markets_has_all_four_lenses(self) -> None:
        assert self._domain_lenses[Domain.MARKETS] == EXPECTED_LENSES

    def test_ai_has_all_four_lenses(self) -> None:
        assert self._domain_lenses[Domain.AI] == EXPECTED_LENSES

    def test_no_unexpected_lenses_present(self) -> None:
        all_lenses = {sd.lens for sd in DEFAULT_SOURCE_DEFS}
        assert all_lenses <= EXPECTED_LENSES, f"Unexpected lenses: {all_lenses - EXPECTED_LENSES}"


class TestThreeDomainsRepresented:
    def test_exactly_three_domains_present(self) -> None:
        domains = {sd.domain for sd in DEFAULT_SOURCE_DEFS}
        assert domains == EXPECTED_DOMAINS


class TestSourceDefFieldIntegrity:
    def test_all_urls_non_empty(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert sd.url, f"Empty url for SourceDef name={sd.name!r}"

    def test_all_names_non_empty(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert sd.name, f"Empty name in DEFAULT_SOURCE_DEFS"

    def test_all_descriptions_non_empty(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert sd.description, f"Empty description for SourceDef name={sd.name!r}"

    def test_all_lenses_are_non_empty_strings(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert isinstance(sd.lens, str) and sd.lens, f"Bad lens for {sd.name!r}"

    def test_all_names_are_non_empty_strings(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert isinstance(sd.name, str) and sd.name, f"Bad name entry in DEFAULT_SOURCE_DEFS"

    def test_all_descriptions_are_non_empty_strings(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert isinstance(sd.description, str) and sd.description, (
                f"Bad description for {sd.name!r}"
            )

    def test_all_urls_start_with_http(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert sd.url.startswith("http"), (
                f"URL doesn't start with http for {sd.name!r}: {sd.url!r}"
            )

    def test_all_domains_are_domain_enum_instances(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert isinstance(sd.domain, Domain), (
                f"domain is not a Domain for {sd.name!r}: {sd.domain!r}"
            )

    def test_all_lenses_from_expected_set(self) -> None:
        for sd in DEFAULT_SOURCE_DEFS:
            assert sd.lens in EXPECTED_LENSES, (
                f"Unexpected lens {sd.lens!r} for {sd.name!r}"
            )

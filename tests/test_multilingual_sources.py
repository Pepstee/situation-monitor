"""Multilingual source integrity: dedup, language-family coverage, per-cell density."""
from __future__ import annotations

import re
from collections import defaultdict

import pytest

from situation_monitor.config import DEFAULT_SOURCE_DEFS, SourceDef
from situation_monitor.models import Domain

# Regex matching any keyword from the curated non-English language list.
# Applied against SourceDef.description only (not name or url).
_NON_ENGLISH_LANG_RE = re.compile(
    r"\b(German|French|Spanish|Arabic|Japanese|Portuguese|Italian|Korean|"
    r"Turkish|Persian|Dutch|Farsi|Hindi|Polish|Swahili|Bengali)\b",
    re.IGNORECASE,
)

# Maps each keyword (lowercase) to a high-level language family.
# Families are used exclusively by test_language_family_breadth.
_FAMILY: dict[str, str] = {
    "german": "Germanic",
    "dutch": "Germanic",
    "french": "Romance",
    "spanish": "Romance",
    "portuguese": "Romance",
    "italian": "Romance",
    "arabic": "Semitic",
    "japanese": "Japonic",
    "korean": "Koreanic",
    "turkish": "Turkic",
    "persian": "Indo-Iranian",
    "farsi": "Indo-Iranian",
    "hindi": "Indo-Iranian",
    "bengali": "Indo-Iranian",
    "polish": "Slavic",
    "swahili": "Bantu",
}

# All (Domain, lens) pairs that the contract demands have ≥3 entries.
_ALL_EXPECTED_PAIRS = [
    (Domain.WORLD, "left"),
    (Domain.WORLD, "right"),
    (Domain.WORLD, "centre"),
    (Domain.WORLD, "state"),
    (Domain.MARKETS, "left"),
    (Domain.MARKETS, "right"),
    (Domain.MARKETS, "centre"),
    (Domain.MARKETS, "state"),
    (Domain.AI, "left"),
    (Domain.AI, "right"),
    (Domain.AI, "centre"),
    (Domain.AI, "state"),
]


# ---------------------------------------------------------------------------
# Helper — built once, reused across the parametrised tests below
# ---------------------------------------------------------------------------

def _build_cell_index() -> dict[tuple[Domain, str], list[SourceDef]]:
    idx: dict[tuple[Domain, str], list[SourceDef]] = defaultdict(list)
    for sd in DEFAULT_SOURCE_DEFS:
        idx[(sd.domain, sd.lens)].append(sd)
    return idx


def test_no_duplicate_urls() -> None:
    """Each URL in DEFAULT_SOURCE_DEFS must appear exactly once."""
    urls = [sd.url for sd in DEFAULT_SOURCE_DEFS]
    duplicates = [u for u in set(urls) if urls.count(u) > 1]
    assert len(set(urls)) == len(urls), (
        f"Duplicate URL(s) detected: {duplicates}"
    )


def test_multilingual_coverage() -> None:
    """At least 12 entries must mention a non-English language in their description."""
    matches = [
        sd for sd in DEFAULT_SOURCE_DEFS
        if _NON_ENGLISH_LANG_RE.search(sd.description)
    ]
    assert len(matches) >= 12, (
        f"Only {len(matches)} entries have a non-English language keyword in description; "
        f"need ≥12.\n"
        f"Matched names: {[sd.name for sd in matches]}"
    )


def test_multilingual_coverage_upper_bound_sanity() -> None:
    """Sanity check: multilingual entries should not exceed the total list length."""
    matches = [
        sd for sd in DEFAULT_SOURCE_DEFS
        if _NON_ENGLISH_LANG_RE.search(sd.description)
    ]
    # This can only fail if the regex or the source list is structurally broken.
    assert len(matches) <= len(DEFAULT_SOURCE_DEFS)


def test_language_family_breadth() -> None:
    """Descriptions must collectively reference sources from ≥5 distinct language families."""
    families: set[str] = set()
    for sd in DEFAULT_SOURCE_DEFS:
        for m in _NON_ENGLISH_LANG_RE.finditer(sd.description):
            keyword = m.group(1).lower()
            if keyword in _FAMILY:
                families.add(_FAMILY[keyword])

    assert len(families) >= 5, (
        f"Only {len(families)} language families represented: {sorted(families)}; need ≥5.\n"
        f"Family map applied: {_FAMILY}"
    )


def test_language_family_breadth_families_are_known() -> None:
    """Every language keyword found in descriptions maps to a known family (no unknown slips through)."""
    unknown: list[str] = []
    for sd in DEFAULT_SOURCE_DEFS:
        for m in _NON_ENGLISH_LANG_RE.finditer(sd.description):
            keyword = m.group(1).lower()
            if keyword not in _FAMILY:
                unknown.append(f"{sd.name!r}: keyword={keyword!r}")
    assert not unknown, f"Keywords matched but not in family map:\n" + "\n".join(unknown)


def test_all_cells_have_at_least_three() -> None:
    """Every (Domain, lens) pair must have ≥3 SourceDef entries."""
    idx = _build_cell_index()
    failures = [
        f"({domain.value}, {lens!r}): {len(idx[(domain, lens)])} entries"
        for domain, lens in _ALL_EXPECTED_PAIRS
        if len(idx[(domain, lens)]) < 3
    ]
    assert not failures, (
        "The following (Domain, lens) cells have fewer than 3 entries:\n"
        + "\n".join(failures)
    )


@pytest.mark.parametrize("domain,lens", _ALL_EXPECTED_PAIRS)
def test_cell_density_parametrised(domain: Domain, lens: str) -> None:
    """Parametrised form: each individual (Domain, lens) pair has ≥3 entries."""
    idx = _build_cell_index()
    count = len(idx[(domain, lens)])
    assert count >= 3, (
        f"({domain.value}, {lens!r}) has only {count} entries; minimum is 3."
    )


def test_no_duplicate_names() -> None:
    """Source names should be unique — a duplicate name almost always means a copy-paste error."""
    names = [sd.name for sd in DEFAULT_SOURCE_DEFS]
    duplicates = [n for n in set(names) if names.count(n) > 1]
    assert len(set(names)) == len(names), (
        f"Duplicate source name(s) found: {duplicates}"
    )


def test_multilingual_descriptions_are_non_trivial() -> None:
    """Entries that claim a language in their description must have descriptions longer than just
    the language name — prevents one-word placeholder descriptions from gaming the count."""
    for sd in DEFAULT_SOURCE_DEFS:
        if _NON_ENGLISH_LANG_RE.search(sd.description):
            assert len(sd.description.split()) >= 4, (
                f"{sd.name!r}: description matching non-English keyword is too short: "
                f"{sd.description!r}"
            )


def test_multilingual_entries_span_multiple_domains() -> None:
    """Non-English-language entries should not all be clustered in a single domain."""
    domain_counts: dict[Domain, int] = defaultdict(int)
    for sd in DEFAULT_SOURCE_DEFS:
        if _NON_ENGLISH_LANG_RE.search(sd.description):
            domain_counts[sd.domain] += 1

    domains_with_multilingual = [d for d, c in domain_counts.items() if c > 0]
    assert len(domains_with_multilingual) >= 2, (
        f"Multilingual entries concentrated in only {len(domains_with_multilingual)} domain(s): "
        f"{dict(domain_counts)}"
    )


def test_multilingual_entries_span_multiple_lenses() -> None:
    """Non-English-language entries should appear across multiple political lenses."""
    lens_counts: dict[str, int] = defaultdict(int)
    for sd in DEFAULT_SOURCE_DEFS:
        if _NON_ENGLISH_LANG_RE.search(sd.description):
            lens_counts[sd.lens] += 1

    lenses_with_multilingual = [l for l, c in lens_counts.items() if c > 0]
    assert len(lenses_with_multilingual) >= 2, (
        f"Multilingual entries concentrated in only {len(lenses_with_multilingual)} lens(es): "
        f"{dict(lens_counts)}"
    )


def test_url_uniqueness_is_strict_not_prefix_match() -> None:
    """Two URLs that share a common prefix but differ in path are still distinct.
    This test ensures the dedup check is URL-exact, not prefix-based."""
    urls = [sd.url for sd in DEFAULT_SOURCE_DEFS]
    # If any two entries share the exact same URL the set-length check will catch it.
    # Here we also assert that no URL is a pure prefix of another in the list, which
    # would indicate a misconfigured feed path (e.g. base URL vs. path).
    sorted_urls = sorted(urls)
    prefix_pairs = [
        (sorted_urls[i], sorted_urls[i + 1])
        for i in range(len(sorted_urls) - 1)
        if sorted_urls[i + 1].startswith(sorted_urls[i] + "/")
        or sorted_urls[i + 1].startswith(sorted_urls[i] + "?")
    ]
    assert not prefix_pairs, (
        f"Some URLs are prefixes of others (likely misconfigured):\n"
        + "\n".join(f"  {a!r} is a prefix of {b!r}" for a, b in prefix_pairs)
    )


def test_each_language_keyword_maps_to_exactly_one_family() -> None:
    """Every keyword in the curated list maps to exactly one family in our lookup table —
    no ambiguous or missing entries that would silently undercount families."""
    keywords_in_regex = [
        "German", "French", "Spanish", "Arabic", "Japanese", "Portuguese",
        "Italian", "Korean", "Turkish", "Persian", "Dutch", "Farsi",
        "Hindi", "Polish", "Swahili", "Bengali",
    ]
    missing = [k for k in keywords_in_regex if k.lower() not in _FAMILY]
    assert not missing, f"Keywords in regex but missing from _FAMILY map: {missing}"

"""Tests for situation_monitor.bias: CURATED_BIAS dataset and lookup helpers."""

from __future__ import annotations


from situation_monitor.bias import CURATED_BIAS, get_source_lean, get_source_reliability


class TestCuratedBiasDataset:
    def test_has_at_least_20_entries(self) -> None:
        assert len(CURATED_BIAS) >= 20

    def test_every_entry_has_lean_and_reliability_tier(self) -> None:
        for key, entry in CURATED_BIAS.items():
            assert "lean" in entry, f"Missing 'lean' for {key}"
            assert "reliability_tier" in entry, f"Missing 'reliability_tier' for {key}"

    def test_lean_values_are_from_known_set(self) -> None:
        valid_leans = {"left", "right", "center", "left-center", "right-center"}
        for key, entry in CURATED_BIAS.items():
            assert entry["lean"] in valid_leans, f"Unexpected lean for {key}: {entry['lean']!r}"

    def test_reliability_tier_values_are_from_known_set(self) -> None:
        valid = {"high", "medium", "low", "mixed"}
        for key, entry in CURATED_BIAS.items():
            assert entry["reliability_tier"] in valid, (
                f"Unexpected reliability_tier for {key}: {entry['reliability_tier']!r}"
            )


class TestGetSourceLean:
    # --- exact matches for >=5 named outlets ---

    def test_foxnews_is_right(self) -> None:
        assert get_source_lean("foxnews.com") == "right"

    def test_cnn_is_left(self) -> None:
        assert get_source_lean("cnn.com") == "left"

    def test_bbc_is_center(self) -> None:
        assert get_source_lean("bbc.com") == "center"

    def test_nytimes_is_left_center(self) -> None:
        assert get_source_lean("nytimes.com") == "left-center"

    def test_wsj_is_right_center(self) -> None:
        assert get_source_lean("wsj.com") == "right-center"

    def test_reuters_is_center(self) -> None:
        assert get_source_lean("reuters.com") == "center"

    def test_breitbart_is_right(self) -> None:
        assert get_source_lean("breitbart.com") == "right"

    def test_npr_is_left_center(self) -> None:
        assert get_source_lean("npr.org") == "left-center"

    # --- substring: source longer than key (key is a substring of source) ---

    def test_key_found_as_substring_of_full_url(self) -> None:
        # "foxnews.com" is a substring of the full URL string
        assert get_source_lean("https://www.foxnews.com/politics/breaking") == "right"

    def test_key_found_in_domain_with_subdomain(self) -> None:
        assert get_source_lean("feeds.reuters.com") == "center"

    # --- substring: source shorter than key (source is a substring of key) ---

    def test_short_source_is_substring_of_key(self) -> None:
        # "bbc" is a substring of "bbc.com"; source_lower in key evaluates True
        result = get_source_lean("bbc")
        assert result is not None
        assert result == "center"

    # --- case insensitivity ---

    def test_uppercase_input_matches(self) -> None:
        assert get_source_lean("FoxNews.com") == "right"

    def test_mixed_case_url_matches(self) -> None:
        assert get_source_lean("CNN.COM") == "left"

    # --- unknown outlets ---

    def test_completely_unknown_outlet_returns_none(self) -> None:
        assert get_source_lean("totally-unknown-outlet-xyz.net") is None

    def test_random_string_with_no_overlap_returns_none(self) -> None:
        assert get_source_lean("gossip-daily-2026.io") is None


class TestGetSourceReliability:
    # --- exact matches for >=5 named outlets ---

    def test_bbc_is_high(self) -> None:
        assert get_source_reliability("bbc.com") == "high"

    def test_reuters_is_high(self) -> None:
        assert get_source_reliability("reuters.com") == "high"

    def test_breitbart_is_low(self) -> None:
        assert get_source_reliability("breitbart.com") == "low"

    def test_cnn_is_medium(self) -> None:
        assert get_source_reliability("cnn.com") == "medium"

    def test_wsj_is_high(self) -> None:
        assert get_source_reliability("wsj.com") == "high"

    def test_foxnews_is_mixed(self) -> None:
        assert get_source_reliability("foxnews.com") == "mixed"

    def test_bloomberg_is_high(self) -> None:
        assert get_source_reliability("bloomberg.com") == "high"

    # --- substring matching ---

    def test_full_url_substring_match(self) -> None:
        assert get_source_reliability("https://www.reuters.com/world/article") == "high"

    def test_short_source_substring_of_key(self) -> None:
        result = get_source_reliability("bbc")
        assert result is not None
        assert result == "high"

    # --- case insensitivity ---

    def test_uppercase_input_matches(self) -> None:
        assert get_source_reliability("BBC.COM") == "high"

    # --- unknown outlets ---

    def test_completely_unknown_outlet_returns_none(self) -> None:
        assert get_source_reliability("totally-unknown-outlet-xyz.net") is None

    def test_unrelated_domain_returns_none(self) -> None:
        assert get_source_reliability("my-cat-photos-2026.site") is None

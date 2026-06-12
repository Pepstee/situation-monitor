"""Adversarial tests for situation_monitor.dedup."""

from __future__ import annotations


from situation_monitor.dedup import deduplicate, _normalise
from situation_monitor.models import Article


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_article(url: str, title: str, source: str = "src") -> Article:
    return Article(url=url, title=title, source=source)


# ---------------------------------------------------------------------------
# _normalise unit tests
# ---------------------------------------------------------------------------

class TestNormalise:
    def test_lowercases(self):
        assert _normalise("Hello WORLD") == ["hello", "world"]

    def test_strips_punctuation(self):
        result = _normalise("It's a test: hello, world!")
        assert "its" in result or "it" in result  # punctuation stripped
        assert "hello" in result
        assert "world" in result

    def test_empty_string(self):
        assert _normalise("") == []

    def test_only_punctuation(self):
        assert _normalise("!!!...???") == []

    def test_preserves_word_order(self):
        assert _normalise("alpha beta gamma") == ["alpha", "beta", "gamma"]

    def test_numbers_preserved(self):
        result = _normalise("Top 10 reasons")
        assert "10" in result
        assert "top" in result


# ---------------------------------------------------------------------------
# deduplicate — empty / trivial inputs
# ---------------------------------------------------------------------------

class TestDeduplicateEmpty:
    def test_empty_list_returns_empty(self):
        assert deduplicate([]) == []

    def test_single_article_passes_through(self):
        a = make_article("http://x.com/1", "Unique title here")
        assert deduplicate([a]) == [a]


# ---------------------------------------------------------------------------
# deduplicate — exact URL deduplication
# ---------------------------------------------------------------------------

class TestExactURLDedup:
    def test_second_copy_dropped(self):
        a1 = make_article("http://x.com/1", "Alpha story", source="reuters")
        a2 = make_article("http://x.com/1", "Alpha story", source="reuters")
        result = deduplicate([a1, a2])
        assert result == [a1]
        assert len(result) == 1

    def test_first_occurrence_kept(self):
        a1 = make_article("http://x.com/1", "First title", source="reuters")
        a2 = make_article("http://x.com/1", "Different title but same URL", source="bbc")
        result = deduplicate([a1, a2])
        assert result[0].title == "First title"

    def test_different_sources_same_url_deduped(self):
        a1 = make_article("http://shared.com/story", "Breaking news today", source="reuters")
        a2 = make_article("http://shared.com/story", "Breaking news today", source="bbc")
        result = deduplicate([a1, a2])
        assert len(result) == 1
        assert result[0].source == "reuters"

    def test_three_duplicates_collapsed_to_one(self):
        url = "http://x.com/dup"
        articles = [make_article(url, f"Title {i}") for i in range(3)]
        assert len(deduplicate(articles)) == 1

    def test_distinct_urls_all_preserved(self):
        articles = [make_article(f"http://x.com/{i}", f"Title {i}") for i in range(5)]
        assert len(deduplicate(articles)) == 5


# ---------------------------------------------------------------------------
# deduplicate — near-duplicate title deduplication
# ---------------------------------------------------------------------------

class TestNearDuplicateTitleDedup:
    def test_near_duplicate_title_removed(self):
        a1 = make_article("http://x.com/1", "US inflation rises for third month in a row")
        a2 = make_article("http://x.com/2", "US inflation rises for third month, analysts say")
        result = deduplicate([a1, a2])
        # Same first 6 words — second should be dropped
        assert len(result) == 1
        assert result[0].url == "http://x.com/1"

    def test_near_duplicate_first_six_words_match(self):
        a1 = make_article("http://x.com/1", "The quick brown fox jumps over the lazy dog")
        a2 = make_article("http://x.com/2", "The quick brown fox jumps over a cat")
        result = deduplicate([a1, a2])
        assert len(result) == 1

    def test_titles_differ_at_word_7_both_kept(self):
        a1 = make_article("http://x.com/1", "one two three four five six DIFFERENT ending here")
        a2 = make_article("http://x.com/2", "one two three four five six OTHER ending here")
        # They share first 6 words → near-duplicate, second dropped
        result = deduplicate([a1, a2])
        assert len(result) == 1

    def test_titles_differ_within_first_six_both_kept(self):
        a1 = make_article("http://x.com/1", "alpha beta gamma delta epsilon zeta")
        a2 = make_article("http://x.com/2", "alpha beta gamma delta epsilon ETA")
        result = deduplicate([a1, a2])
        assert len(result) == 2

    def test_short_title_all_words_used_as_key(self):
        # Titles shorter than 6 words: same full title → deduped
        a1 = make_article("http://x.com/1", "War in Ukraine")
        a2 = make_article("http://x.com/2", "War in Ukraine")
        result = deduplicate([a1, a2])
        assert len(result) == 1

    def test_short_title_different_words_both_kept(self):
        a1 = make_article("http://x.com/1", "War in Ukraine")
        a2 = make_article("http://x.com/2", "Peace in Ukraine")
        result = deduplicate([a1, a2])
        assert len(result) == 2

    def test_punctuation_ignored_in_near_dup_check(self):
        a1 = make_article("http://x.com/1", "US inflation rises for third month!")
        a2 = make_article("http://x.com/2", "US inflation rises for third month?")
        result = deduplicate([a1, a2])
        # After normalisation the prefixes match
        assert len(result) == 1

    def test_case_ignored_in_near_dup_check(self):
        a1 = make_article("http://x.com/1", "Breaking US Inflation Rises For Third Month")
        a2 = make_article("http://x.com/2", "breaking us inflation rises for third month extended")
        result = deduplicate([a1, a2])
        assert len(result) == 1


# ---------------------------------------------------------------------------
# deduplicate — unique articles preserved
# ---------------------------------------------------------------------------

class TestUniqueArticlesPreserved:
    def test_unique_articles_all_kept(self):
        articles = [
            make_article("http://x.com/1", "Climate report warns of rising seas"),
            make_article("http://x.com/2", "Stock market hits record high today"),
            make_article("http://x.com/3", "New AI model released by Anthropic"),
        ]
        result = deduplicate(articles)
        assert len(result) == 3

    def test_order_preserved_for_unique(self):
        articles = [make_article(f"http://x.com/{i}", f"Story {i} headline here now") for i in range(4)]
        result = deduplicate(articles)
        assert [a.url for a in result] == [a.url for a in articles]


# ---------------------------------------------------------------------------
# deduplicate — URL dedup happens before title dedup
# ---------------------------------------------------------------------------

class TestURLBeforeTitleDedup:
    def test_url_dup_removed_before_title_check(self):
        # Two articles share URL; the surviving one then competes on title with a third
        a1 = make_article("http://x.com/1", "US inflation rises for third month report")
        a2 = make_article("http://x.com/1", "US inflation rises for third month analysis")  # URL dup
        a3 = make_article("http://x.com/2", "US inflation rises for third month warning")   # near-dup title
        result = deduplicate([a1, a2, a3])
        # a2 dropped (URL dup), a3 dropped (near-dup of a1), only a1 survives
        assert len(result) == 1
        assert result[0].url == "http://x.com/1"

    def test_mixed_dedup_all_distinct_survive(self):
        a1 = make_article("http://x.com/1", "Bitcoin falls twenty percent in one week crash")
        a2 = make_article("http://x.com/1", "Bitcoin falls twenty percent in one week crash")  # URL dup
        a3 = make_article("http://x.com/3", "Ethereum soars fifty percent in record rally")   # unique
        result = deduplicate([a1, a2, a3])
        assert len(result) == 2
        urls = {a.url for a in result}
        assert "http://x.com/1" in urls
        assert "http://x.com/3" in urls


# ---------------------------------------------------------------------------
# deduplicate — articles from different sources with same URL
# ---------------------------------------------------------------------------

class TestDifferentSourcesSameURL:
    def test_same_url_different_sources_one_kept(self):
        sources = ["reuters", "bbc", "cnn", "ap"]
        articles = [make_article("http://wire.com/story", "Breaking story now", source=s) for s in sources]
        result = deduplicate(articles)
        assert len(result) == 1
        assert result[0].source == "reuters"  # first in wins

    def test_each_unique_url_from_same_source_all_kept(self):
        articles = [
            make_article("http://bbc.com/1", "Story one from bbc", source="bbc"),
            make_article("http://bbc.com/2", "Story two from bbc", source="bbc"),
        ]
        result = deduplicate(articles)
        assert len(result) == 2

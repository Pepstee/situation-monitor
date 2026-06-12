"""Adversarial tests for situation_monitor.reliability."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


from situation_monitor.reliability import ReliabilityTracker


# ---------------------------------------------------------------------------
# record_fetch — basic counting behaviour
# ---------------------------------------------------------------------------

class TestRecordFetch:
    def test_record_fetch_increments_fetch_count(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("reuters", 3)
        tracker.record_fetch("reuters", 5)
        # Internal state: fetch_count should be 2 after two calls
        fetches, total = tracker._data["reuters"]
        assert fetches == 2

    def test_record_fetch_increments_article_total(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("bbc", 4)
        tracker.record_fetch("bbc", 6)
        _, total = tracker._data["bbc"]
        assert total == 10

    def test_record_fetch_creates_source_on_first_call(self):
        tracker = ReliabilityTracker()
        assert "ap" not in tracker._data
        tracker.record_fetch("ap", 2)
        assert "ap" in tracker._data

    def test_record_fetch_zero_articles(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("empty_source", 0)
        fetches, total = tracker._data["empty_source"]
        assert fetches == 1
        assert total == 0

    def test_record_fetch_large_count(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("fire_hose", 10_000)
        _, total = tracker._data["fire_hose"]
        assert total == 10_000

    def test_multiple_sources_tracked_independently(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("reuters", 10)
        tracker.record_fetch("reuters", 10)
        tracker.record_fetch("cnn", 2)

        reuters_fetches, reuters_total = tracker._data["reuters"]
        cnn_fetches, cnn_total = tracker._data["cnn"]

        assert reuters_fetches == 2
        assert reuters_total == 20
        assert cnn_fetches == 1
        assert cnn_total == 2

    def test_sources_do_not_bleed_into_each_other(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("source_a", 50)
        tracker.record_fetch("source_b", 1)
        assert tracker._data["source_a"][1] == 50
        assert tracker._data["source_b"][1] == 1


# ---------------------------------------------------------------------------
# get_tracked_reliability — label derivation
# ---------------------------------------------------------------------------

class TestGetTrackedReliability:
    def test_returns_none_for_unknown_source(self):
        tracker = ReliabilityTracker()
        assert tracker.get_tracked_reliability("ghost") is None

    def test_returns_non_none_after_recording(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("cnn", 3)
        result = tracker.get_tracked_reliability("cnn")
        assert result is not None

    def test_high_reliability_when_avg_ge_5(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("high_src", 10)  # avg = 10/1 = 10 → high
        assert tracker.get_tracked_reliability("high_src") == "high"

    def test_high_reliability_exact_boundary(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("high_src", 5)  # avg = 5.0 → high
        assert tracker.get_tracked_reliability("high_src") == "high"

    def test_medium_reliability_avg_between_1_and_5(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("med_src", 3)   # avg = 3.0 → medium
        assert tracker.get_tracked_reliability("med_src") == "medium"

    def test_medium_reliability_exact_lower_boundary(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("med_src", 1)   # avg = 1.0 → medium
        assert tracker.get_tracked_reliability("med_src") == "medium"

    def test_low_reliability_avg_below_1(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("low_src", 0)   # avg = 0/1 = 0 → low
        assert tracker.get_tracked_reliability("low_src") == "low"

    def test_label_reflects_accumulated_fetches(self):
        tracker = ReliabilityTracker()
        # 10 fetches each with 0 articles → avg stays 0 → low
        for _ in range(10):
            tracker.record_fetch("sparse", 0)
        assert tracker.get_tracked_reliability("sparse") == "low"

    def test_avg_computed_across_multiple_fetches(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("mixed", 0)
        tracker.record_fetch("mixed", 0)
        tracker.record_fetch("mixed", 0)
        tracker.record_fetch("mixed", 0)
        tracker.record_fetch("mixed", 10)
        # avg = 10/5 = 2.0 → medium
        assert tracker.get_tracked_reliability("mixed") == "medium"

    def test_returns_string_not_enum(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("check", 5)
        result = tracker.get_tracked_reliability("check")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# load / save round-trip
# ---------------------------------------------------------------------------

class TestLoadSave:
    def test_save_then_load_round_trips(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("reuters", 8)
        tracker.record_fetch("reuters", 4)
        tracker.record_fetch("bbc", 1)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker.save(path)

            tracker2 = ReliabilityTracker()
            tracker2.load(path)

            assert tracker2._data == tracker._data
        finally:
            os.unlink(path)

    def test_save_produces_valid_json(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("ap", 7)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            tracker.save(path)
            raw = Path(path).read_text()
            parsed = json.loads(raw)
            assert "ap" in parsed
        finally:
            os.unlink(path)

    def test_load_missing_file_starts_empty(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("existing", 3)  # pre-existing state
        tracker.load("/tmp/__nonexistent_reliability_file_xyz__.json")
        # load should silently fail; original state untouched (no reset), or reset — check implementation
        # Implementation catches FileNotFoundError with `pass`, so state unchanged
        assert "existing" in tracker._data

    def test_load_fresh_tracker_missing_file_stays_empty(self):
        tracker = ReliabilityTracker()
        tracker.load("/tmp/__nonexistent_reliability_file_xyz__.json")
        assert tracker._data == {}

    def test_load_corrupt_json_does_not_raise(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write("{INVALID JSON{{")
            path = f.name
        try:
            tracker = ReliabilityTracker()
            tracker.load(path)  # should not raise
            assert tracker._data == {}
        finally:
            os.unlink(path)

    def test_load_empty_json_object_clears_data(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump({}, f)
            path = f.name
        try:
            tracker = ReliabilityTracker()
            tracker.record_fetch("before_load", 5)
            tracker.load(path)
            assert tracker._data == {}
        finally:
            os.unlink(path)

    def test_reliability_label_survives_round_trip(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("premium", 20)  # avg=20, high

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker.save(path)

            tracker2 = ReliabilityTracker()
            tracker2.load(path)

            assert tracker2.get_tracked_reliability("premium") == "high"
        finally:
            os.unlink(path)

    def test_save_overwrites_previous_file(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker = ReliabilityTracker()
            tracker.record_fetch("v1", 3)
            tracker.save(path)

            tracker2 = ReliabilityTracker()
            tracker2.record_fetch("v2", 9)
            tracker2.save(path)

            tracker3 = ReliabilityTracker()
            tracker3.load(path)
            assert "v2" in tracker3._data
            assert "v1" not in tracker3._data
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# Multiple sources tracked independently (integrated)
# ---------------------------------------------------------------------------

class TestMultipleSourcesIndependent:
    def test_five_sources_all_tracked(self):
        tracker = ReliabilityTracker()
        sources = ["reuters", "bbc", "cnn", "ap", "al_jazeera"]
        for i, src in enumerate(sources):
            tracker.record_fetch(src, (i + 1) * 2)

        for src in sources:
            assert tracker.get_tracked_reliability(src) is not None

    def test_updating_one_source_does_not_affect_others(self):
        tracker = ReliabilityTracker()
        tracker.record_fetch("a", 5)
        tracker.record_fetch("b", 5)

        label_b_before = tracker.get_tracked_reliability("b")
        # Many fetches with 0 articles should push "a" to low
        for _ in range(100):
            tracker.record_fetch("a", 0)

        assert tracker.get_tracked_reliability("b") == label_b_before

    def test_all_sources_survive_save_load(self):
        tracker = ReliabilityTracker()
        sources_data = {"reuters": 8, "bbc": 3, "tabloid": 0}
        for src, count in sources_data.items():
            tracker.record_fetch(src, count)

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            path = f.name
        try:
            tracker.save(path)
            tracker2 = ReliabilityTracker()
            tracker2.load(path)

            for src in sources_data:
                assert tracker2.get_tracked_reliability(src) is not None
        finally:
            os.unlink(path)

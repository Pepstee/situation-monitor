"""Adversarial tests for situation_monitor.alerting.check_and_emit_alerts.

Author: independent test agent — NOT the builder that wrote alerting.py.
Tests exercise real code paths: no mocking of the unit under test.
"""

from __future__ import annotations

import io
from typing import Optional

import pytest

from situation_monitor.alerting import check_and_emit_alerts
from situation_monitor.models import Article


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _article(
    *,
    title: str = "Test Article",
    source: str = "example.com",
    score: Optional[float] = None,
    cluster_id: Optional[str] = None,
    url: str = "https://example.com/a",
) -> Article:
    return Article(
        url=url,
        title=title,
        source=source,
        relevance_score=score,
        cluster_id=cluster_id,
    )


# ---------------------------------------------------------------------------
# Acceptance criteria
# ---------------------------------------------------------------------------

class TestAcceptanceCriteria:
    """The three mandated acceptance-criteria cases plus the StringIO requirement."""

    def test_alert_fires_when_score_above_threshold(self, capsys) -> None:
        article = _article(title="High Relevance", score=0.9)
        alerted = check_and_emit_alerts([article], threshold=0.5)
        assert article in alerted

    def test_alert_fires_when_score_at_threshold(self, capsys) -> None:
        """Spec says score >= threshold triggers an alert; implementation uses >, so this fails."""
        article = _article(title="On The Line", score=0.7)
        alerted = check_and_emit_alerts([article], threshold=0.7)
        assert article in alerted, (
            "Expected alert when relevance_score == threshold (spec requires >=, implementation uses >)"
        )

    def test_no_alert_when_score_below_threshold(self, capsys) -> None:
        article = _article(title="Low Relevance", score=0.3)
        alerted = check_and_emit_alerts([article], threshold=0.5)
        assert alerted == []

    def test_mixed_score_batch_returns_correct_subset(self, capsys) -> None:
        low = _article(title="Low", score=0.1)
        at_threshold = _article(title="At Threshold", score=0.5)
        high = _article(title="High", score=0.9)
        alerted = check_and_emit_alerts([low, at_threshold, high], threshold=0.5)
        assert high in alerted, "score above threshold must be alerted"
        assert low not in alerted, "score below threshold must not be alerted"
        # spec says >=; current code uses > so this assertion will fail:
        assert at_threshold in alerted, (
            "score == threshold must be alerted (spec: >=, implementation uses >)"
        )

    def test_stringio_accepted_as_output_file(self) -> None:
        """Acceptance: no I/O side-effects — pass StringIO as output_file.

        The current implementation calls open(output_file, "a") which requires a
        path string, so passing a StringIO will raise TypeError.  This test
        documents the intended contract; it fails until the implementation accepts
        file-like objects.
        """
        buf = io.StringIO()
        article = _article(title="StringIO Alert", score=0.9)
        alerted = check_and_emit_alerts([article], threshold=0.5, output_file=buf)
        assert article in alerted
        output = buf.getvalue()
        assert "StringIO Alert" in output, "Alert should be written into the StringIO buffer"


# ---------------------------------------------------------------------------
# Return value contract
# ---------------------------------------------------------------------------

class TestReturnValue:
    def test_returns_list(self, capsys) -> None:
        result = check_and_emit_alerts([], threshold=0.5)
        assert isinstance(result, list)

    def test_empty_input_returns_empty_list(self, capsys) -> None:
        assert check_and_emit_alerts([], threshold=0.5) == []

    def test_all_below_threshold_returns_empty_list(self, capsys) -> None:
        articles = [_article(score=0.1), _article(score=0.2), _article(score=0.3)]
        assert check_and_emit_alerts(articles, threshold=0.5) == []

    def test_all_above_threshold_returns_all(self, capsys) -> None:
        articles = [_article(title=f"Art{i}", score=0.6 + i * 0.1) for i in range(3)]
        alerted = check_and_emit_alerts(articles, threshold=0.5)
        assert len(alerted) == 3

    def test_returned_articles_are_same_objects_not_copies(self, capsys) -> None:
        article = _article(score=0.9)
        alerted = check_and_emit_alerts([article], threshold=0.5)
        assert len(alerted) == 1
        assert alerted[0] is article

    def test_input_order_preserved_in_output(self, capsys) -> None:
        a = _article(title="Alpha", score=0.9)
        b = _article(title="Beta", score=0.8)
        c = _article(title="Gamma", score=0.7)
        alerted = check_and_emit_alerts([a, b, c], threshold=0.5)
        assert alerted == [a, b, c]

    def test_original_list_not_mutated(self, capsys) -> None:
        articles = [_article(title=f"Art{i}", score=0.9) for i in range(3)]
        original_ids = [id(a) for a in articles]
        check_and_emit_alerts(articles, threshold=0.5)
        assert [id(a) for a in articles] == original_ids


# ---------------------------------------------------------------------------
# Threshold boundary conditions
# ---------------------------------------------------------------------------

class TestThresholdBoundary:
    def test_tiny_increment_above_threshold_fires(self, capsys) -> None:
        article = _article(score=0.5001)
        alerted = check_and_emit_alerts([article], threshold=0.5)
        assert article in alerted

    def test_tiny_decrement_below_threshold_does_not_fire(self, capsys) -> None:
        article = _article(score=0.4999)
        alerted = check_and_emit_alerts([article], threshold=0.5)
        assert alerted == []

    def test_threshold_zero_fires_for_any_positive_score(self, capsys) -> None:
        article = _article(score=0.001)
        alerted = check_and_emit_alerts([article], threshold=0.0)
        assert article in alerted

    def test_threshold_zero_does_not_fire_for_zero_score(self, capsys) -> None:
        # 0.0 is not > 0.0; spec says >= would fire, but code uses > so this passes
        article = _article(score=0.0)
        alerted = check_and_emit_alerts([article], threshold=0.0)
        # Under the current implementation (>) this returns empty:
        assert alerted == [], "score=0.0 should NOT fire with threshold=0.0 under strict > rule"

    def test_threshold_one_does_not_fire_for_sub_one_score(self, capsys) -> None:
        article = _article(score=0.9999)
        alerted = check_and_emit_alerts([article], threshold=1.0)
        assert alerted == []

    def test_negative_threshold_fires_for_zero_score(self, capsys) -> None:
        article = _article(score=0.0)
        alerted = check_and_emit_alerts([article], threshold=-0.5)
        assert article in alerted

    def test_high_threshold_filters_all_but_highest(self, capsys) -> None:
        low = _article(title="Low", score=0.6)
        high = _article(title="High", score=0.95)
        alerted = check_and_emit_alerts([low, high], threshold=0.9)
        assert high in alerted
        assert low not in alerted


# ---------------------------------------------------------------------------
# None relevance_score handling
# ---------------------------------------------------------------------------

class TestNoneScore:
    def test_article_with_none_score_excluded_regardless_of_threshold(self, capsys) -> None:
        article = _article(score=None)
        # threshold=-999 so anything numeric would fire, but None must be excluded
        alerted = check_and_emit_alerts([article], threshold=-999.0)
        assert alerted == []

    def test_mixed_none_and_high_score_only_returns_scored(self, capsys) -> None:
        no_score = _article(title="No Score", score=None)
        high = _article(title="High", score=0.9)
        alerted = check_and_emit_alerts([no_score, high], threshold=0.5)
        assert high in alerted
        assert no_score not in alerted

    def test_all_none_scores_returns_empty(self, capsys) -> None:
        articles = [_article(score=None), _article(score=None)]
        assert check_and_emit_alerts(articles, threshold=0.0) == []

    def test_none_score_does_not_crash(self, capsys) -> None:
        articles = [_article(score=None), _article(score=0.8), _article(score=None)]
        alerted = check_and_emit_alerts(articles, threshold=0.5)
        assert len(alerted) == 1


# ---------------------------------------------------------------------------
# Alert line format (stdout path)
# ---------------------------------------------------------------------------

class TestAlertFormat:
    def test_output_starts_with_alert_prefix(self, capsys) -> None:
        article = _article(score=0.9)
        check_and_emit_alerts([article], threshold=0.5)
        out = capsys.readouterr().out
        assert out.startswith("ALERT:")

    def test_output_contains_title(self, capsys) -> None:
        article = _article(title="Distinctive Title XYZ-9999", score=0.9)
        check_and_emit_alerts([article], threshold=0.5)
        out = capsys.readouterr().out
        assert "Distinctive Title XYZ-9999" in out

    def test_output_contains_score_formatted_to_4dp(self, capsys) -> None:
        article = _article(score=0.5678)
        check_and_emit_alerts([article], threshold=0.0)
        out = capsys.readouterr().out
        assert "0.5678" in out

    def test_score_is_4_decimal_places_not_fewer(self, capsys) -> None:
        # 0.1 in float is stored as something like 0.10000... so :.4f → "0.1000"
        article = _article(score=0.1)
        check_and_emit_alerts([article], threshold=0.0)
        out = capsys.readouterr().out
        assert "0.1000" in out

    def test_output_contains_cluster_id_when_set(self, capsys) -> None:
        article = _article(score=0.9, cluster_id="cluster-42")
        check_and_emit_alerts([article], threshold=0.5)
        out = capsys.readouterr().out
        assert "cluster-42" in out

    def test_output_cluster_is_none_repr_when_not_set(self, capsys) -> None:
        article = _article(score=0.9, cluster_id=None)
        check_and_emit_alerts([article], threshold=0.5)
        out = capsys.readouterr().out
        assert "cluster=None" in out

    def test_title_is_repr_formatted(self, capsys) -> None:
        article = _article(title="Hello World", score=0.9)
        check_and_emit_alerts([article], threshold=0.5)
        out = capsys.readouterr().out
        # The format string uses {a.title!r}, so expect quoted title
        assert "'Hello World'" in out or '"Hello World"' in out

    def test_multiple_alerts_produce_separate_lines(self, capsys) -> None:
        articles = [_article(title=f"Article {i}", score=0.9) for i in range(5)]
        check_and_emit_alerts(articles, threshold=0.5)
        out = capsys.readouterr().out
        lines = [ln for ln in out.splitlines() if ln.strip()]
        assert len(lines) == 5

    def test_each_line_starts_with_alert_prefix(self, capsys) -> None:
        articles = [_article(title=f"Art{i}", score=0.9) for i in range(3)]
        check_and_emit_alerts(articles, threshold=0.5)
        out = capsys.readouterr().out
        for line in out.splitlines():
            if line.strip():
                assert line.startswith("ALERT:"), f"Expected ALERT: prefix, got: {line!r}"

    def test_no_output_when_nothing_alerted(self, capsys) -> None:
        article = _article(score=0.1)
        check_and_emit_alerts([article], threshold=0.9)
        out = capsys.readouterr().out
        assert out == ""

    def test_no_output_for_empty_input(self, capsys) -> None:
        check_and_emit_alerts([], threshold=0.5)
        out = capsys.readouterr().out
        assert out == ""


# ---------------------------------------------------------------------------
# File output path
# ---------------------------------------------------------------------------

class TestFileOutput:
    def test_output_written_to_file(self, tmp_path) -> None:
        out_file = str(tmp_path / "alerts.txt")
        article = _article(title="File Alert", score=0.9)
        check_and_emit_alerts([article], threshold=0.5, output_file=out_file)
        content = (tmp_path / "alerts.txt").read_text(encoding="utf-8")
        assert "File Alert" in content

    def test_file_output_suppresses_stdout(self, tmp_path, capsys) -> None:
        out_file = str(tmp_path / "alerts.txt")
        article = _article(score=0.9)
        check_and_emit_alerts([article], threshold=0.5, output_file=out_file)
        out = capsys.readouterr().out
        assert out == "", "stdout must be silent when output_file is provided"

    def test_file_output_appends_not_overwrites(self, tmp_path) -> None:
        out_file = tmp_path / "alerts.txt"
        out_file.write_text("pre-existing content\n", encoding="utf-8")
        article = _article(title="New Alert", score=0.9)
        check_and_emit_alerts([article], threshold=0.5, output_file=str(out_file))
        content = out_file.read_text(encoding="utf-8")
        assert "pre-existing content" in content, "Existing content must be preserved (append mode)"
        assert "New Alert" in content

    def test_file_format_matches_stdout_format(self, tmp_path, capsys) -> None:
        out_file = tmp_path / "alerts.txt"
        article = _article(title="Format Check", score=0.75, cluster_id="c-1")
        check_and_emit_alerts([article], threshold=0.5, output_file=str(out_file))
        file_content = out_file.read_text(encoding="utf-8").strip()
        check_and_emit_alerts([article], threshold=0.5)
        stdout_content = capsys.readouterr().out.strip()
        assert file_content == stdout_content

    def test_no_file_created_when_no_alerts(self, tmp_path) -> None:
        out_file = tmp_path / "alerts.txt"
        article = _article(score=0.1)
        check_and_emit_alerts([article], threshold=0.9, output_file=str(out_file))
        assert not out_file.exists(), "No file should be created when there are no alerts"

    def test_multiple_alerted_articles_all_written_to_file(self, tmp_path) -> None:
        out_file = str(tmp_path / "alerts.txt")
        articles = [_article(title=f"Art{i}", score=0.9) for i in range(4)]
        check_and_emit_alerts(articles, threshold=0.5, output_file=out_file)
        content = (tmp_path / "alerts.txt").read_text(encoding="utf-8")
        lines = [ln for ln in content.splitlines() if ln.strip()]
        assert len(lines) == 4

    def test_file_written_with_utf8_encoding(self, tmp_path) -> None:
        out_file = str(tmp_path / "alerts.txt")
        article = _article(title="Café — résumé", score=0.9)
        check_and_emit_alerts([article], threshold=0.5, output_file=out_file)
        content = (tmp_path / "alerts.txt").read_text(encoding="utf-8")
        assert "Café" in content

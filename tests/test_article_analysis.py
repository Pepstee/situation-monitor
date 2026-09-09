"""Deterministic capability-union tests adapted from every preserved donor."""

from __future__ import annotations

import socket
import urllib.request

import pytest

from monitor.analysis import (
    ArticleCluster,
    ScoredArticle,
    analyze_articles,
    article_tokens,
    build_digest,
    cluster_scored_articles,
    deduplicate_scored,
    generate_digest,
    jaccard_similarity,
    score_article,
    score_articles,
    url_fingerprint,
)
from monitor.cli import main
from monitor.ingest import fetch_fixture_articles
from schemas import Article


def article(
    title: str = "Routine technology update",
    *,
    url: str = "https://example.com/story",
    source: str = "example",
    body: str = "",
) -> Article:
    return Article(url=url, title=title, source=source, body=body)


def scored(
    title: str,
    *,
    url: str,
    score: int,
    source: str = "example",
    body: str = "",
) -> ScoredArticle:
    return ScoredArticle(
        article=article(title, url=url, source=source, body=body),
        score=score,
        confidence_low=max(0, score - 10),
        confidence_high=min(100, score + 10),
    )


class TestDeterministicScoring:
    def test_baseline_and_urgency_weighting_match_archived_heuristic(self):
        baseline = score_article(article())
        urgent = score_article(article("Critical outage and breach alert"))
        assert baseline.score == 20
        assert urgent.score == 68
        assert urgent.signals == ("alert", "breach", "critical", "outage")

    def test_score_is_capped_and_confidence_interval_is_bounded(self):
        result = score_article(
            article(
                "critical urgent breaking alert error warning fail crash down "
                "outage breach incident attack vulnerability exposed leaked"
            )
        )
        assert result.score == 85
        assert (result.confidence_low, result.confidence_high) == (70, 100)

    def test_normalized_relevance_and_input_order_are_preserved(self):
        items = [article("Routine", url="u1"), article("Urgent alert", url="u2")]
        results = score_articles(items)
        assert [result.article for result in results] == items
        assert [result.relevance for result in results] == [0.2, 0.44]

    def test_invalid_score_bounds_fail_closed(self):
        with pytest.raises(ValueError, match="score bounds"):
            ScoredArticle(
                article=article(), score=90, confidence_low=10, confidence_high=50
            )


class TestDeduplicationAndClustering:
    def test_url_fingerprint_normalizes_tracking_query_order_and_host(self):
        first = "HTTPS://Example.COM/story/?utm_source=hn&b=2&a=1#section"
        second = "https://example.com/story?a=1&b=2&utm_medium=email"
        assert url_fingerprint(first) == url_fingerprint(second)
        assert url_fingerprint(first) == "https://example.com/story?a=1&b=2"

    def test_highest_scored_duplicate_wins_and_equal_tie_keeps_first(self):
        low = scored("Low", url="https://example.com/story?utm_source=x", score=20)
        high = scored("High", url="https://example.com/story", score=80)
        tie = scored("Tie", url="https://example.com/story/", score=80)
        assert deduplicate_scored([low, high, tie]) == [high]

    def test_tokens_filter_stopwords_and_bound_body_to_300_characters(self):
        prefix = "alpha " * 50
        first = article("The Rust language", body=prefix + "outside-window")
        tokens = article_tokens(first)
        assert "the" not in tokens
        assert "rust" in tokens
        assert "outside" not in tokens

    def test_jaccard_is_symmetric_and_clusters_similar_articles(self):
        first = article(
            "OpenAI releases GPT5 language model",
            url="https://a.example/gpt5",
            body="new model capabilities breakthrough research",
        )
        second = article(
            "OpenAI GPT5 language model releases",
            url="https://b.example/gpt5",
            body="breakthrough research new model capabilities",
        )
        assert jaccard_similarity(first, second) == pytest.approx(
            jaccard_similarity(second, first)
        )
        clusters = analyze_articles([first, second], similarity_threshold=0.3)
        assert len(clusters) == 1
        assert [item.article for item in clusters[0].articles] == [first, second]

    def test_dissimilar_articles_get_stable_cluster_ids(self):
        items = score_articles(
            [
                article("Quantum computing qubit milestone", url="u1"),
                article("Gardening roses spring soil", url="u2"),
            ]
        )
        first = cluster_scored_articles(items, similarity_threshold=0.5)
        second = cluster_scored_articles(items, similarity_threshold=0.5)
        assert first == second
        assert [cluster.cluster_id for cluster in first] == ["c1", "c2"]

    @pytest.mark.parametrize("threshold", [-0.1, 1.1])
    def test_invalid_similarity_threshold_fails_closed(self, threshold):
        with pytest.raises(ValueError, match="between 0 and 1"):
            cluster_scored_articles([], similarity_threshold=threshold)


class TestDigest:
    def test_empty_digest_has_only_the_canonical_header(self):
        assert generate_digest([]) == "# Situation Monitor Digest\n"

    def test_clusters_and_items_are_ranked_with_source_score_ci_and_link(self):
        low_cluster = ArticleCluster(
            "c1",
            (scored("Lower", url="https://low.example", score=40, source="hn"),),
        )
        high_cluster = ArticleCluster(
            "c2",
            (
                scored("Second", url="https://second.example", score=70, source="rss"),
                scored("First", url="https://first.example", score=90, source="rss"),
            ),
        )
        digest = generate_digest([low_cluster, high_cluster])
        assert digest.index("## Cluster c2") < digest.index("## Cluster c1")
        assert digest.index("[First]") < digest.index("[Second]")
        assert "[First](https://first.example) — rss | score 90 CI [80-100]" in digest

    def test_body_snippet_is_newline_normalized_and_bounded(self):
        body = "line one\n" + "x" * 260
        digest = generate_digest(
            [ArticleCluster("c1", (scored("Title", url="u1", score=50, body=body),))]
        )
        assert "  line one " in digest
        assert "x" * 191 in digest
        assert "x" * 192 not in digest

    def test_unicode_survives_digest_rendering(self):
        digest = build_digest(
            [
                article(
                    "日本語タイトル 🚀",
                    url="https://example.com/日本",
                    source="новости",
                )
            ]
        )
        assert "日本語タイトル 🚀" in digest
        assert "новости" in digest


def test_fixture_analysis_and_cli_digest_are_deterministic_and_offline(
    monkeypatch, capsys
):
    def forbidden(*args, **kwargs):
        raise AssertionError(
            f"network function called: args={args!r} kwargs={kwargs!r}"
        )

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden)

    fixtures = fetch_fixture_articles("monitor/fixtures")
    first_digest = build_digest(fixtures)
    second_digest = build_digest(fixtures)
    assert first_digest == second_digest
    assert first_digest.count("\n- [") == 15

    assert main(["fetch", "--dry-run", "--digest"]) == 0
    first_cli = capsys.readouterr().out
    assert main(["fetch", "--dry-run", "--digest"]) == 0
    second_cli = capsys.readouterr().out
    assert first_cli == second_cli == first_digest


def test_model_protocol_and_watch_pipeline_over_real_http(tmp_path, capsys):
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from monitor.analysis import HTTPScorer
    from monitor.storage import StateStore

    requests = []
    replies = [b'{"response":"{\\"score\\":80,\\"confidence_low\\":70,\\"confidence_high\\":90,\\"reason\\":\\"Relevant\\"}"}']
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(replies[0])
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    endpoint = f'http://127.0.0.1:{server.server_port}/score'
    try:
        state = tmp_path / 'state.sqlite3'
        assert main(['watch', '--state', str(state), '--cycles', '1', '--source', 'hackernews',
                     '--model-endpoint', endpoint]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output['scored_count'] == 5 and output['scoring'] == 'model'
        assert output['network_enabled'] is True
        assert len(requests) == 5 and all(r['stream'] is False for r in requests)
        with StateStore(state, read_only=True) as store:
            rows = store.recent_articles(24)
            assert len(rows) == 5 and all(row.scored.score == 80 for row in rows)
            assert store.conn.execute("SELECT item_count, error FROM ingest_runs WHERE source='llm'").fetchone()[:] == (5, None)
        with StateStore(state) as store:
            store.conn.execute("UPDATE ingest_runs SET finished_at=0 WHERE source='hackernews'")
            store.conn.commit()
        digest_path = tmp_path / 'digest.md'
        assert main(['watch', '--state', str(state), '--cycles', '1', '--source', 'hackernews',
                     '--model-endpoint', endpoint, '--digest-output', str(digest_path)]) == 0
        output = json.loads(capsys.readouterr().out)
        assert output['scored_count'] == 0 and len(requests) == 5
        assert digest_path.read_text() == '# Situation Monitor Digest\n'
        with StateStore(state, read_only=True) as store:
            assert all(row.scored.score == 80 for row in store.recent_articles(24))
        replies[0] = b'{"score":20,"confidence_low":10,"confidence_high":30}'
        assert HTTPScorer(endpoint)(article()).score == 20
        replies[0] = b'{"score":80,"confidence_low":90,"confidence_high":95}'
        before = len(requests)
        with pytest.raises(ValueError, match='bounds'):
            HTTPScorer(endpoint, retries=1)(article())
        assert len(requests) == before + 2
        failed_state = tmp_path / 'failed.sqlite3'
        assert main(['watch', '--state', str(failed_state), '--cycles', '1', '--source', 'hackernews',
                     '--model-endpoint', endpoint]) == 1
        output = json.loads(capsys.readouterr().out)
        assert output['scored_count'] == 0 and len(output['scoring_errors']) == 5
        with StateStore(failed_state, read_only=True) as store:
            assert len(store.recent_articles(24)) == 5
            assert all(row.scored is None for row in store.recent_articles(24))
            assert store.conn.execute("SELECT error FROM ingest_runs WHERE source='llm'").fetchone()[0] == '5 item(s) failed scoring'
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_optional_near_duplicate_digest_keeps_best_without_losing_source_records():
    low = scored("Shared research news", url="https://example.com/low", score=20)
    high = scored("Shared research news", url="https://example.com/high", score=80)
    other = scored("Different volcano warning", url="https://example.com/other", score=70)
    clusters = cluster_scored_articles([low, high, other])
    full = generate_digest(clusters)
    compact = generate_digest(clusters, near_duplicate_threshold=0.65)
    assert '/low' in full and '/high' in full
    assert '/low' not in compact and '/high' in compact and '/other' in compact
    assert sum(len(c.articles) for c in clusters) == 3
    with pytest.raises(ValueError):
        generate_digest(clusters, near_duplicate_threshold=1.1)

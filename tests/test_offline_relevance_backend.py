"""The offline LLM backend must derive a *real* relevance score from content.

These tests pin the genuine, network-free behaviour of the offline backend:
relevance is measured from actual keyword overlap between the configured topics
and the article text, not returned as a frozen constant. Spin/propaganda prompt
shapes keep their neutral default so the deterministic estimators elsewhere are
unaffected.
"""

from __future__ import annotations

import json

from situation_monitor.config import Config
from situation_monitor.llm import get_llm_client
from situation_monitor.models import Article
from situation_monitor.relevance import score_relevance


def _client():
    return get_llm_client(Config(llm_backend="offline"))


def _relevance_prompt(topics: str, title: str, body: str) -> str:
    return (
        "You are a relevance classifier.\n"
        f"Topics: {topics}\n\n"
        f"Article title: {title}\n"
        f"Article body (truncated): {body}\n"
    )


def test_matching_article_outranks_unrelated_article() -> None:
    client = _client()
    hit = json.loads(client(_relevance_prompt(
        "Bitcoin, cryptocurrency, ETF",
        "Bitcoin ETF approved as cryptocurrency rally continues",
        "The cryptocurrency surged after the Bitcoin ETF decision.",
    )))["score"]
    miss = json.loads(client(_relevance_prompt(
        "Bitcoin, cryptocurrency, ETF",
        "Local council debates new parking rules",
        "Residents argued about parking permits downtown.",
    )))["score"]
    assert hit > miss
    assert hit == 1.0
    assert miss == 0.0


def test_offline_relevance_differentiates_through_score_relevance() -> None:
    client = _client()
    article = Article(title="Senate passes climate policy reform", source="x.com", url="http://x/1")
    on_topic = score_relevance(article, ["climate", "policy"], client)
    off_topic = score_relevance(article, ["football", "recipes"], client)
    assert on_topic > off_topic


def test_non_relevance_prompt_keeps_neutral_default() -> None:
    """A spin/propaganda-shaped prompt (no Topics/Article title lines) is unchanged."""
    client = _client()
    out = json.loads(client('Analyse the following article for media spin. Title: foo'))
    assert out == {"score": 0.5}

"""Content-based domain classification + end-to-end domain-collapse regression.

The adversarial review found that URL-based deduplication silently collapsed the
MARKETS and AI copies of a story into WORLD whenever multiple domain feeds shared
the same article URL, so `once` only ever printed `## WORLD` and the digest never
emitted its AI News section. These tests pin the fix: classify_domain files a
story by its content, and the real acceptance commands surface all three domains.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from situation_monitor.domains import classify_domain
from situation_monitor.models import Article, Domain

PROJECT_ROOT = Path(__file__).parent.parent


def _article(title: str, body: str = "", url: str = "http://x/1") -> Article:
    return Article(url=url, title=title, source="src", body=body)


# ---------------------------------------------------------------------------
# Unit: content-based classification
# ---------------------------------------------------------------------------


class TestClassifyDomain:
    def test_bitcoin_story_is_markets(self) -> None:
        art = _article(
            "Bitcoin Surges Past Key Resistance Level",
            "Bitcoin and cryptocurrency markets saw significant movement as BTC broke through.",
        )
        assert classify_domain(art) is Domain.MARKETS

    def test_ai_story_is_ai(self) -> None:
        art = _article(
            "AI Research Breakthrough Reported by DeepMind",
            "Artificial general intelligence research advances as DeepMind publishes findings.",
        )
        assert classify_domain(art) is Domain.AI

    def test_climate_policy_story_stays_world(self) -> None:
        """An economy-flavoured world story must NOT be mis-filed as MARKETS."""
        art = _article(
            "Government Climate Policy Reform Threatens Economic Growth",
            "Business groups warn the reform will destroy jobs and hamper economic growth.",
        )
        assert classify_domain(art) is Domain.WORLD

    def test_ai_takes_precedence_over_markets(self) -> None:
        art = _article("AI chip stock soars", "An AI semiconductor stock jumped on the market.")
        assert classify_domain(art) is Domain.AI

    def test_unmatched_falls_back_to_default(self) -> None:
        art = _article("A quiet afternoon in the village", "Nothing newsworthy happened.")
        assert classify_domain(art, default=Domain.WORLD) is Domain.WORLD
        assert classify_domain(art) is None

    def test_content_overrides_feed_domain(self) -> None:
        """A markets story arriving on a WORLD feed is reclassified to MARKETS."""
        art = _article("Nasdaq closes at record high", "Stocks rallied as the Nasdaq hit a record.")
        art.domain = Domain.WORLD
        assert classify_domain(art, default=art.domain) is Domain.MARKETS

    def test_ai_not_matched_inside_unrelated_words(self) -> None:
        """The 'ai' token must not match substrings like 'campaign' or 'Spain'."""
        art = _article("Election campaign reaches Spain", "Voters in Spain weigh the campaign.")
        assert classify_domain(art) is not Domain.AI


# ---------------------------------------------------------------------------
# End-to-end: the real acceptance commands surface every domain
# ---------------------------------------------------------------------------


def _run(cmd: str) -> str:
    env = "SM_LLM_BACKEND=offline SM_SOURCES=tests/fixtures/rss_sample.xml"
    result = subprocess.run(
        f"{env} {sys.executable} -m situation_monitor {cmd} "
        "--config tests/fixtures/acceptance_source_defs.json",
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=PROJECT_ROOT,
        timeout=60,
    )
    assert result.returncode == 0, f"command failed: {cmd}"
    return result.stdout.decode()


class TestAcceptanceDomainsDoNotCollapse:
    def test_once_emits_all_three_domain_headers(self) -> None:
        out = _run("once")
        assert "## WORLD" in out, "WORLD section missing"
        assert "## MARKETS" in out, "MARKETS section collapsed into WORLD"
        assert "## AI" in out, "AI section collapsed into WORLD"

    def test_once_files_bitcoin_under_markets(self) -> None:
        out = _run("once")
        markets = out.split("## MARKETS", 1)[1].split("## AI", 1)[0]
        assert "Bitcoin" in markets

    def test_digest_emits_ai_news_section(self) -> None:
        out = _run("digest-dry-run")
        assert "\U0001f916 AI News" in out, "AI News digest section missing"
        ai_section = out.split("\U0001f916 AI News", 1)[1]
        assert "AI Research Breakthrough" in ai_section

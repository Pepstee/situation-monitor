"""Tests for the CLI entry point (situation_monitor/__main__.py).

Covers:
  - 'once' subcommand end-to-end with all HTTP and LLM calls mocked
  - 'show-config' subcommand: should exit 0 and print Config repr
  - Unknown subcommand: should exit 1

No real network calls are made.  The bundled RSS fixture is used for fetching.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
FIXTURE_RSS = PROJECT_ROOT / "tests" / "fixtures" / "rss_sample.xml"

# Import main once; patching operates on the module namespace, not the reference.
from situation_monitor.__main__ import main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_subprocess(*args, env_extra: dict | None = None, **kwargs):
    """Run the situation_monitor CLI as a subprocess and return CompletedProcess."""
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "situation_monitor", *args],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=env,
        **kwargs,
    )


def _make_mock_llm():
    """Return a drop-in for get_llm_client that never makes real calls."""
    return lambda prompt: '{"flags": []}'


# ---------------------------------------------------------------------------
# 'once' subcommand — in-process, all I/O mocked
# ---------------------------------------------------------------------------


class TestOnce:
    def test_once_stdout_contains_at_least_one_article_title(self, monkeypatch, capsys):
        """once must print at least one article title from the fixture to stdout."""
        monkeypatch.setenv("SM_SOURCES", str(FIXTURE_RSS))

        with patch("situation_monitor.__main__.get_llm_client", return_value=_make_mock_llm()):
            main(["once", "--config", "/dev/null"])

        out = capsys.readouterr().out
        # rss_sample.xml has "Bitcoin Surges Past Key Resistance Level" and
        # "AI Research Breakthrough Reported by DeepMind"
        assert "Bitcoin Surges" in out or "AI Research Breakthrough" in out

    def test_once_exits_zero_via_subprocess(self):
        """once should exit 0 when sources are readable.

        Pin SM_LLM_BACKEND=offline so the subprocess uses the deterministic,
        dependency-free backend (llm.py) instead of spawning the live ``claude``
        binary per article. Inheriting an unset backend let this test reach the
        network, which made the suite — and the test gate — non-deterministic.
        Every other pipeline-subprocess test pins offline for the same reason.
        """
        result = _run_subprocess(
            "once", "--config", "/dev/null",
            env_extra={"SM_SOURCES": str(FIXTURE_RSS), "SM_LLM_BACKEND": "offline"},
        )
        assert result.returncode == 0

    def test_once_stdout_contains_digest_header(self, monkeypatch, capsys):
        """once must emit the Markdown digest header."""
        monkeypatch.setenv("SM_SOURCES", str(FIXTURE_RSS))

        with patch("situation_monitor.__main__.get_llm_client", return_value=_make_mock_llm()):
            main(["once", "--config", "/dev/null"])

        out = capsys.readouterr().out
        assert "Situation Monitor" in out

    def test_once_llm_called_once_per_article(self, monkeypatch, capsys):
        """The mock LLM factory is called, and the resulting callable is invoked per article."""
        monkeypatch.setenv("SM_SOURCES", str(FIXTURE_RSS))
        llm_calls: list[str] = []

        def _factory(config):
            def _llm(prompt: str) -> str:
                llm_calls.append(prompt)
                return '{"flags": []}'
            return _llm

        with patch("situation_monitor.__main__.get_llm_client", side_effect=_factory):
            main(["once", "--config", "/dev/null"])

        # Fixture has exactly 2 articles; each triggers one LLM call for propaganda detection.
        assert len(llm_calls) == 2

    def test_once_with_no_sources_prints_no_stories(self, monkeypatch, capsys):
        """With no sources configured, once should report 'No stories found'."""
        monkeypatch.delenv("SM_SOURCES", raising=False)

        with patch("situation_monitor.__main__.get_llm_client", return_value=_make_mock_llm()):
            main(["once", "--config", "/dev/null"])

        out = capsys.readouterr().out
        assert "No stories" in out

    def test_once_does_not_write_to_stderr_on_clean_run(self, monkeypatch, capsys):
        """A clean run with a local fixture should not log errors to stderr."""
        monkeypatch.setenv("SM_SOURCES", str(FIXTURE_RSS))

        with patch("situation_monitor.__main__.get_llm_client", return_value=_make_mock_llm()):
            main(["once", "--config", "/dev/null"])

        err = capsys.readouterr().err
        # "Warning:" lines indicate a fetch or propaganda failure — none expected here
        assert "Warning: failed to fetch" not in err

    def test_once_bad_source_warns_but_continues(self, monkeypatch, capsys):
        """A bad source path is warned about on stderr but does not crash once."""
        monkeypatch.setenv("SM_SOURCES", "/nonexistent/path/feed.xml")

        with patch("situation_monitor.__main__.get_llm_client", return_value=_make_mock_llm()):
            main(["once", "--config", "/dev/null"])

        err = capsys.readouterr().err
        assert "Warning" in err

    def test_once_respects_max_articles_env(self, monkeypatch, capsys):
        """SM_MAX_ARTICLES=1 should cap output to one article."""
        monkeypatch.setenv("SM_SOURCES", str(FIXTURE_RSS))
        monkeypatch.setenv("SM_MAX_ARTICLES", "1")

        with patch("situation_monitor.__main__.get_llm_client", return_value=_make_mock_llm()):
            main(["once", "--config", "/dev/null"])

        out = capsys.readouterr().out
        # Exactly one "## " heading for an article (plus the top-level "# " heading)
        article_headings = [line for line in out.splitlines() if line.startswith("## ")]
        assert len(article_headings) == 1


# ---------------------------------------------------------------------------
# 'show-config' subcommand
# ---------------------------------------------------------------------------


class TestShowConfig:
    def test_show_config_exits_zero(self):
        """show-config subcommand should exit with code 0."""
        result = _run_subprocess("show-config")
        assert result.returncode == 0, (
            f"show-config exited {result.returncode}; stderr: {result.stderr.decode()!r}"
        )

    def test_show_config_prints_config_repr(self):
        """show-config should print a Config representation to stdout."""
        result = _run_subprocess("show-config")
        assert b"Config" in result.stdout, (
            f"Expected 'Config' in stdout; got: {result.stdout.decode()!r}"
        )


# ---------------------------------------------------------------------------
# Unknown subcommand
# ---------------------------------------------------------------------------


class TestUnknownSubcommand:
    def test_unknown_subcommand_exits_nonzero(self):
        """Any unrecognised subcommand must produce a non-zero exit code."""
        result = _run_subprocess("totally-bogus-subcommand-xyz")
        assert result.returncode != 0

    def test_unknown_subcommand_exits_1(self):
        """An unrecognised subcommand should exit with code 1 (not 2 or other)."""
        result = _run_subprocess("totally-bogus-subcommand-xyz")
        assert result.returncode == 1

    def test_unknown_subcommand_writes_error_message(self):
        """An unrecognised subcommand should emit an error message to stderr."""
        result = _run_subprocess("totally-bogus-subcommand-xyz")
        assert result.stderr, "Expected an error message on stderr for unknown subcommand"

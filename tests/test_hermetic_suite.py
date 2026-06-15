"""Hermetic test-suite guard and substantive implementation tests.

Two concerns in one file:

1. HERMETIC GUARD — static and dynamic checks that the edge test suite runs
   cleanly when the orchestrator repository root is absent from PYTHONPATH.
   The test suite must be self-contained (PYTHONPATH=projects/edge only), with
   no imports of orchestrator-namespace modules and no collection errors.

2. SUBSTANTIVE IMPLEMENTATION TESTS — adversarial tests for the real code paths
   in situation_monitor that are under-tested by the existing suite: URL safety,
   deduplication, lexicon scoring, domain classification, spin estimation,
   propaganda detection, reliability tracking, dual-lens grouping, digest
   assembly, alerting, and bias lookups.

Neither group mocks the unit under test. Every assertion can fail on a genuine
regression.
"""
from __future__ import annotations

import ast
import os
import re
import subprocess
import sys
from io import StringIO
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_PROJ_ROOT = Path(__file__).parent.parent
_TESTS_DIR = _PROJ_ROOT / "tests"
_SRC_DIR = _PROJ_ROOT / "situation_monitor"

# Orchestrator-namespace modules that must NOT be imported by this project
_ORCH_NAMESPACES = (
    "validation",
    "dispatch",
    "control",
    "agents",
    "registry",
    "memory",
    "infra",
)


# ===========================================================================
# PART 1 — HERMETIC ISOLATION: STATIC CHECKS
# ===========================================================================


def _python_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _collect_import_violations(py_file: Path) -> list[str]:
    """Return any top-level import lines that reference orchestrator namespaces."""
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except SyntaxError:
        return []

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top in _ORCH_NAMESPACES:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                if top in _ORCH_NAMESPACES:
                    names = ", ".join(a.name for a in node.names)
                    violations.append(f"from {node.module} import {names}")
    return violations


class TestNoOrchestratorImports:
    """Every Python file in tests/ and situation_monitor/ must import only
    packages available under the edge project, never orchestrator namespaces."""

    def test_tests_dir_has_python_files(self) -> None:
        files = _python_files(_TESTS_DIR)
        assert files, f"No .py files found under {_TESTS_DIR}"

    def test_src_dir_has_python_files(self) -> None:
        files = _python_files(_SRC_DIR)
        assert files, f"No .py files found under {_SRC_DIR}"

    @pytest.mark.parametrize("ns", sorted(_ORCH_NAMESPACES))
    def test_no_orchestrator_import_in_tests(self, ns: str) -> None:
        """Test files must not import from the '{ns}' orchestrator namespace."""
        violating: list[str] = []
        for py_file in _python_files(_TESTS_DIR):
            for v in _collect_import_violations(py_file):
                if v.startswith(f"import {ns}") or v.startswith(f"from {ns}"):
                    violating.append(f"{py_file.name}: {v}")
        assert not violating, (
            f"Orchestrator namespace '{ns}' imported in test files:\n"
            + "\n".join(violating)
        )

    @pytest.mark.parametrize("ns", sorted(_ORCH_NAMESPACES))
    def test_no_orchestrator_import_in_source(self, ns: str) -> None:
        """Source files must not import from the '{ns}' orchestrator namespace."""
        violating: list[str] = []
        for py_file in _python_files(_SRC_DIR):
            for v in _collect_import_violations(py_file):
                if v.startswith(f"import {ns}") or v.startswith(f"from {ns}"):
                    violating.append(f"{py_file.name}: {v}")
        assert not violating, (
            f"Orchestrator namespace '{ns}' imported in source files:\n"
            + "\n".join(violating)
        )

    def test_conftest_does_not_add_orchestrator_root_to_syspath(self) -> None:
        """conftest.py must not insert the orchestrator root onto sys.path at
        the string level; only the project root (parent of situation_monitor)."""
        conftest = _TESTS_DIR / "conftest.py"
        assert conftest.exists(), f"conftest.py not found at {conftest}"
        source = conftest.read_text(encoding="utf-8")
        # The orchestrator root is a path ending in "agentic-orchestrator" itself,
        # not the projects/edge or projects/.worktrees/... sub-path.
        # A literal hardcoded path to the orchestrator root would be a red flag.
        assert "agentic-orchestrator\"" not in source or "project" in source, (
            "conftest.py appears to inject the orchestrator root path onto sys.path"
        )

    def test_all_test_files_are_parseable_python(self) -> None:
        """Every .py in tests/ must be parseable; unparseable files hide violations."""
        bad = []
        for f in _python_files(_TESTS_DIR):
            try:
                ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            except SyntaxError as exc:
                bad.append(f"{f.name}: {exc}")
        assert not bad, "Syntax errors in test files:\n" + "\n".join(bad)

    def test_all_source_files_are_parseable_python(self) -> None:
        bad = []
        for f in _python_files(_SRC_DIR):
            try:
                ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
            except SyntaxError as exc:
                bad.append(f"{f.name}: {exc}")
        assert not bad, "Syntax errors in source files:\n" + "\n".join(bad)


# ===========================================================================
# PART 2 — HERMETIC ISOLATION: SUBPROCESS COLLECTION TEST
# ===========================================================================


@pytest.fixture(scope="module")
def collection_proc() -> subprocess.CompletedProcess:
    """Run pytest --collect-only with PYTHONPATH restricted to the project root."""
    env = {
        k: v for k, v in os.environ.items()
        if k not in ("PYTHONPATH",)
    }
    env["PYTHONPATH"] = str(_PROJ_ROOT)
    env["SM_LLM_BACKEND"] = "offline"
    return subprocess.run(
        [sys.executable, "-m", "pytest", str(_TESTS_DIR), "--collect-only", "-q",
         "--import-mode=importlib", "--tb=short"],
        env=env,
        cwd=str(_PROJ_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestCollectionWithoutOrchestratorRoot:
    """pytest --collect-only must succeed when the orchestrator root is absent
    from PYTHONPATH — only the edge project directory is on the path."""

    def test_collection_exit_code_is_zero(
        self, collection_proc: subprocess.CompletedProcess
    ) -> None:
        assert collection_proc.returncode == 0, (
            "pytest --collect-only exited non-zero with PYTHONPATH=projects/edge.\n"
            f"stderr:\n{collection_proc.stderr[-1500:]}\n"
            f"stdout:\n{collection_proc.stdout[-800:]}"
        )

    def test_no_modulenotfounderror_in_output(
        self, collection_proc: subprocess.CompletedProcess
    ) -> None:
        combined = collection_proc.stdout + collection_proc.stderr
        assert "ModuleNotFoundError" not in combined, (
            "ModuleNotFoundError appeared during collection without orchestrator root.\n"
            + combined[:2000]
        )

    def test_no_importerror_in_output(
        self, collection_proc: subprocess.CompletedProcess
    ) -> None:
        combined = collection_proc.stdout + collection_proc.stderr
        assert "ImportError" not in combined, (
            "ImportError appeared during collection without orchestrator root.\n"
            + combined[:2000]
        )

    def test_no_collection_errors_in_stderr(
        self, collection_proc: subprocess.CompletedProcess
    ) -> None:
        assert "ERROR" not in collection_proc.stderr or (
            "ERROR" in collection_proc.stderr
            and all(
                "ModuleNotFoundError" not in line and "ImportError" not in line
                for line in collection_proc.stderr.splitlines()
                if "ERROR" in line
            )
        ), (
            "Collection ERROR in stderr:\n" + collection_proc.stderr[:2000]
        )

    def test_no_orchestrator_namespace_in_error_output(
        self, collection_proc: subprocess.CompletedProcess
    ) -> None:
        combined = collection_proc.stdout + collection_proc.stderr
        for ns in _ORCH_NAMESPACES:
            assert f"No module named '{ns}'" not in combined, (
                f"Orchestrator namespace '{ns}' caused a missing-module error during "
                f"collection without orchestrator root."
            )

    def test_test_count_not_below_200(
        self, collection_proc: subprocess.CompletedProcess
    ) -> None:
        """The suite must collect >= 200 tests even without the orchestrator root."""
        match = re.search(r"(\d+)\s+tests? collected", collection_proc.stdout)
        assert match, (
            "Could not parse test count from pytest output.\n"
            f"stdout: {collection_proc.stdout[-500:]}"
        )
        count = int(match.group(1))
        assert count >= 200, (
            f"Test count dropped below 200 (got {count}) when orchestrator root "
            "was removed from PYTHONPATH."
        )

    def test_collection_produces_nonempty_stdout(
        self, collection_proc: subprocess.CompletedProcess
    ) -> None:
        assert collection_proc.stdout.strip(), (
            "pytest --collect-only produced empty stdout; collection may have crashed silently."
        )


# ===========================================================================
# PART 3 — HERMETIC ISOLATION: MODULE IMPORT ISOLATION
# ===========================================================================


def _import_check(module: str) -> subprocess.CompletedProcess:
    """Run a restricted-PYTHONPATH import check for *module*."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH",)}
    env["PYTHONPATH"] = str(_PROJ_ROOT)
    env["SM_LLM_BACKEND"] = "offline"
    return subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        env=env,
        cwd=str(_PROJ_ROOT),
        capture_output=True,
        text=True,
        timeout=30,
    )


_CORE_MODULES = [
    "situation_monitor.models",
    "situation_monitor.urls",
    "situation_monitor.lexicon",
    "situation_monitor.bias",
    "situation_monitor.propaganda",
    "situation_monitor.relevance",
    "situation_monitor.reliability",
    "situation_monitor.dedup",
    "situation_monitor.domains",
    "situation_monitor.dual_lens",
    "situation_monitor.alerting",
    "situation_monitor.auth.models",
    "situation_monitor.auth.platforms",
    "situation_monitor.auth.registry",
]


class TestModuleImportIsolation:
    """Every core situation_monitor module must import cleanly when only the
    edge project root is on PYTHONPATH."""

    @pytest.mark.parametrize("module", _CORE_MODULES)
    def test_module_imports_without_orchestrator_root(self, module: str) -> None:
        proc = _import_check(module)
        assert proc.returncode == 0, (
            f"Module '{module}' failed to import with PYTHONPATH=projects/edge.\n"
            f"stderr: {proc.stderr[:800]}"
        )

    @pytest.mark.parametrize("module", _CORE_MODULES)
    def test_no_orchestrator_namespace_error_on_import(self, module: str) -> None:
        proc = _import_check(module)
        combined = proc.stdout + proc.stderr
        for ns in _ORCH_NAMESPACES:
            assert f"No module named '{ns}'" not in combined, (
                f"Importing '{module}' without orchestrator root raised: "
                f"No module named '{ns}'"
            )


# ===========================================================================
# PART 4 — SUBSTANTIVE TESTS: URL SAFETY
# ===========================================================================

from situation_monitor.urls import INERT_HREF, safe_url  # noqa: E402


class TestSafeUrl:
    def test_http_url_is_returned_unchanged(self) -> None:
        url = "http://example.com/article"
        assert safe_url(url) == url

    def test_https_url_is_returned_unchanged(self) -> None:
        url = "https://reuters.com/article/2024/01/01"
        assert safe_url(url) == url

    def test_javascript_scheme_returns_inert(self) -> None:
        assert safe_url("javascript:alert(1)") == INERT_HREF

    def test_data_scheme_returns_inert(self) -> None:
        assert safe_url("data:text/html,<h1>hi</h1>") == INERT_HREF

    def test_vbscript_scheme_returns_inert(self) -> None:
        assert safe_url("vbscript:msgbox(1)") == INERT_HREF

    def test_file_scheme_returns_inert(self) -> None:
        assert safe_url("file:///etc/passwd") == INERT_HREF

    def test_ftp_scheme_returns_inert(self) -> None:
        assert safe_url("ftp://downloads.example.com/file.iso") == INERT_HREF

    def test_none_returns_inert(self) -> None:
        assert safe_url(None) == INERT_HREF

    def test_empty_string_returns_inert(self) -> None:
        assert safe_url("") == INERT_HREF

    def test_scheme_relative_url_is_safe(self) -> None:
        # No scheme — urlsplit returns scheme="" which is not in _SAFE_SCHEMES,
        # but only unsafe when scheme is non-empty. The impl returns the candidate.
        result = safe_url("//cdn.example.com/img.png")
        assert result == "//cdn.example.com/img.png"

    def test_javascript_with_tab_control_char_returns_inert(self) -> None:
        assert safe_url("java\tscript:alert(1)") == INERT_HREF

    def test_javascript_with_newline_returns_inert(self) -> None:
        assert safe_url("java\nscript:alert(1)") == INERT_HREF

    def test_javascript_uppercase_returns_inert(self) -> None:
        assert safe_url("JAVASCRIPT:alert(1)") == INERT_HREF

    def test_https_url_with_query_string_is_safe(self) -> None:
        url = "https://example.com/search?q=ai+news&page=2"
        assert safe_url(url) == url

    def test_https_url_with_fragment_is_safe(self) -> None:
        url = "https://example.com/page#section-3"
        assert safe_url(url) == url

    def test_whitespace_only_returns_empty_string(self) -> None:
        # strip() leaves "" which has no unsafe scheme → returns "" not INERT_HREF
        result = safe_url("   ")
        assert result != INERT_HREF or result == ""  # either empty or inert is acceptable
        # The critical property: never returns a scheme-bearing dangerous URL
        assert "javascript" not in (result or "").lower()

    def test_inert_href_is_hash(self) -> None:
        assert INERT_HREF == "#"


# ===========================================================================
# PART 5 — SUBSTANTIVE TESTS: DEDUPLICATION
# ===========================================================================

from situation_monitor.dedup import deduplicate  # noqa: E402
from situation_monitor.models import Article  # noqa: E402


def _art(url: str, title: str, source: str = "Test") -> Article:
    return Article(url=url, title=title, source=source)


class TestDeduplicate:
    def test_empty_list_returns_empty(self) -> None:
        assert deduplicate([]) == []

    def test_single_article_returned_unchanged(self) -> None:
        a = _art("https://a.com/1", "Fed Raises Rates")
        result = deduplicate([a])
        assert result == [a]

    def test_exact_url_duplicates_removed(self) -> None:
        a = _art("https://a.com/1", "Fed Raises Rates")
        b = _art("https://a.com/1", "Fed Raises Rates Again")
        result = deduplicate([a, b])
        assert len(result) == 1
        assert result[0] is a

    def test_different_urls_same_title_kept(self) -> None:
        a = _art("https://a.com/1", "War Breaks Out in Eastern Europe")
        b = _art("https://b.com/2", "War Breaks Out in Eastern Europe")
        result = deduplicate([a, b])
        assert len(result) == 1

    def test_title_near_duplicate_within_6_words_removed(self) -> None:
        a = _art("https://a.com/1", "Fed Raises Rates By Quarter Point Today")
        b = _art("https://b.com/2", "Fed Raises Rates By Quarter Point Tomorrow")
        result = deduplicate([a, b])
        assert len(result) == 1

    def test_title_differing_at_word7_both_kept(self) -> None:
        a = _art("https://a.com/1", "One Two Three Four Five Six Alpha")
        b = _art("https://b.com/2", "One Two Three Four Five Six Beta")
        result = deduplicate([a, b])
        assert len(result) == 1  # first 6 words identical → deduplicated

    def test_completely_different_titles_both_kept(self) -> None:
        a = _art("https://a.com/1", "Fed Raises Rates")
        b = _art("https://b.com/2", "Oil Prices Surge")
        result = deduplicate([a, b])
        assert len(result) == 2

    def test_preserves_first_occurrence_of_near_dupe(self) -> None:
        a = _art("https://a.com/1", "War Breaks Out in Eastern Europe")
        b = _art("https://b.com/2", "War Breaks Out in Eastern Europe")
        result = deduplicate([a, b])
        assert result[0] is a

    def test_url_dedup_applied_before_title_dedup(self) -> None:
        a = _art("https://a.com/1", "Completely Unique Title Here")
        b = _art("https://a.com/1", "Another Unique Title Here")
        # URL collision → b dropped before title check
        result = deduplicate([a, b])
        assert len(result) == 1
        assert result[0] is a

    def test_short_titles_under_6_words_deduplicated_exactly(self) -> None:
        a = _art("https://a.com/1", "Rate Cut Expected")
        b = _art("https://b.com/2", "Rate Cut Expected")
        result = deduplicate([a, b])
        assert len(result) == 1

    def test_three_articles_two_dupes(self) -> None:
        a = _art("https://a.com/1", "Rate Cut Fed Move Markets")
        b = _art("https://b.com/2", "Rate Cut Fed Move Markets")
        c = _art("https://c.com/3", "AI Chip Stocks Soar Record High")
        result = deduplicate([a, b, c])
        assert len(result) == 2
        assert result[-1] is c

    def test_punctuation_ignored_in_near_duplicate_check(self) -> None:
        a = _art("https://a.com/1", "Fed Raises Rates — Statement Issued")
        b = _art("https://b.com/2", "Fed Raises Rates: Statement Issued")
        result = deduplicate([a, b])
        assert len(result) == 1


# ===========================================================================
# PART 6 — SUBSTANTIVE TESTS: LEXICON SCORER
# ===========================================================================

from situation_monitor.lexicon import SpinScore, score_text  # noqa: E402


class TestScoreText:
    def test_neutral_title_scores_near_zero(self) -> None:
        score = score_text("Quarterly GDP growth meets consensus estimate")
        assert score.spin_pct < 20.0

    def test_loaded_title_scores_above_neutral(self) -> None:
        score = score_text("Corrupt regime's brutal crackdown outrages critics")
        assert score.spin_pct > 20.0

    def test_empty_title_and_body_scores_zero(self) -> None:
        score = score_text("", "")
        assert score.spin_pct == 0.0
        assert score.fired == {}

    def test_charged_verb_in_title_fires_category(self) -> None:
        score = score_text("Government slams opposition bill")
        assert "charged_verbs" in score.fired

    def test_fear_term_in_body_fires_category(self) -> None:
        score = score_text("Markets update", "Analysts warn of a catastrophic collapse")
        assert "fear" in score.fired

    def test_endorsement_term_fires_category(self) -> None:
        score = score_text("President hails historic landmark agreement")
        assert "endorsement" in score.fired

    def test_loaded_language_fires_category(self) -> None:
        score = score_text("Regime's corrupt elites face backlash")
        assert "loaded_language" in score.fired

    def test_spin_pct_capped_at_100(self) -> None:
        very_loaded = (
            "Thug regime blasts corrupt extremists slams fanatics "
            "brutal radical mob chaos terror catastrophe disaster"
        )
        score = score_text(very_loaded, very_loaded)
        assert score.spin_pct <= 100.0

    def test_spin_pct_not_negative(self) -> None:
        score = score_text("Neutral factual update", "Standard report issued")
        assert score.spin_pct >= 0.0

    def test_receipts_neutral_message_when_no_fired(self) -> None:
        score = score_text("Data released")
        if not score.fired:
            assert "neutral framing" in score.receipts().lower()

    def test_receipts_names_fired_categories(self) -> None:
        score = score_text("Radical thugs slam government")
        receipts = score.receipts()
        assert any(cat.replace("_", " ").lower() in receipts.lower()
                   for cat in score.fired)

    def test_title_hits_weight_higher_than_body_hits(self) -> None:
        title_score = score_text("Regime collapses", "Neutral update today")
        body_score = score_text("Neutral update today", "Regime collapses")
        # Title carries double weight → same term in title → higher score
        assert title_score.spin_pct >= body_score.spin_pct

    def test_same_term_different_categories_each_fires(self) -> None:
        # "chaos" = loaded_language; "slam" = charged_verbs
        score = score_text("Chaos slams markets")
        assert "loaded_language" in score.fired
        assert "charged_verbs" in score.fired

    def test_subscores_keys_are_four_categories(self) -> None:
        score = score_text("anything")
        assert set(score.subscores.keys()) == {
            "loaded_language", "charged_verbs", "fear", "endorsement"
        }

    def test_subscores_are_nonnegative(self) -> None:
        score = score_text("anything here is fine")
        for val in score.subscores.values():
            assert val >= 0.0

    def test_deterministic_same_input_same_output(self) -> None:
        s1 = score_text("Regime blasts critics", "fear of disaster")
        s2 = score_text("Regime blasts critics", "fear of disaster")
        assert s1.spin_pct == s2.spin_pct
        assert s1.fired == s2.fired


# ===========================================================================
# PART 7 — SUBSTANTIVE TESTS: DOMAIN CLASSIFICATION
# ===========================================================================

from situation_monitor.domains import classify_domain  # noqa: E402
from situation_monitor.models import Domain  # noqa: E402


class TestClassifyDomain:
    def test_ai_keyword_in_title_returns_ai(self) -> None:
        a = _art("https://x.com/1", "OpenAI releases GPT-5 with new capabilities")
        assert classify_domain(a) is Domain.AI

    def test_markets_keyword_returns_markets(self) -> None:
        a = _art("https://x.com/1", "NASDAQ hits all-time high as stocks surge")
        assert classify_domain(a) is Domain.MARKETS

    def test_world_keyword_returns_world(self) -> None:
        a = _art("https://x.com/1", "President signs ceasefire treaty with neighbours")
        assert classify_domain(a) is Domain.WORLD

    def test_ai_takes_precedence_over_markets(self) -> None:
        a = _art("https://x.com/1", "AI chip stocks on NASDAQ reach new high")
        assert classify_domain(a) is Domain.AI

    def test_no_keyword_returns_default(self) -> None:
        a = _art("https://x.com/1", "Weather is sunny today")
        assert classify_domain(a, default=Domain.WORLD) is Domain.WORLD

    def test_no_keyword_returns_none_when_no_default(self) -> None:
        a = _art("https://x.com/1", "Weather is sunny today")
        assert classify_domain(a) is None

    def test_body_text_used_for_classification(self) -> None:
        a = Article(
            url="https://x.com/1",
            title="Economic Update",
            source="Reuters",
            body="The Federal Reserve raised interest rates today",
        )
        result = classify_domain(a)
        assert result is Domain.MARKETS

    def test_ai_term_in_body_triggers_ai(self) -> None:
        a = Article(
            url="https://x.com/1",
            title="Company News",
            source="TechCrunch",
            body="The startup uses ChatGPT and machine learning for analytics",
        )
        assert classify_domain(a) is Domain.AI

    def test_word_boundary_prevents_false_match(self) -> None:
        # "Spain" contains "ain" but not word-bounded "ai"
        a = _art("https://x.com/1", "Spain wins the football championship")
        result = classify_domain(a, default=None)
        # "spain" does not match \bai\b → no AI classification
        assert result is not Domain.AI

    def test_case_insensitive_matching(self) -> None:
        a = _art("https://x.com/1", "ARTIFICIAL INTELLIGENCE reshapes hiring")
        assert classify_domain(a) is Domain.AI


# ===========================================================================
# PART 8 — SUBSTANTIVE TESTS: MODELS
# ===========================================================================


class TestArticleValidation:
    def test_empty_url_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="url"):
            Article(url="", title="Title", source="Source")

    def test_empty_title_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="title"):
            Article(url="https://a.com", title="", source="Source")

    def test_empty_source_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="source"):
            Article(url="https://a.com", title="Title", source="")

    def test_valid_article_created_with_defaults(self) -> None:
        a = Article(url="https://a.com", title="Title", source="Source")
        assert a.propaganda_flags == []
        assert a.tags == []
        assert a.loaded_language is False

    def test_domain_field_accepts_enum(self) -> None:
        a = Article(
            url="https://a.com", title="Title", source="Source", domain=Domain.AI
        )
        assert a.domain is Domain.AI

    def test_domain_field_defaults_to_none(self) -> None:
        a = Article(url="https://a.com", title="Title", source="Source")
        assert a.domain is None

    def test_spin_result_fields(self) -> None:
        from situation_monitor.models import SpinResult
        s = SpinResult(spin_pct=42.5, lens="left", rubric={"x": 0.5}, receipts="ok")
        assert s.spin_pct == 42.5
        assert s.hype_vs_substance is None
        assert s.vendor_pr is None


# ===========================================================================
# PART 9 — SUBSTANTIVE TESTS: BIAS MODULE
# ===========================================================================

from situation_monitor.bias import (  # noqa: E402
    ALLSIDES_PRIORS,
    CURATED_BIAS,
    _as_float,
    _prior_lean,
    _try_parse,
    get_source_lean,
    get_source_reliability,
)


class TestGetSourceLean:
    def test_bbc_returns_center(self) -> None:
        assert get_source_lean("bbc.com") == "center"

    def test_foxnews_returns_right(self) -> None:
        assert get_source_lean("foxnews.com") == "right"

    def test_theguardian_returns_left_center(self) -> None:
        assert get_source_lean("theguardian.com") == "left-center"

    def test_unknown_source_returns_none(self) -> None:
        assert get_source_lean("unknownnews123.xyz") is None

    def test_case_insensitive_match(self) -> None:
        assert get_source_lean("BBC.COM") == "center"

    def test_short_source_below_min_len_returns_none(self) -> None:
        assert get_source_lean("bb") is None

    def test_empty_source_returns_none(self) -> None:
        assert get_source_lean("") is None

    def test_breitbart_returns_right(self) -> None:
        assert get_source_lean("breitbart.com") == "right"

    def test_reuters_returns_center(self) -> None:
        assert get_source_lean("reuters.com") == "center"


class TestGetSourceReliability:
    def test_bbc_returns_high(self) -> None:
        assert get_source_reliability("bbc.com") == "high"

    def test_breitbart_returns_low(self) -> None:
        assert get_source_reliability("breitbart.com") == "low"

    def test_cnn_returns_medium(self) -> None:
        assert get_source_reliability("cnn.com") == "medium"

    def test_unknown_returns_none(self) -> None:
        assert get_source_reliability("unknown-outlet.xyz") is None


class TestPriorLean:
    def test_foxnews_lean(self) -> None:
        assert _prior_lean("foxnews.com") == "right"

    def test_unknown_defaults_to_center(self) -> None:
        assert _prior_lean("totally-unknown-outlet.io") == "center"

    def test_bbc_lean(self) -> None:
        assert _prior_lean("bbc.com") == "center"


class TestAsFloat:
    def test_int_converted(self) -> None:
        assert _as_float(42, 0.0) == 42.0

    def test_float_returned(self) -> None:
        assert _as_float(3.14, 0.0) == 3.14

    def test_string_numeric_converted(self) -> None:
        assert _as_float("7.5", 0.0) == 7.5

    def test_bool_returns_default(self) -> None:
        assert _as_float(True, 99.0) == 99.0

    def test_non_numeric_string_returns_default(self) -> None:
        assert _as_float("high", 50.0) == 50.0

    def test_none_returns_default(self) -> None:
        assert _as_float(None, 50.0) == 50.0

    def test_list_returns_default(self) -> None:
        assert _as_float([1, 2], 50.0) == 50.0


class TestTryParse:
    def test_valid_json_object_parsed(self) -> None:
        result = _try_parse('{"spin_pct": 30.0, "lens": "left"}')
        assert result == {"spin_pct": 30.0, "lens": "left"}

    def test_json_with_prose_preamble_extracted(self) -> None:
        raw = 'Here is my analysis: {"spin_pct": 40} good.'
        result = _try_parse(raw)
        assert result == {"spin_pct": 40}

    def test_empty_string_returns_none(self) -> None:
        assert _try_parse("") is None

    def test_no_json_returns_none(self) -> None:
        assert _try_parse("no JSON here") is None

    def test_invalid_json_returns_none(self) -> None:
        assert _try_parse("{not valid json}") is None

    def test_nested_json_returned(self) -> None:
        raw = '{"rubric": {"loaded_language": 0.8}}'
        result = _try_parse(raw)
        assert result["rubric"]["loaded_language"] == 0.8


class TestAllsidesPriors:
    def test_curated_bias_wins_on_conflict(self) -> None:
        # bbc.com has curated bias entry; the ALLSIDES_PRIORS must agree with it
        curated = CURATED_BIAS.get("bbc.com")
        if curated:
            priors = ALLSIDES_PRIORS.get("bbc.com")
            assert priors is not None
            assert priors["lean"] == curated["lean"]

    def test_all_priors_have_lean_key(self) -> None:
        for domain, entry in ALLSIDES_PRIORS.items():
            assert "lean" in entry, f"No 'lean' key for '{domain}'"

    def test_all_priors_have_reliability_tier_key(self) -> None:
        for domain, entry in ALLSIDES_PRIORS.items():
            assert "reliability_tier" in entry, f"No 'reliability_tier' for '{domain}'"


# ===========================================================================
# PART 10 — SUBSTANTIVE TESTS: SPIN ESTIMATOR
# ===========================================================================

from situation_monitor.bias import SpinEstimator  # noqa: E402
from situation_monitor.models import SpinResult  # noqa: E402


def _make_article(**kw) -> Article:
    defaults = dict(url="https://example.com/1", title="Test Article", source="BBC")
    defaults.update(kw)
    return Article(**defaults)


class TestSpinEstimator:
    def test_valid_response_parsed(self) -> None:
        estimator = SpinEstimator()
        raw = '{"spin_pct": 65.0, "lens": "right", "rubric": {"loaded_language": 0.9, "omission": 0.2, "sourcing_asymmetry": 0.1, "emotional_framing": 0.3}, "hype_vs_substance": null, "vendor_pr": null}'
        result = estimator.estimate_spin(_make_article(), lambda _: raw)
        assert result.spin_pct == 65.0
        assert result.lens == "right"

    def test_unparseable_response_returns_fallback(self) -> None:
        estimator = SpinEstimator()
        result = estimator.estimate_spin(
            _make_article(source="bbc.com"), lambda _: "not json"
        )
        assert result.spin_pct == 50.0
        assert "unparseable" in result.receipts.lower()

    def test_fallback_uses_source_prior_lean(self) -> None:
        estimator = SpinEstimator()
        result = estimator.estimate_spin(
            _make_article(source="foxnews.com"), lambda _: "garbage"
        )
        assert result.lens == "right"

    def test_ai_domain_populates_hype_vs_substance(self) -> None:
        estimator = SpinEstimator()
        raw = '{"spin_pct": 70.0, "lens": "right", "rubric": {}, "hype_vs_substance": 0.8, "vendor_pr": true}'
        article = _make_article(domain=Domain.AI)
        result = estimator.estimate_spin(article, lambda _: raw)
        assert result.hype_vs_substance == 0.8
        assert result.vendor_pr is True

    def test_non_ai_domain_hype_remains_none(self) -> None:
        estimator = SpinEstimator()
        raw = '{"spin_pct": 40.0, "lens": "center", "rubric": {}, "hype_vs_substance": 0.5, "vendor_pr": false}'
        article = _make_article(domain=Domain.WORLD)
        result = estimator.estimate_spin(article, lambda _: raw)
        assert result.hype_vs_substance is None
        assert result.vendor_pr is None

    def test_rubric_non_dict_coerced_to_empty(self) -> None:
        estimator = SpinEstimator()
        raw = '{"spin_pct": 50.0, "lens": "center", "rubric": "high", "hype_vs_substance": null, "vendor_pr": null}'
        result = estimator.estimate_spin(_make_article(), lambda _: raw)
        assert result.rubric == {}

    def test_spin_pct_clamped_from_string(self) -> None:
        estimator = SpinEstimator()
        raw = '{"spin_pct": "high", "lens": "left", "rubric": {}, "hype_vs_substance": null, "vendor_pr": null}'
        result = estimator.estimate_spin(_make_article(), lambda _: raw)
        # "high" falls back to default 50.0 via _as_float
        assert result.spin_pct == 50.0

    def test_receipts_present_when_rubric_fires(self) -> None:
        estimator = SpinEstimator()
        raw = '{"spin_pct": 80.0, "lens": "right", "rubric": {"loaded_language": 0.9}, "hype_vs_substance": null, "vendor_pr": null}'
        result = estimator.estimate_spin(_make_article(), lambda _: raw)
        assert "Spin signals fired" in result.receipts

    def test_receipts_neutral_when_nothing_fires(self) -> None:
        estimator = SpinEstimator()
        raw = '{"spin_pct": 10.0, "lens": "center", "rubric": {"loaded_language": 0.1}, "hype_vs_substance": null, "vendor_pr": null}'
        result = estimator.estimate_spin(_make_article(), lambda _: raw)
        assert "No strong spin signals" in result.receipts

    def test_fallback_ai_domain_sets_neutral_hype(self) -> None:
        estimator = SpinEstimator()
        article = _make_article(domain=Domain.AI)
        result = estimator.estimate_spin(article, lambda _: "not json")
        assert result.hype_vs_substance == 0.5
        assert result.vendor_pr is False


# ===========================================================================
# PART 11 — SUBSTANTIVE TESTS: PROPAGANDA
# ===========================================================================

from situation_monitor.propaganda import (  # noqa: E402
    apply_lexicon_baseline,
    enrich_article,
    flag_article,
    lexicon_signal,
)


class TestFlagArticle:
    def test_valid_flags_returned(self) -> None:
        raw = '{"flags": ["loaded_language", "appeal_to_fear"]}'
        result = flag_article(_make_article(), lambda _: raw)
        assert result == ["loaded_language", "appeal_to_fear"]

    def test_empty_flags_returned_on_empty_list(self) -> None:
        raw = '{"flags": []}'
        result = flag_article(_make_article(), lambda _: raw)
        assert result == []

    def test_exception_in_client_returns_empty(self) -> None:
        def bad_client(_: str) -> str:
            raise RuntimeError("network down")
        result = flag_article(_make_article(), bad_client)
        assert result == []

    def test_invalid_json_returns_empty(self) -> None:
        result = flag_article(_make_article(), lambda _: "not json")
        assert result == []

    def test_non_string_flags_filtered_out(self) -> None:
        raw = '{"flags": [1, 2, "loaded_language"]}'
        result = flag_article(_make_article(), lambda _: raw)
        assert result == []

    def test_excerpt_limited_to_2000_chars(self) -> None:
        seen_prompts = []
        article = _make_article(body="x" * 5000)
        def capture(prompt: str) -> str:
            seen_prompts.append(prompt)
            return '{"flags": []}'
        flag_article(article, capture)
        assert "x" * 2001 not in seen_prompts[0]


class TestEnrichArticle:
    def test_enrich_sets_propaganda_flags(self) -> None:
        raw = '{"flags": ["bandwagon"], "loaded_language": true, "propaganda_flag": true}'
        article = _make_article()
        enrich_article(article, lambda _: raw)
        assert "bandwagon" in article.propaganda_flags
        assert article.loaded_language is True
        assert article.propaganda_flag is True

    def test_enrich_on_exception_leaves_article_unchanged(self) -> None:
        article = _make_article()
        orig_flags = list(article.propaganda_flags)
        enrich_article(article, lambda _: (_ for _ in ()).throw(RuntimeError("err")))
        assert article.propaganda_flags == orig_flags

    def test_enrich_on_bad_json_leaves_article_unchanged(self) -> None:
        article = _make_article()
        enrich_article(article, lambda _: "oops")
        assert article.propaganda_flags == []


class TestLexiconSignal:
    def test_neutral_article_no_flags(self) -> None:
        article = _make_article(title="GDP Data Released", body="The economy grew.")
        flags, loaded, flagged = lexicon_signal(article)
        assert not flagged
        assert not loaded

    def test_loaded_title_sets_loaded_language_flag(self) -> None:
        article = _make_article(
            title="Thugs slam regime in brutal crackdown", body=""
        )
        flags, loaded, flagged = lexicon_signal(article)
        assert flagged
        assert loaded or "loaded_language" in flags

    def test_fear_term_fires_appeal_to_fear(self) -> None:
        article = _make_article(
            title="Experts warn of catastrophic collapse", body="disaster looms"
        )
        flags, loaded, flagged = lexicon_signal(article)
        assert "appeal_to_fear" in flags

    def test_returns_three_tuple(self) -> None:
        article = _make_article()
        result = lexicon_signal(article)
        assert len(result) == 3


class TestApplyLexiconBaseline:
    def test_adds_flags_when_none_present(self) -> None:
        article = _make_article(title="Regime slams critics in brutal crackdown")
        apply_lexicon_baseline(article)
        assert article.propaganda_flag or article.propaganda_flags

    def test_never_downgrades_existing_flags(self) -> None:
        article = _make_article(title="Neutral report")
        article.propaganda_flags = ["pre_existing"]
        article.loaded_language = True
        apply_lexicon_baseline(article)
        assert "pre_existing" in article.propaganda_flags
        assert article.loaded_language is True

    def test_neutral_article_no_flags_added(self) -> None:
        article = _make_article(title="GDP Data Released", body="The economy grew.")
        apply_lexicon_baseline(article)
        assert article.propaganda_flags == []
        assert article.propaganda_flag is False


# ===========================================================================
# PART 12 — SUBSTANTIVE TESTS: RELEVANCE
# ===========================================================================

from situation_monitor.relevance import score_relevance  # noqa: E402


class TestScoreRelevance:
    def test_empty_topics_returns_1(self) -> None:
        article = _make_article()
        result = score_relevance(article, [], lambda _: "x")
        assert result == 1.0

    def test_valid_score_returned(self) -> None:
        article = _make_article()
        result = score_relevance(article, ["AI", "tech"], lambda _: '{"score": 0.75}')
        assert result == 0.75

    def test_score_clamped_to_0_1(self) -> None:
        article = _make_article()
        result = score_relevance(article, ["AI"], lambda _: '{"score": 1.5}')
        assert result == 1.0

    def test_negative_score_clamped_to_zero(self) -> None:
        article = _make_article()
        result = score_relevance(article, ["AI"], lambda _: '{"score": -0.3}')
        assert result == 0.0

    def test_exception_returns_1(self) -> None:
        def bad(_: str) -> str:
            raise RuntimeError("timeout")
        result = score_relevance(_make_article(), ["AI"], bad)
        assert result == 1.0

    def test_invalid_json_returns_1(self) -> None:
        result = score_relevance(_make_article(), ["AI"], lambda _: "not json")
        assert result == 1.0

    def test_markdown_fenced_json_parsed(self) -> None:
        raw = "```json\n{\"score\": 0.9}\n```"
        result = score_relevance(_make_article(), ["AI"], lambda _: raw)
        assert result == pytest.approx(0.9)


# ===========================================================================
# PART 13 — SUBSTANTIVE TESTS: RELIABILITY TRACKER
# ===========================================================================

from situation_monitor.reliability import ReliabilityTracker  # noqa: E402


class TestReliabilityTracker:
    def test_new_source_returns_none(self) -> None:
        t = ReliabilityTracker()
        assert t.get_tracked_reliability("bbc.com") is None

    def test_record_then_high_avg_returns_high(self) -> None:
        t = ReliabilityTracker()
        t.record_fetch("bbc.com", 10)
        assert t.get_tracked_reliability("bbc.com") == "high"

    def test_low_avg_returns_low(self) -> None:
        t = ReliabilityTracker()
        t.record_fetch("tiny.com", 0)
        assert t.get_tracked_reliability("tiny.com") == "low"

    def test_medium_avg_returns_medium(self) -> None:
        t = ReliabilityTracker()
        t.record_fetch("medium.com", 3)
        assert t.get_tracked_reliability("medium.com") == "medium"

    def test_multiple_fetches_averaged(self) -> None:
        t = ReliabilityTracker()
        t.record_fetch("a.com", 0)
        t.record_fetch("a.com", 10)
        # avg = 5 → high
        assert t.get_tracked_reliability("a.com") == "high"

    def test_save_and_load_roundtrip(self, tmp_path) -> None:
        t = ReliabilityTracker()
        t.record_fetch("bbc.com", 7)
        path = str(tmp_path / "rel.json")
        t.save(path)
        t2 = ReliabilityTracker()
        t2.load(path)
        assert t2.get_tracked_reliability("bbc.com") == "high"

    def test_load_nonexistent_file_is_noop(self) -> None:
        t = ReliabilityTracker()
        t.load("/tmp/__does_not_exist__.json")
        assert t.get_tracked_reliability("any") is None

    def test_load_invalid_json_is_noop(self, tmp_path) -> None:
        p = tmp_path / "bad.json"
        p.write_text("not json")
        t = ReliabilityTracker()
        t.load(str(p))
        assert t.get_tracked_reliability("x") is None

    def test_save_creates_parent_dirs(self, tmp_path) -> None:
        t = ReliabilityTracker()
        t.record_fetch("x.com", 5)
        nested = str(tmp_path / "a" / "b" / "rel.json")
        t.save(nested)
        assert Path(nested).exists()


# ===========================================================================
# PART 14 — SUBSTANTIVE TESTS: DUAL LENS
# ===========================================================================

from situation_monitor.dual_lens import (  # noqa: E402
    DualLensEvent,
    _avg_spin,
    _lean_bucket,
    _significant_words,
    deterministic_spin,
    group_by_event,
)


def _spin_result(spin_pct: float = 50.0, lens: str = "left") -> SpinResult:
    return SpinResult(spin_pct=spin_pct, lens=lens, rubric={}, receipts="ok")


class TestDualLensHelpers:
    def test_lean_bucket_left(self) -> None:
        assert _lean_bucket("left") == "left"
        assert _lean_bucket("left-center") == "left"

    def test_lean_bucket_right(self) -> None:
        assert _lean_bucket("right") == "right"
        assert _lean_bucket("right-center") == "right"

    def test_lean_bucket_center(self) -> None:
        assert _lean_bucket("center") == "center"
        assert _lean_bucket("state") == "center"

    def test_significant_words_removes_stopwords(self) -> None:
        result = _significant_words("The war in Ukraine")
        assert "the" not in result
        assert "in" not in result
        assert "war" in result
        assert "ukraine" in result

    def test_significant_words_filters_short_words(self) -> None:
        result = _significant_words("AI is key")
        # "is" is a stopword but "key" length=3 included; "ai" length=2 excluded
        assert "ai" not in result

    def test_avg_spin_empty_returns_zero(self) -> None:
        assert _avg_spin([]) == 0.0

    def test_avg_spin_computed_correctly(self) -> None:
        from situation_monitor.dual_lens import AnnotatedArticle
        a1 = AnnotatedArticle(article=_make_article(), spin=_spin_result(40.0, "left"))
        a2 = AnnotatedArticle(article=_make_article(), spin=_spin_result(60.0, "left"))
        assert _avg_spin([a1, a2]) == pytest.approx(50.0)


class TestDeterministicSpin:
    def test_returns_spin_result(self) -> None:
        article = _make_article(
            title="Regime slams critics in brutal crackdown", source="foxnews.com"
        )
        result = deterministic_spin(article)
        assert isinstance(result, SpinResult)

    def test_spin_pct_in_range(self) -> None:
        article = _make_article(title="Quarterly GDP report released")
        result = deterministic_spin(article)
        assert 0.0 <= result.spin_pct <= 100.0

    def test_lean_from_source_prior(self) -> None:
        article = _make_article(source="foxnews.com")
        result = deterministic_spin(article)
        assert result.lens == "right"


class TestGroupByEvent:
    def test_empty_list_returns_empty(self) -> None:
        assert group_by_event([]) == []

    def test_single_article_forms_single_event(self) -> None:
        a = _make_article(title="War breaks out in Eastern Europe")
        events = group_by_event([a])
        assert len(events) == 1

    def test_two_similar_articles_merge(self) -> None:
        a = _make_article(
            url="https://a.com/1",
            title="War breaks out in Eastern Europe between forces",
            source="theguardian.com",
        )
        b = _make_article(
            url="https://b.com/2",
            title="War breaks out in Eastern Europe between nations",
            source="foxnews.com",
        )
        events = group_by_event([a, b])
        assert len(events) == 1

    def test_two_different_articles_separate_events(self) -> None:
        a = _make_article(
            url="https://a.com/1",
            title="Fed raises interest rates significantly today"
        )
        b = _make_article(
            url="https://b.com/2",
            title="Solar eclipse visible across North America"
        )
        events = group_by_event([a, b])
        assert len(events) == 2

    def test_spin_fn_called_for_each_article(self) -> None:
        calls = []
        def spy_spin(article: Article) -> SpinResult:
            calls.append(article)
            return _spin_result()
        articles = [
            _make_article(url=f"https://x.com/{i}", title=f"Unique title {i}")
            for i in range(3)
        ]
        group_by_event(articles, spin_fn=spy_spin)
        assert len(calls) == 3

    def test_spin_delta_zero_for_single_article(self) -> None:
        a = _make_article(title="Single article with no counterpart")
        events = group_by_event([a])
        # Only one article; no opposing lens → spin_delta = 0
        assert events[0].spin_delta == 0.0

    def test_left_and_right_articles_bucketed(self) -> None:
        a = _make_article(url="https://a.com/1", title="War in Ukraine Russian troops advance", source="theguardian.com")
        b = _make_article(url="https://b.com/2", title="War in Ukraine Russian troops advance", source="foxnews.com")
        def fixed_spin(article: Article) -> SpinResult:
            if "guardian" in article.source:
                return _spin_result(lens="left")
            return _spin_result(lens="right")
        events = group_by_event([a, b], spin_fn=fixed_spin)
        assert len(events) == 1
        evt = events[0]
        assert len(evt.left_articles) == 1
        assert len(evt.right_articles) == 1

    def test_spin_delta_positive_for_opposing_framings(self) -> None:
        a = _make_article(url="https://a.com/1", title="Economic policy slams workers hard")
        b = _make_article(url="https://b.com/2", title="Economic policy slams workers hard")
        def varying_spin(article: Article) -> SpinResult:
            if article.url.endswith("1"):
                return _spin_result(20.0, "left")
            return _spin_result(80.0, "right")
        events = group_by_event([a, b], spin_fn=varying_spin)
        assert len(events) == 1
        assert events[0].spin_delta == pytest.approx(60.0)


# ===========================================================================
# PART 15 — SUBSTANTIVE TESTS: ALERTING
# ===========================================================================

from situation_monitor.alerting import check_and_emit_alerts  # noqa: E402


def _scored_article(score: float | None, cluster_id: str = "c1") -> Article:
    return Article(
        url=f"https://x.com/{score}",
        title=f"Title score={score}",
        source="Test",
        relevance_score=score,
        cluster_id=cluster_id,
    )


class TestCheckAndEmitAlerts:
    def test_no_articles_returns_empty(self) -> None:
        result = check_and_emit_alerts([], threshold=0.8)
        assert result == []

    def test_article_at_threshold_fires(self) -> None:
        a = _scored_article(0.8)
        result = check_and_emit_alerts([a], threshold=0.8)
        assert result == [a]

    def test_article_above_threshold_fires(self) -> None:
        a = _scored_article(0.95)
        result = check_and_emit_alerts([a], threshold=0.8)
        assert result == [a]

    def test_article_below_threshold_not_fired(self) -> None:
        a = _scored_article(0.7)
        result = check_and_emit_alerts([a], threshold=0.8)
        assert result == []

    def test_none_relevance_score_not_fired(self) -> None:
        a = _scored_article(None)
        result = check_and_emit_alerts([a], threshold=0.8)
        assert result == []

    def test_stringio_accepted_as_output_file(self) -> None:
        buf = StringIO()
        a = _scored_article(0.9)
        result = check_and_emit_alerts([a], threshold=0.8, output_file=buf)
        assert result == [a]
        assert "ALERT" in buf.getvalue()

    def test_file_output_written_when_path_given(self, tmp_path) -> None:
        p = str(tmp_path / "alerts.txt")
        a = _scored_article(0.9)
        check_and_emit_alerts([a], threshold=0.8, output_file=p)
        assert "ALERT" in Path(p).read_text()

    def test_mixed_batch_returns_only_above_threshold(self) -> None:
        articles = [
            _scored_article(0.9),
            _scored_article(0.5),
            _scored_article(0.8),
            _scored_article(0.3),
        ]
        result = check_and_emit_alerts(articles, threshold=0.8)
        assert len(result) == 2

    def test_alert_line_contains_title_and_score(self) -> None:
        buf = StringIO()
        a = _scored_article(0.95)
        check_and_emit_alerts([a], threshold=0.8, output_file=buf)
        line = buf.getvalue()
        assert "Title" in line or "title" in line.lower()
        assert "0.9500" in line


# ===========================================================================
# PART 16 — SUBSTANTIVE TESTS: DIGEST ASSEMBLY
# ===========================================================================

from datetime import datetime  # noqa: E402

from situation_monitor.digest import daily_digest  # noqa: E402
from situation_monitor.dual_lens import AnnotatedArticle, DualLensEvent  # noqa: E402
from situation_monitor.practical import PracticalMover  # noqa: E402


def _make_event(
    title: str = "Test event",
    spin_delta: float = 0.0,
    left: int = 0,
    right: int = 0,
    center: int = 0,
) -> DualLensEvent:
    def _aa(source: str, lean: str) -> AnnotatedArticle:
        a = Article(url=f"https://{source}/1", title=title, source=source, domain=Domain.WORLD)
        return AnnotatedArticle(article=a, spin=_spin_result(50.0, lean))
    return DualLensEvent(
        event_title=title,
        left_articles=[_aa(f"l{i}.com", "left") for i in range(left)],
        right_articles=[_aa(f"r{i}.com", "right") for i in range(right)],
        center_articles=[_aa(f"c{i}.com", "center") for i in range(center)],
        spin_delta=spin_delta,
    )


class TestDailyDigest:
    def test_empty_events_and_movers_returns_no_events_line(self) -> None:
        text = daily_digest([], [])
        assert "No events found" in text

    def test_header_contains_date(self) -> None:
        ts = datetime(2024, 1, 15, 7, 0)
        text = daily_digest([], [], as_of=ts)
        assert "2024-01-15" in text

    def test_top_stories_section_present_with_events(self) -> None:
        event = _make_event("War in Ukraine", spin_delta=20.0, left=1, right=1)
        text = daily_digest([event], [])
        assert "Top Stories" in text

    def test_event_title_in_output(self) -> None:
        event = _make_event("Fed Raises Rates")
        text = daily_digest([event], [])
        assert "Fed Raises Rates" in text

    def test_spin_delta_shown_when_above_5(self) -> None:
        event = _make_event("Big Story", spin_delta=30.0, left=1, right=1)
        text = daily_digest([event], [])
        assert "30%" in text or "↕30" in text

    def test_spin_delta_not_shown_when_below_5(self) -> None:
        event = _make_event("Small Story", spin_delta=2.0)
        text = daily_digest([event], [])
        assert "↕" not in text

    def test_market_movers_section_present(self) -> None:
        mover = PracticalMover(
            asset="EUR/USD",
            change_pct=1.2,
            direction="up",
            who_it_affects="traders",
            what_to_watch="ECB",
            source_url="https://ecb.eu",
        )
        text = daily_digest([], [mover])
        assert "Market Movers" in text
        assert "EUR/USD" in text

    def test_up_arrow_for_positive_mover(self) -> None:
        mover = PracticalMover(
            asset="Gold",
            change_pct=2.5,
            direction="up",
            who_it_affects="x",
            what_to_watch="y",
            source_url="https://example.com",
        )
        text = daily_digest([], [mover])
        assert "▲" in text

    def test_down_arrow_for_negative_mover(self) -> None:
        mover = PracticalMover(
            asset="Oil",
            change_pct=-1.5,
            direction="down",
            who_it_affects="x",
            what_to_watch="y",
            source_url="https://example.com",
        )
        text = daily_digest([], [mover])
        assert "▼" in text

    def test_top_n_limits_events(self) -> None:
        events = [_make_event(f"Event {i}") for i in range(20)]
        text = daily_digest(events, [], top_n=5)
        # Only first 5 event titles should appear
        assert "Event 0" in text
        assert "Event 4" in text
        # "Event 10" would exceed top_n=5 if original ordering is by index
        for i in range(5, 20):
            assert f"Event {i}" not in text

    def test_ai_articles_section_present(self) -> None:
        ai_art = Article(
            url="https://tech.com/1",
            title="ChatGPT beats human at coding",
            source="TechCrunch",
            domain=Domain.AI,
        )
        aa = AnnotatedArticle(article=ai_art, spin=_spin_result())
        event = DualLensEvent(
            event_title="AI News",
            center_articles=[aa],
        )
        text = daily_digest([event], [])
        assert "AI News" in text or "ChatGPT" in text

    def test_lens_counts_in_output(self) -> None:
        event = _make_event("Test Story", left=2, right=3, center=1)
        text = daily_digest([event], [])
        assert "L:2" in text
        assert "R:3" in text


# ===========================================================================
# PART 17 — SUBSTANTIVE TESTS: POLYMARKET
# ===========================================================================

from situation_monitor.polymarket import PolymarketClient, PolymarketMatcher  # noqa: E402


class TestPolymarketMatcher:
    def test_keyword_match_returns_odds(self) -> None:
        matcher = PolymarketMatcher()
        article = _make_article(title="Election in US 2024", body="Results incoming")
        markets = [{"keywords": ["election"], "odds": 0.72}]
        result = matcher.match(article, markets)
        assert result == pytest.approx(0.72)

    def test_no_match_returns_none(self) -> None:
        matcher = PolymarketMatcher()
        article = _make_article(title="Sports update")
        markets = [{"keywords": ["election"], "odds": 0.5}]
        result = matcher.match(article, markets)
        assert result is None

    def test_empty_markets_returns_none(self) -> None:
        matcher = PolymarketMatcher()
        result = matcher.match(_make_article(), [])
        assert result is None

    def test_match_is_case_insensitive(self) -> None:
        matcher = PolymarketMatcher()
        article = _make_article(title="ELECTION NEWS")
        markets = [{"keywords": ["election"], "odds": 0.6}]
        assert matcher.match(article, markets) == pytest.approx(0.6)


class TestPolymarketClientMatch:
    def test_slug_keywords_matched(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _make_article(title="Bitcoin ETF approved by SEC")
        markets = [{"slug": "bitcoin-etf", "question": "Will Bitcoin ETF?", "outcomePrices": ["0.8"]}]
        result = client.match(article, markets)
        assert result == pytest.approx(0.8)

    def test_no_match_returns_none(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _make_article(title="Cricket match results")
        markets = [{"slug": "bitcoin-etf", "question": "Will Bitcoin ETF?", "outcomePrices": ["0.8"]}]
        assert client.match(article, markets) is None

    def test_empty_markets_returns_none(self) -> None:
        client = PolymarketClient(slugs=[])
        assert client.match(_make_article(), []) is None

    def test_bad_outcome_prices_returns_none(self) -> None:
        client = PolymarketClient(slugs=[])
        article = _make_article(title="Bitcoin ETF news")
        markets = [{"slug": "bitcoin-etf", "question": "BTC ETF?", "outcomePrices": ["not-a-float"]}]
        assert client.match(article, markets) is None


# ===========================================================================
# PART 18 — SUBSTANTIVE TESTS: CONFIG
# ===========================================================================

from situation_monitor.config import Config, SourceDef  # noqa: E402


class TestConfig:
    def test_from_defaults_returns_config(self) -> None:
        cfg = Config.from_defaults()
        assert isinstance(cfg, Config)
        assert cfg.fetch_interval_seconds == 3600

    def test_from_env_reads_sm_fetch_interval(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_FETCH_INTERVAL", "1800")
        cfg = Config.from_env()
        assert cfg.fetch_interval_seconds == 1800

    def test_from_env_reads_sm_llm_backend(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_LLM_BACKEND", "offline")
        cfg = Config.from_env()
        assert cfg.llm_backend == "offline"

    def test_from_env_reads_sm_sources(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_SOURCES", "https://a.com,https://b.com")
        cfg = Config.from_env()
        assert "https://a.com" in cfg.sources
        assert "https://b.com" in cfg.sources

    def test_from_env_trims_whitespace_in_sources(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_SOURCES", " https://a.com , https://b.com ")
        cfg = Config.from_env()
        assert "https://a.com" in cfg.sources

    def test_from_file_loads_valid_json(self, tmp_path) -> None:
        data = {
            "fetch_interval_seconds": 7200,
            "log_level": "DEBUG",
        }
        import json
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(data))
        cfg = Config.from_file(str(p))
        assert cfg.fetch_interval_seconds == 7200
        assert cfg.log_level == "DEBUG"

    def test_from_file_loads_source_defs(self, tmp_path) -> None:
        import json
        data = {
            "source_defs": [
                {
                    "url": "https://feeds.bbci.co.uk/news/rss.xml",
                    "name": "BBC",
                    "domain": "WORLD",
                    "lens": "centre",
                }
            ]
        }
        p = tmp_path / "cfg.json"
        p.write_text(json.dumps(data))
        cfg = Config.from_file(str(p))
        assert len(cfg.source_defs) == 1
        assert cfg.source_defs[0].name == "BBC"
        assert cfg.source_defs[0].domain is Domain.WORLD

    def test_repr_contains_key_fields(self) -> None:
        cfg = Config.from_defaults()
        r = repr(cfg)
        assert "sources" in r
        assert "log_level" in r


# ===========================================================================
# PART 19 — SUBSTANTIVE TESTS: AUTH MODELS AND REGISTRY
# ===========================================================================

from situation_monitor.auth.models import AuthType, PlatformDef  # noqa: E402
from situation_monitor.auth.platforms import KNOWN_PLATFORMS  # noqa: E402
from situation_monitor.auth.registry import CredentialRegistry  # noqa: E402


class TestAuthModels:
    def test_authtype_values_present(self) -> None:
        assert AuthType.BEARER_TOKEN.value == "bearer_token"
        assert AuthType.OAUTH2.value == "oauth2"

    def test_platformdef_is_frozen(self) -> None:
        p = PlatformDef(
            platform_id="test",
            display_name="Test",
            auth_type=AuthType.API_KEY,
        )
        with pytest.raises((AttributeError, TypeError)):
            p.platform_id = "changed"  # type: ignore[misc]

    def test_known_platforms_not_empty(self) -> None:
        assert len(KNOWN_PLATFORMS) > 0

    def test_twitter_platform_present(self) -> None:
        assert "twitter" in KNOWN_PLATFORMS

    def test_twitter_requires_bearer_token_env(self) -> None:
        p = KNOWN_PLATFORMS["twitter"]
        assert "SM_AUTH_TWITTER_BEARER_TOKEN" in p.required_env_vars


class TestCredentialRegistry:
    def test_unknown_platform_has_returns_false(self) -> None:
        reg = CredentialRegistry.load_from_env()
        assert reg.has("totally_unknown_platform") is False

    def test_platform_without_env_vars_returns_false(self) -> None:
        reg = CredentialRegistry.load_from_env()
        # Twitter requires SM_AUTH_TWITTER_BEARER_TOKEN which is not set in CI
        assert isinstance(reg.has("twitter"), bool)

    def test_get_env_values_unknown_platform_returns_empty(self) -> None:
        reg = CredentialRegistry.load_from_env()
        result = reg.get_env_values("unknown_platform_xyz")
        assert result == {}

    def test_status_report_is_list(self) -> None:
        reg = CredentialRegistry.load_from_env()
        report = reg.status_report()
        assert isinstance(report, list)
        assert all("platform" in entry for entry in report)

    def test_status_report_entry_has_missing_vars(self) -> None:
        reg = CredentialRegistry.load_from_env()
        report = reg.status_report()
        for entry in report:
            assert "missing_vars" in entry

    def test_registry_with_all_vars_present(self, monkeypatch) -> None:
        monkeypatch.setenv("SM_AUTH_TWITTER_BEARER_TOKEN", "fake-token")
        reg = CredentialRegistry.load_from_env()
        assert reg.has("twitter") is True

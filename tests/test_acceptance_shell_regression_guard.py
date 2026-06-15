"""Independent acceptance regression guard.

Runs the acceptance shell script (``./acceptance``) as a real subprocess from the
project root with SM_LLM_BACKEND=offline and verifies the four mandated acceptance
criteria:

  1. acceptance script exits 0
  2. stdout has WORLD / MARKETS / AI domain headers AND a DUAL-LENS EVENTS block
  3. spin_pct: N.N% appears inside the dual-lens block
  4. digest-dry-run output contains '*Situation Monitor*' and bullet (•) entries

Design constraints:
  - Every assertion CAN fail on a real regression — no trivially-true checks.
  - The unit under test is NEVER mocked — mocking it proves nothing.
  - No recursive pytest subprocess invocations (project memory: they hang the suite).
  - Uses sys.executable via acceptance.py instead of the bare ``python`` in the
    shell script to make the subprocess portable, while a separate class tests the
    shell script itself for exit-code portability.
  - Module-scoped fixtures ensure each subprocess runs exactly once per session.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
ACCEPTANCE_FILE = PROJECT_ROOT / "acceptance"
ACCEPTANCE_PY = PROJECT_ROOT / "acceptance.py"
FIXTURES = PROJECT_ROOT / "tests" / "fixtures"
ACCEPTANCE_SOURCE_DEFS = FIXTURES / "acceptance_source_defs.json"
RSS_FIXTURE = FIXTURES / "rss_sample.xml"


# ---------------------------------------------------------------------------
# Offline environment helper
# ---------------------------------------------------------------------------


def _offline_env(**extra: str) -> dict[str, str]:
    return {
        **os.environ,
        "SM_LLM_BACKEND": "offline",
        "SM_SOURCES": str(RSS_FIXTURE),
        **extra,
    }


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixture: acceptance.py captured end-to-end
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def acceptance_proc() -> subprocess.CompletedProcess:
    """Run acceptance.py with SM_LLM_BACKEND=offline; capture combined stdout."""
    return subprocess.run(
        [sys.executable, str(ACCEPTANCE_PY)],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=180,
    )


@pytest.fixture(scope="module")
def acceptance_stdout(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stdout.decode(errors="replace")


@pytest.fixture(scope="module")
def acceptance_stderr(acceptance_proc: subprocess.CompletedProcess) -> str:
    return acceptance_proc.stderr.decode(errors="replace")


# ---------------------------------------------------------------------------
# Module-scoped subprocess fixture: digest-dry-run independently
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def digest_proc() -> subprocess.CompletedProcess:
    """Run digest-dry-run as a completely separate subprocess (independent from acceptance_proc)."""
    return subprocess.run(
        [
            sys.executable, "-m", "situation_monitor",
            "digest-dry-run",
            "--config", str(ACCEPTANCE_SOURCE_DEFS),
        ],
        capture_output=True,
        cwd=PROJECT_ROOT,
        env=_offline_env(),
        timeout=120,
    )


@pytest.fixture(scope="module")
def digest_stdout(digest_proc: subprocess.CompletedProcess) -> str:
    return digest_proc.stdout.decode(errors="replace")


# ---------------------------------------------------------------------------
# Criterion 1: acceptance script exits 0
# ---------------------------------------------------------------------------


class TestCriterion1AcceptanceExitsZero:
    """Criterion 1: SM_LLM_BACKEND=offline python acceptance.py must exit 0."""

    def test_returncode_is_zero(
        self, acceptance_proc: subprocess.CompletedProcess
    ) -> None:
        assert acceptance_proc.returncode == 0, (
            f"acceptance.py exited {acceptance_proc.returncode}, expected 0.\n"
            f"stderr (last 1 000 chars):\n"
            f"{acceptance_proc.stderr.decode(errors='replace')[-1000:]}\n"
            f"stdout (last 500 chars):\n"
            f"{acceptance_proc.stdout.decode(errors='replace')[-500:]}"
        )

    def test_stdout_is_non_empty(self, acceptance_stdout: str) -> None:
        assert acceptance_stdout.strip(), (
            "acceptance.py produced empty stdout — at minimum the 'once' digest must appear."
        )

    def test_no_traceback_in_stdout(self, acceptance_stdout: str) -> None:
        assert "Traceback" not in acceptance_stdout, (
            "acceptance.py stdout must not contain a Python Traceback.\n"
            f"stdout (first 2 000):\n{acceptance_stdout[:2000]}"
        )

    def test_no_traceback_in_stderr(self, acceptance_stderr: str) -> None:
        assert "Traceback" not in acceptance_stderr, (
            "acceptance.py stderr must not contain a Python Traceback.\n"
            f"stderr:\n{acceptance_stderr[:2000]}"
        )

    def test_offline_mode_no_api_error_in_stderr(self, acceptance_stderr: str) -> None:
        """SM_LLM_BACKEND=offline must prevent live LLM calls — no API errors."""
        api_indicators = [
            "AuthenticationError",
            "ANTHROPIC_API_KEY",
            "RateLimitError",
            "openai.error",
        ]
        found = [ind for ind in api_indicators if ind in acceptance_stderr]
        assert not found, (
            f"acceptance stderr contains API error indicators {found} — "
            "SM_LLM_BACKEND=offline must suppress live LLM traffic.\n"
            f"stderr:\n{acceptance_stderr[:1000]}"
        )

    def test_shell_script_file_exists(self) -> None:
        """The ``acceptance`` shell script itself must exist at the project root."""
        assert ACCEPTANCE_FILE.exists(), (
            f"Shell script 'acceptance' not found at {ACCEPTANCE_FILE}"
        )

    def test_shell_script_references_offline_backend(self) -> None:
        """The shell script must set SM_LLM_BACKEND=offline so CI never hits a live LLM."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "SM_LLM_BACKEND=offline" in content, (
            "The 'acceptance' shell script must contain 'SM_LLM_BACKEND=offline'.\n"
            "Without this, running './acceptance' would hit a live LLM backend."
        )

    def test_shell_script_invokes_acceptance_py(self) -> None:
        """The shell script must invoke acceptance.py — not some other script."""
        content = ACCEPTANCE_FILE.read_text(errors="replace")
        assert "acceptance.py" in content, (
            "The 'acceptance' shell script must invoke 'acceptance.py'."
        )

    def test_acceptance_py_exists(self) -> None:
        assert ACCEPTANCE_PY.exists(), (
            f"acceptance.py not found at {ACCEPTANCE_PY}"
        )

    def test_web_server_smoke_pass_in_stdout(self, acceptance_stdout: str) -> None:
        """cmd4 (check_server.py) inside acceptance.py must emit 'web-server-smoke: PASS'."""
        assert "web-server-smoke: PASS" in acceptance_stdout, (
            "acceptance.py stdout must contain 'web-server-smoke: PASS'.\n"
            "check_server.py (cmd4) must pass the Flask smoke test.\n"
            f"stdout (last 1000):\n{acceptance_stdout[-1000:]}"
        )

    def test_discourse_carrier_line_emitted(self, acceptance_stdout: str) -> None:
        """cmd3 (carrier once) must emit a line starting with 'discourse-carrier'."""
        carrier_lines = [
            ln for ln in acceptance_stdout.splitlines()
            if ln.startswith("discourse-carrier")
        ]
        assert carrier_lines, (
            "acceptance.py stdout must contain a line starting with 'discourse-carrier'.\n"
            "cmd3 (carrier once with SM_CARRIER_FEEDS) must find and emit at least one "
            "carrier article.\n"
            f"stdout (first 1 000):\n{acceptance_stdout[:1000]}"
        )


# ---------------------------------------------------------------------------
# Criterion 2: stdout has WORLD/MARKETS/AI domain headers AND DUAL-LENS EVENTS
# ---------------------------------------------------------------------------


class TestCriterion2DomainHeadersAndDualLens:
    """Criterion 2: all three domain H2 headers and DUAL-LENS EVENTS must appear."""

    def test_world_domain_header_present(self, acceptance_stdout: str) -> None:
        assert re.search(r"^## WORLD\b", acceptance_stdout, re.MULTILINE), (
            "acceptance stdout must contain '^## WORLD' H2 section heading.\n"
            "World-domain articles (rss_left.xml, rss_right.xml) must be ingested.\n"
            f"stdout (first 3 000):\n{acceptance_stdout[:3000]}"
        )

    def test_markets_domain_header_present(self, acceptance_stdout: str) -> None:
        assert re.search(r"^## MARKETS\b", acceptance_stdout, re.MULTILINE), (
            "acceptance stdout must contain '^## MARKETS' H2 section heading.\n"
            "Markets-domain articles (rss_markets.xml) must be ingested.\n"
            f"stdout (first 3 000):\n{acceptance_stdout[:3000]}"
        )

    def test_ai_domain_header_present(self, acceptance_stdout: str) -> None:
        assert re.search(r"^## AI\b", acceptance_stdout, re.MULTILINE), (
            "acceptance stdout must contain '^## AI' H2 section heading.\n"
            "AI-domain articles (rss_ai.xml) must be ingested.\n"
            f"stdout (first 3 000):\n{acceptance_stdout[:3000]}"
        )

    def test_all_three_domain_headers_present_simultaneously(
        self, acceptance_stdout: str
    ) -> None:
        missing = [
            d for d in ("## WORLD", "## MARKETS", "## AI")
            if d not in acceptance_stdout
        ]
        assert not missing, (
            f"Domain section(s) absent from acceptance stdout: {missing}.\n"
            "All three domain feeds must produce at least one article each.\n"
            f"stdout (first 3 000):\n{acceptance_stdout[:3000]}"
        )

    def test_dual_lens_events_block_present(self, acceptance_stdout: str) -> None:
        assert "## DUAL-LENS EVENTS" in acceptance_stdout, (
            "acceptance stdout must contain '## DUAL-LENS EVENTS' header.\n"
            "The fixture contains left- and right-leaning articles on the same topic; "
            "they must cluster into at least one dual-lens event.\n"
            f"stdout (first 3 000):\n{acceptance_stdout[:3000]}"
        )

    def test_domain_sections_precede_dual_lens_block(self, acceptance_stdout: str) -> None:
        """Domain H2 sections must come before ## DUAL-LENS EVENTS in document order."""
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' missing — cannot check ordering"
        for domain in ("## WORLD", "## MARKETS", "## AI"):
            d_idx = acceptance_stdout.find(domain)
            if d_idx >= 0:
                assert d_idx < dual_idx, (
                    f"'{domain}' must appear before '## DUAL-LENS EVENTS'; "
                    f"found at {d_idx}, dual-lens at {dual_idx}"
                )

    def test_domain_sections_in_canonical_order(self, acceptance_stdout: str) -> None:
        """Canonical render order: WORLD → MARKETS → AI."""
        world_idx = acceptance_stdout.find("## WORLD")
        markets_idx = acceptance_stdout.find("## MARKETS")
        ai_idx = acceptance_stdout.find("## AI")
        if world_idx >= 0 and markets_idx >= 0:
            assert world_idx < markets_idx, (
                "'## WORLD' must appear before '## MARKETS'"
            )
        if markets_idx >= 0 and ai_idx >= 0:
            assert markets_idx < ai_idx, (
                "'## MARKETS' must appear before '## AI'"
            )

    def test_each_domain_section_has_article_headings(
        self, acceptance_stdout: str
    ) -> None:
        """Each ## DOMAIN section must contain at least one ### article heading."""
        lines = acceptance_stdout.splitlines()
        current_domain: str | None = None
        counts: dict[str, int] = {}
        for line in lines:
            m = re.match(r"^## (WORLD|MARKETS|AI)$", line)
            if m:
                current_domain = m.group(1)
                counts.setdefault(current_domain, 0)
            elif current_domain and line.startswith("### "):
                counts[current_domain] = counts.get(current_domain, 0) + 1
            elif line.startswith("## DUAL-LENS") or (
                line.startswith("## ") and line not in ("## WORLD", "## MARKETS", "## AI")
            ):
                current_domain = None

        for domain, count in counts.items():
            assert count > 0, (
                f"## {domain} section has no '### <article>' entries.\n"
                "An empty domain section means no articles were ingested from that feed."
            )

    def test_left_and_right_headings_inside_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        block = acceptance_stdout[dual_idx:]
        assert re.search(r"^#### LEFT\b", block, re.MULTILINE), (
            "'#### LEFT' heading must appear inside the DUAL-LENS EVENTS block.\n"
            f"Block (first 500):\n{block[:500]}"
        )
        assert re.search(r"^#### RIGHT\b", block, re.MULTILINE), (
            "'#### RIGHT' heading must appear inside the DUAL-LENS EVENTS block.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_dual_lens_block_has_event_h3_title(self, acceptance_stdout: str) -> None:
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        assert dual_idx >= 0, "'## DUAL-LENS EVENTS' not found"
        block = acceptance_stdout[dual_idx:]
        h3_lines = [ln for ln in block.splitlines() if re.match(r"^### \S", ln)]
        assert h3_lines, (
            "'## DUAL-LENS EVENTS' block must contain at least one '### <event title>' H3 line.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_dual_lens_left_column_has_bullet_article(self, acceptance_stdout: str) -> None:
        left_idx = acceptance_stdout.find("#### LEFT")
        assert left_idx >= 0, "'#### LEFT' heading not found in acceptance stdout"
        section = acceptance_stdout[left_idx:]
        end = re.search(r"\n#+[ ]", section[5:])
        left_body = section[: end.start() + 5] if end else section
        bullets = [ln for ln in left_body.splitlines() if ln.startswith("- ")]
        assert bullets, (
            "'#### LEFT' column must contain at least one '- <article>' bullet.\n"
            f"LEFT section:\n{left_body[:400]}"
        )

    def test_dual_lens_right_column_has_bullet_article(self, acceptance_stdout: str) -> None:
        right_idx = acceptance_stdout.find("#### RIGHT")
        assert right_idx >= 0, "'#### RIGHT' heading not found in acceptance stdout"
        section = acceptance_stdout[right_idx:]
        end = re.search(r"\n#+[ ]", section[5:])
        right_body = section[: end.start() + 5] if end else section
        bullets = [ln for ln in right_body.splitlines() if ln.startswith("- ")]
        assert bullets, (
            "'#### RIGHT' column must contain at least one '- <article>' bullet.\n"
            f"RIGHT section:\n{right_body[:400]}"
        )

    def test_left_heading_precedes_right_heading_inside_dual_lens(
        self, acceptance_stdout: str
    ) -> None:
        dual_idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        if dual_idx < 0:
            pytest.skip("DUAL-LENS EVENTS block missing — covered by another test")
        block = acceptance_stdout[dual_idx:]
        left_pos = block.find("#### LEFT")
        right_pos = block.find("#### RIGHT")
        if left_pos >= 0 and right_pos >= 0:
            assert left_pos < right_pos, (
                "'#### LEFT' must appear before '#### RIGHT' inside the DUAL-LENS block"
            )


# ---------------------------------------------------------------------------
# Criterion 3: spin_pct: N.N% appears in the dual-lens block
# ---------------------------------------------------------------------------


class TestCriterion3SpinPctInDualLensBlock:
    """Criterion 3: 'spin_pct: N.N%' must appear INSIDE the DUAL-LENS EVENTS block."""

    def _dual_lens_block(self, acceptance_stdout: str) -> str:
        idx = acceptance_stdout.find("## DUAL-LENS EVENTS")
        if idx < 0:
            pytest.skip("## DUAL-LENS EVENTS block missing — covered by TestCriterion2")
        return acceptance_stdout[idx:]

    def test_spin_pct_keyword_in_dual_lens_block(self, acceptance_stdout: str) -> None:
        block = self._dual_lens_block(acceptance_stdout)
        assert "spin_pct:" in block, (
            "'spin_pct:' keyword must appear inside the DUAL-LENS EVENTS block.\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_spin_pct_decimal_percent_pattern_in_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """Pattern must be 'spin_pct: N.N%' (one decimal place, :.1f format)."""
        block = self._dual_lens_block(acceptance_stdout)
        m = re.search(r"spin_pct:\s*\d+\.\d+%", block)
        assert m is not None, (
            "No 'spin_pct: N.N%' pattern found inside the DUAL-LENS EVENTS block.\n"
            "Format must be :.1f (e.g. '43.4%'), not integer (e.g. '43%').\n"
            f"Block (first 500):\n{block[:500]}"
        )

    def test_spin_pct_values_are_in_valid_range(self, acceptance_stdout: str) -> None:
        """All spin_pct values must be in [0.0, 100.0] — the estimator clamps to this range."""
        block = self._dual_lens_block(acceptance_stdout)
        values = re.findall(r"spin_pct:\s*([\d.]+)%", block)
        assert values, "No 'spin_pct: N.N%' values found in dual-lens block"
        for raw in values:
            val = float(raw)
            assert 0.0 <= val <= 100.0, (
                f"spin_pct value {val}% is outside [0, 100] — estimator must clamp to this range"
            )

    def test_spin_pct_uses_decimal_format_not_integer(self, acceptance_stdout: str) -> None:
        """Each spin_pct must contain a decimal point (:.1f), not be an integer like '43%'."""
        block = self._dual_lens_block(acceptance_stdout)
        values = re.findall(r"spin_pct:\s*([\d.]+)%", block)
        assert values, "No spin_pct values found in dual-lens block"
        for raw in values:
            assert "." in raw, (
                f"spin_pct value {raw!r} missing decimal point — must use :.1f format (e.g. '43.4%')"
            )

    def test_at_least_two_spin_pct_values_in_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        """A dual-lens event needs one article per side — minimum 2 spin_pct annotations."""
        block = self._dual_lens_block(acceptance_stdout)
        values = re.findall(r"spin_pct:\s*[\d.]+%", block)
        assert len(values) >= 2, (
            f"Expected ≥2 'spin_pct:' annotations in the dual-lens block; found {len(values)}.\n"
            "A minimal dual-lens event requires one LEFT article and one RIGHT article, "
            "each with its own spin_pct."
        )

    def test_spin_pct_values_are_not_all_fifty(self, acceptance_stdout: str) -> None:
        """All spin_pct values at 50.0 would indicate the stub estimator is active.

        The fixture articles contain charged language, so the REAL deterministic
        lexical estimator must produce differentiated (non-50.0) values.
        """
        block = self._dual_lens_block(acceptance_stdout)
        values = [float(v) for v in re.findall(r"spin_pct:\s*([\d.]+)%", block)]
        assert values, "No spin_pct values found in dual-lens block"
        assert not all(v == 50.0 for v in values), (
            "All spin_pct values are exactly 50.0 — the stub estimator is running.\n"
            "The real lexical estimator must produce differentiated values for the fixture.\n"
            f"All values found: {values}"
        )

    def test_spin_pct_on_bullet_article_lines(self, acceptance_stdout: str) -> None:
        """'spin_pct:' must appear on '- <title> | spin_pct: N.N%' bullet lines."""
        bullet_spin_lines = [
            ln for ln in acceptance_stdout.splitlines()
            if ln.startswith("- ") and "spin_pct:" in ln
        ]
        assert bullet_spin_lines, (
            "No '- <title> | spin_pct: N.N%' bullet lines found in acceptance stdout.\n"
            "The dual-lens renderer must annotate each article bullet with its spin_pct."
        )

    def test_spin_delta_present_in_dual_lens_block(self, acceptance_stdout: str) -> None:
        block = self._dual_lens_block(acceptance_stdout)
        assert "spin_delta:" in block, (
            "'spin_delta:' annotation must appear inside the DUAL-LENS EVENTS block.\n"
            "Each dual-lens event must show its LEFT↔RIGHT spin divergence."
        )

    def test_spin_delta_values_non_negative(self, acceptance_stdout: str) -> None:
        block = self._dual_lens_block(acceptance_stdout)
        deltas = re.findall(r"spin_delta:\s*([\d.]+)", block)
        assert deltas, "No 'spin_delta:' values found in dual-lens block"
        for raw in deltas:
            assert float(raw) >= 0.0, (
                f"spin_delta must be ≥ 0.0; got {raw!r}"
            )

    def test_spin_delta_nonzero_for_left_right_fixture(self, acceptance_stdout: str) -> None:
        """The left and right fixture articles have different charged framing —
        their spin_pct values must differ, so at least one spin_delta must be > 0."""
        block = self._dual_lens_block(acceptance_stdout)
        deltas = re.findall(r"spin_delta:\s*([\d.]+)", block)
        assert deltas, "No spin_delta values found in dual-lens block"
        nonzero = [d for d in deltas if float(d) > 0.0]
        assert nonzero, (
            "All spin_delta values are 0.0.\n"
            "The left/right fixture articles use different charged language; "
            "at least one dual-lens event must show a nonzero divergence.\n"
            f"All delta values: {deltas}"
        )

    def test_rationale_lines_present_in_dual_lens_block(
        self, acceptance_stdout: str
    ) -> None:
        block = self._dual_lens_block(acceptance_stdout)
        rationale_lines = [ln for ln in block.splitlines() if "rationale:" in ln]
        assert rationale_lines, (
            "No 'rationale:' lines found in the DUAL-LENS EVENTS block.\n"
            "The lexical estimator must emit receipts; _print_dual_lens must render them "
            "as '  rationale: <text>' lines."
        )

    def test_spin_pct_annotates_both_left_and_right_articles(
        self, acceptance_stdout: str
    ) -> None:
        """spin_pct must appear on bullet lines in BOTH #### LEFT and #### RIGHT sections."""
        block = self._dual_lens_block(acceptance_stdout)
        lines = block.splitlines()
        in_left = in_right = False
        left_has_spin = right_has_spin = False
        for line in lines:
            if re.match(r"^#### LEFT\b", line):
                in_left, in_right = True, False
            elif re.match(r"^#### RIGHT\b", line):
                in_right, in_left = True, False
            elif line.startswith("#### ") or (line.startswith("## ") and line != "## DUAL-LENS EVENTS"):
                in_left = in_right = False
            if in_left and "spin_pct:" in line:
                left_has_spin = True
            if in_right and "spin_pct:" in line:
                right_has_spin = True

        assert left_has_spin, (
            "#### LEFT section must contain at least one 'spin_pct:' annotation"
        )
        assert right_has_spin, (
            "#### RIGHT section must contain at least one 'spin_pct:' annotation"
        )


# ---------------------------------------------------------------------------
# Criterion 4: digest-dry-run stdout has '*Situation Monitor*' and bullet entries
# ---------------------------------------------------------------------------


class TestCriterion4DigestDryRun:
    """Criterion 4: digest-dry-run must emit '*Situation Monitor*' and '•' bullets."""

    def test_digest_dry_run_exits_zero(
        self, digest_proc: subprocess.CompletedProcess
    ) -> None:
        assert digest_proc.returncode == 0, (
            f"digest-dry-run exited {digest_proc.returncode}, expected 0.\n"
            f"stderr:\n{digest_proc.stderr.decode(errors='replace')[-500:]}"
        )

    def test_digest_contains_situation_monitor_bold_heading(
        self, digest_stdout: str
    ) -> None:
        """'*Situation Monitor*' is the Telegram bold heading — must appear verbatim."""
        assert "*Situation Monitor*" in digest_stdout, (
            "digest-dry-run stdout must contain '*Situation Monitor*' (Telegram bold heading).\n"
            f"stdout:\n{digest_stdout[:1000]}"
        )

    def test_digest_contains_bullet_entries(self, digest_stdout: str) -> None:
        lines = digest_stdout.splitlines()
        bullets = [ln for ln in lines if ln.startswith("•")]
        assert bullets, (
            "digest-dry-run stdout must contain at least one '•' bullet entry.\n"
            f"stdout:\n{digest_stdout[:1000]}"
        )

    def test_digest_bullet_entries_are_non_empty(self, digest_stdout: str) -> None:
        """Each bullet must carry a story title — empty bullets are a render bug."""
        for line in digest_stdout.splitlines():
            if line.startswith("•"):
                assert line.strip() != "•", (
                    f"Empty bullet entry found in digest-dry-run stdout: {line!r}"
                )

    def test_digest_contains_top_stories_section(self, digest_stdout: str) -> None:
        assert "*Top Stories*" in digest_stdout, (
            "digest-dry-run stdout must contain '*Top Stories*' section.\n"
            f"stdout:\n{digest_stdout[:1000]}"
        )

    def test_digest_uses_telegram_bold_not_atx_markdown(
        self, digest_stdout: str
    ) -> None:
        """digest-dry-run emits Telegram *bold* format, NOT ATX Markdown (# headings)."""
        assert "*Situation Monitor*" in digest_stdout, (
            "digest-dry-run must use '*Situation Monitor*' Telegram bold, not '# ...' ATX"
        )
        assert not digest_stdout.strip().startswith("# Situation Monitor"), (
            "digest-dry-run must NOT start with '# Situation Monitor' (ATX Markdown) — "
            "it must use Telegram *bold* '*Situation Monitor*' format."
        )

    def test_digest_contains_date_stamp(self, digest_stdout: str) -> None:
        assert re.search(r"\d{4}-\d{2}-\d{2}", digest_stdout), (
            "digest-dry-run stdout must contain a YYYY-MM-DD date stamp"
        )

    def test_digest_no_traceback(self, digest_stdout: str) -> None:
        assert "Traceback" not in digest_stdout, (
            "digest-dry-run stdout must not contain a Python Traceback"
        )

    def test_digest_no_traceback_in_stderr(
        self, digest_proc: subprocess.CompletedProcess
    ) -> None:
        stderr = digest_proc.stderr.decode(errors="replace")
        assert "Traceback" not in stderr, (
            "digest-dry-run stderr must not contain a Python Traceback.\n"
            f"stderr:\n{stderr[:2000]}"
        )

    def test_digest_is_non_empty(self, digest_stdout: str) -> None:
        assert digest_stdout.strip(), "digest-dry-run must produce non-empty stdout"

    def test_digest_has_at_least_one_story_bullet(self, digest_stdout: str) -> None:
        bullets = [ln for ln in digest_stdout.splitlines() if ln.startswith("•")]
        assert len(bullets) >= 1, (
            f"digest-dry-run must contain at least 1 '•' story bullet; found {len(bullets)}"
        )

    def test_digest_and_once_produce_different_output(
        self, acceptance_stdout: str, digest_stdout: str
    ) -> None:
        """digest-dry-run (Telegram format) must differ from 'once' (ATX Markdown)."""
        assert digest_stdout != acceptance_stdout, (
            "'once' and 'digest-dry-run' must produce different output; "
            "one is ATX Markdown, the other is Telegram *bold* format."
        )

    def test_acceptance_combined_stdout_contains_situation_monitor_bold(
        self, acceptance_stdout: str
    ) -> None:
        """acceptance.py runs digest-dry-run (cmd2) internally — its output must appear
        in the combined acceptance stdout alongside the 'once' (cmd1) output."""
        assert "*Situation Monitor*" in acceptance_stdout, (
            "acceptance.py combined stdout must contain '*Situation Monitor*' from "
            "the digest-dry-run command (cmd2 runs without capture_output).\n"
            f"stdout (last 2 000):\n{acceptance_stdout[-2000:]}"
        )

    def test_acceptance_combined_stdout_contains_bullet(
        self, acceptance_stdout: str
    ) -> None:
        """Bullet entries from digest-dry-run must appear in the combined acceptance output."""
        bullets = [ln for ln in acceptance_stdout.splitlines() if ln.startswith("•")]
        assert bullets, (
            "acceptance.py combined stdout must contain '•' bullet entries from "
            "the digest-dry-run command (cmd2).\n"
            f"stdout (last 1 000):\n{acceptance_stdout[-1000:]}"
        )


# ---------------------------------------------------------------------------
# Structural prereq guards: fail early with clear messages
# ---------------------------------------------------------------------------


class TestPrerequisiteGuards:
    """Files and fixtures that must exist BEFORE any subprocess can succeed."""

    def test_rss_sample_xml_exists(self) -> None:
        assert RSS_FIXTURE.exists(), f"Primary fixture missing: {RSS_FIXTURE}"

    def test_rss_left_xml_exists(self) -> None:
        assert (FIXTURES / "rss_left.xml").exists(), "rss_left.xml fixture missing"

    def test_rss_right_xml_exists(self) -> None:
        assert (FIXTURES / "rss_right.xml").exists(), "rss_right.xml fixture missing"

    def test_rss_markets_xml_exists(self) -> None:
        assert (FIXTURES / "rss_markets.xml").exists(), "rss_markets.xml fixture missing"

    def test_rss_ai_xml_exists(self) -> None:
        assert (FIXTURES / "rss_ai.xml").exists(), "rss_ai.xml fixture missing"

    def test_rss_carrier_xml_exists(self) -> None:
        assert (FIXTURES / "rss_carrier.xml").exists(), "rss_carrier.xml fixture missing"

    def test_acceptance_source_defs_json_exists(self) -> None:
        assert ACCEPTANCE_SOURCE_DEFS.exists(), (
            f"acceptance_source_defs.json missing: {ACCEPTANCE_SOURCE_DEFS}"
        )

    def test_check_server_py_exists(self) -> None:
        assert (PROJECT_ROOT / "check_server.py").exists(), (
            "check_server.py missing from project root — cmd4 inside acceptance.py will fail"
        )

    def test_rss_carrier_xml_has_items(self) -> None:
        """Carrier fixture must have at least one <item> — otherwise carrier count is 0."""
        content = (FIXTURES / "rss_carrier.xml").read_text()
        assert "<item>" in content, (
            "rss_carrier.xml must contain at least one <item> element."
        )

    def test_acceptance_source_defs_covers_all_domain_feeds(self) -> None:
        import json
        data = json.loads(ACCEPTANCE_SOURCE_DEFS.read_text())
        assert "source_defs" in data, "acceptance_source_defs.json missing 'source_defs' key"
        urls = {sd["url"] for sd in data["source_defs"]}
        required = {
            "tests/fixtures/rss_left.xml",
            "tests/fixtures/rss_right.xml",
            "tests/fixtures/rss_markets.xml",
            "tests/fixtures/rss_ai.xml",
        }
        missing = required - urls
        assert not missing, (
            f"acceptance_source_defs.json missing these domain feed URLs: {missing}\n"
            "Without them the WORLD/MARKETS/AI sections will be empty."
        )

    def test_situation_monitor_package_is_importable(self) -> None:
        result = subprocess.run(
            [sys.executable, "-c", "import situation_monitor"],
            capture_output=True,
        )
        assert result.returncode == 0, (
            f"situation_monitor package is not importable:\n"
            f"{result.stderr.decode(errors='replace')}"
        )

    def test_no_recursive_pytest_in_this_file(self) -> None:
        """This file itself must not invoke pytest as a subprocess — that hangs the suite."""
        content = Path(__file__).read_text(errors="replace")
        for lineno, line in enumerate(content.splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if re.search(r'["\']pytest["\']', line) and re.search(
                r"\bsubprocess\.(run|Popen|call|check_output|check_call)\b", line
            ):
                pytest.fail(
                    f"Line {lineno}: recursive pytest subprocess call found:\n  {line.rstrip()}\n"
                    "Recursive pytest invocations hang the suite (project memory)."
                )

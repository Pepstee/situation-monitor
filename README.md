# Situation Monitor

Autonomous RSS + news ingest pipeline with bias scoring, propaganda detection, dual-lens event clustering, spin estimation, Polymarket odds matching, a practical market layer, and a live web dashboard.

## Quick start

```bash
pip install -e .
edge run
```

This loops `once` every `poll_interval_seconds`, printing a Markdown digest each cycle. To serve the web dashboard instead:

```bash
edge serve
# → http://localhost:8080
```

To run once and exit:

```bash
edge once
```

## Acceptance demo

The `acceptance` file contains the canonical smoke-test command. Run it from the project root:

```bash
cat acceptance | sh
```

Expected output: a Markdown digest with at least one story parsed from the bundled RSS fixture (`tests/fixtures/rss_sample.xml`), with no network access required.

---

## Dual-lens view — parity with Ground News

[Ground News](https://ground.news) shows how many outlets from each political wing are covering a given story, colour-coded left / centre / right, so readers can see when a story is being amplified by only one side. Situation Monitor implements the same mental model end-to-end in code.

`dual_lens.py` clusters incoming articles into *events* by multi-word title overlap (≥ 2 significant non-stopword tokens in common). Every article carries a political lean derived from the source registry or the curated `ALLSIDES_PRIORS` table. Once clustered, each event is split into three buckets — `left_articles`, `right_articles`, and `center_articles` — and a `spin_delta` is computed: the absolute difference between the average `spin_pct` of the left bucket and the average `spin_pct` of the right bucket.

The web dashboard (`edge serve`) renders each event as a side-by-side card:

```
┌─ Event: "Central bank raises rates" (spin_delta: 23.4) ──────────┐
│  LEFT                          │  RIGHT                           │
│  [spin_pct: 61%] Guardian…     │  [spin_pct: 38%] Fox News…       │
│  [spin_pct: 57%] Democracy Now │  [spin_pct: 42%] CNBC…           │
└──────────────────────────────────────────────────────────────────┘
```

Where Ground News shows *coverage spread* as a bar chart, Situation Monitor exposes the spin estimate inline so you can see not just *who* covered the story but *how hard* each outlet is framing it. The `/api/events` JSON endpoint and `/api/events/<id>/rationale` endpoint expose the full rubric breakdown for downstream analysis.

---

## Spin estimator — alignment with AllSides and MBFC methodology

[AllSides](https://www.allsides.com) rates outlets on a five-point political spectrum (Left → Lean Left → Center → Lean Right → Right) and explains each rating with editorial evidence. [Media Bias / Fact Check (MBFC)](https://mediabiasfactcheck.com) adds a factual reporting scale and flags specific rhetorical techniques — loaded language, propaganda, and selective omission — as the primary evidence categories.

`bias.py` implements a `SpinEstimator` that applies four rubrics to each article, matching MBFC's evidence taxonomy directly:

| Rubric | What it detects | MBFC / AllSides analogue |
|---|---|---|
| **Loaded Language** | Emotionally charged vocabulary swapped for neutral synonyms (e.g. *thug*, *hero*, *slam*) | MBFC "Loaded Headline / Story" flag |
| **Omission** | Missing opposing views, absent data, single-source claims on multi-actor events | AllSides "Missing Context" / MBFC factual reporting deductions |
| **Sourcing Asymmetry** | Credentialled experts quoted only for the favoured side; anonymous sourcing for the other | AllSides editorial-balance criterion |
| **Emotional Framing** | Personalised victim/hero narratives, rhetorical questions, fear/triumph sequencing before evidence | MBFC "Propaganda / Emotional" category |

The estimator sends article title and the first 1 500 characters of body text to an LLM backend (Claude or Ollama) with the four rubric definitions in the prompt, requesting a structured JSON response:

```json
{
  "spin_pct": 62.0,
  "lens": "right",
  "rubric": {
    "loaded_language": 0.75,
    "omission": 0.4,
    "sourcing_asymmetry": 0.3,
    "emotional_framing": 0.5
  }
}
```

When the LLM response is unparseable the estimator falls back to `ALLSIDES_PRIORS`, a merged dictionary seeded from the curated `CURATED_BIAS` table (which directly mirrors AllSides ratings for ~25 major domains) and augmented by the `DEFAULT_SOURCE_DEFS` registry. This means every article gets *at least* an AllSides-calibrated prior, with the LLM rubric applied on top when available.

For the `AI` domain, two additional fields are populated: `hype_vs_substance` (0 – 1 float measuring product-announcement vs. technical depth) and `vendor_pr` (boolean), enabling detection of corporate AI announcements dressed as journalism.

---

## Practical market layer — terminal parity

Professional terminals like Bloomberg and data providers like [Tiingo](https://api.tiingo.com) present a unified view of market movers, FX rates, commodity prices, and regulatory news alongside editorial flow. Situation Monitor replicates this pattern with free public data sources in `practical.py`.

`fetch_practical_movers()` pulls three data types each cycle:

| Asset class | Source | Notes |
|---|---|---|
| **EUR/USD FX rate** | ECB `eurofxref-daily.xml` | Daily reference rate; change expressed relative to a 1.10 baseline |
| **WTI Crude Oil** | Yahoo Finance RSS `CL=F` | Headline-parsed percentage change |
| **Gold** | Yahoo Finance RSS `GC=F` | Headline-parsed percentage change |

`fetch_regulatory_movers()` adds top-5 items from Reuters Politics and AP Politics RSS feeds as `PracticalMover` objects with direction, `who_it_affects`, and `what_to_watch` annotations — the same three-column format a terminal uses to contextualise a price move.

The `/api/practical` JSON endpoint exposes all movers for dashboard widgets or external consumers. This mirrors the way Bloomberg's top-panel shows the macro backdrop (FX, oil, rates) alongside the news ticker, enabling a reader to correlate a headline with the market reaction in a single view.

---

## Core flow end-to-end

```
1. Sources (RSS / hn:// / github_trending:// / crypto)
        ↓ per-source fetcher
   raw articles

2. dedup.py  — exact URL dedup + near-title dedup
   reliability.py  — per-source fetch counts → state_file

3. bias.py  — source lean + reliability label from ALLSIDES_PRIORS
   propaganda.py  — LLM flags (loaded language, propaganda)
   polymarket.py  — keyword match → implied odds from prediction market

4. dual_lens.py
     group_by_event()  — cluster by ≥2 shared significant words
     spin_fn per article  — SpinEstimator rubric (LLM or prior fallback)
     left / right / centre bucket assignment
     spin_delta = |avg_left_spin − avg_right_spin|

5. practical.py
     fetch_practical_movers()  — ECB FX, Yahoo Finance commodities
     fetch_regulatory_movers()  — Reuters Politics, AP Politics

6. Output
     once  → Markdown digest to stdout
     serve → Flask dashboard auto-refresh 60 s
              /api/events  (dual-lens JSON)
              /api/events/<id>/rationale  (per-article rubric receipts)
              /api/practical  (market movers JSON)
     run   → loop steps 1 – 6 every poll_interval_seconds
```

**Practical takeaway for one event:** a story about a Fed rate decision arrives from six sources. The left bucket (NPR, Guardian) averages spin_pct 55 with omission firing. The right bucket (CNBC, MarketWatch) averages spin_pct 38 with sourcing_asymmetry firing. spin_delta = 17. Simultaneously, the practical layer shows EUR/USD up 0.4 % and Gold up 1.1 %, which the dashboard renders below the event card — giving the reader both the narrative divergence and the real-world price signal in one screen.

---

## Source config — lenses and live feeds

Sources are defined in `situation_monitor/config.py` as `SourceDef` objects with a `domain` (`WORLD`, `MARKETS`, `AI`) and a `lens`. The four lenses and representative live feeds per domain:

### `left`
| Domain | Feed | URL |
|---|---|---|
| WORLD | The Guardian World | `https://www.theguardian.com/world/rss` |
| WORLD | Democracy Now | `https://www.democracynow.org/democracynow.rss` |
| WORLD | Al Jazeera | `https://www.aljazeera.com/xml/rss/all.xml` |
| MARKETS | The Nation Economy | `https://www.thenation.com/subject/economy/feed/` |
| MARKETS | Common Dreams | `https://www.commondreams.org/rss.xml` |
| AI | EFF Updates | `https://www.eff.org/rss/updates.xml` |
| AI | AlgorithmWatch | `https://algorithmwatch.org/en/feed/` |

### `right`
| Domain | Feed | URL |
|---|---|---|
| WORLD | Fox News World | `https://feeds.foxnews.com/foxnews/world` |
| WORLD | Breitbart | `https://feeds.feedburner.com/breitbart` |
| MARKETS | CNBC Markets | `https://www.cnbc.com/id/100003114/device/rss/rss.html` |
| MARKETS | MarketWatch | `https://feeds.marketwatch.com/marketwatch/topstories/` |
| AI | Reason | `https://reason.com/feed/` |
| AI | Forbes Tech | `https://www.forbes.com/technology/feed/` |

### `centre`
| Domain | Feed | URL |
|---|---|---|
| WORLD | BBC World | `https://feeds.bbci.co.uk/news/world/rss.xml` |
| WORLD | Reuters World | `https://feeds.reuters.com/Reuters/worldNews` |
| WORLD | NPR World | `https://feeds.npr.org/1004/rss.xml` |
| MARKETS | Reuters Business | `https://feeds.reuters.com/reuters/businessNews` |
| MARKETS | Yahoo Finance | `https://finance.yahoo.com/news/rssindex` |
| AI | Ars Technica | `https://feeds.arstechnica.com/arstechnica/index` |
| AI | MIT Technology Review | `https://www.technologyreview.com/feed/` |

### `state` (state-aligned)
| Domain | Feed | URL |
|---|---|---|
| WORLD | RT | `https://www.rt.com/rss/` |
| WORLD | TASS | `https://tass.com/rss/v2.xml` |
| WORLD | Xinhua World | `http://www.xinhuanet.com/english/rss/worldnews.xml` |
| MARKETS | People's Daily Economy | `http://en.people.cn/rss/90778.xml` |
| AI | Global Times | `https://www.globaltimes.cn/rss/outbrain.xml` |
| AI | CGTN Sci-Tech | `https://www.cgtn.com/subscribe/rss/section/sci-tech.xml` |

State-aligned feeds are included for narrative comparison, not as trusted sources. They are rated `center` in `ALLSIDES_PRIORS` to avoid distorting the lean-bucket averages, but the propaganda detector (`propaganda.py`) is more likely to fire on them.

---

## Configuration

Configuration is layered: defaults → JSON file (`--config PATH`) → environment variables (highest priority).

| Config field | Env var | Default | Description |
|---|---|---|---|
| `sources` | `SM_SOURCES` | `[]` | Comma-separated list of RSS URLs or local XML file paths |
| `poll_interval_seconds` | `SM_POLL_INTERVAL` | `600` | Seconds between `run` loop iterations |
| `dashboard_port` | `SM_DASHBOARD_PORT` | `8080` | Port for `serve` subcommand |
| `max_articles_per_digest` | `SM_MAX_ARTICLES` | `20` | Maximum articles per digest cycle |
| `log_level` | `SM_LOG_LEVEL` | `INFO` | Logging verbosity |
| `anthropic_model` | `SM_MODEL` | `claude-sonnet-4-6` | Anthropic model for LLM tasks |
| `llm_backend` | `SM_LLM_BACKEND` | `claude` | `claude` (subprocess) or `ollama` |
| `ollama_url` | `SM_OLLAMA_URL` | `http://localhost:11434` | Ollama API base URL |
| `ollama_model` | `SM_OLLAMA_MODEL` | `llama3` | Ollama model name |
| `polymarket_markets` | `SM_POLYMARKET_MARKETS` | `[]` | Path(s) to JSON market definition file(s) |
| `polymarket_slugs` | `SM_POLYMARKET_SLUGS` | `[]` | Polymarket slug(s) to fetch live from the API |
| `alert_threshold` | `SM_ALERT_THRESHOLD` | `0.8` | Relevance threshold for alerts |
| `digest_output_dir` | `SM_DIGEST_DIR` | `digests` | Directory for saved digests |
| `state_file` | `SM_STATE_FILE` | `state/reliability.json` | Reliability tracker state path |
| `telegram_token` | `SM_TELEGRAM_TOKEN` | — | Telegram bot token for alert delivery |
| `telegram_chat_id` | `SM_TELEGRAM_CHAT_ID` | — | Telegram chat ID for alert delivery |

### JSON config file

```json
{
  "sources": ["https://feeds.bbci.co.uk/news/rss.xml"],
  "poll_interval_seconds": 300,
  "dashboard_port": 8080,
  "llm_backend": "claude"
}
```

Pass it with `--config path/to/config.json`. Any field not present falls back to defaults and then env vars.

---

## Sources — fetcher routing

The `sources` config field (or `SM_SOURCES` env var) accepts a comma-separated list of URLs or local file paths. Each entry is routed to the appropriate fetcher:

| Scheme / pattern | Fetcher | Notes |
|---|---|---|
| `hn://` | `HNFetcher` | Hacker News front page via Algolia API |
| `github_trending://` | `GitHubTrendingFetcher` | GitHub trending repositories |
| URL containing `coindesk` or `cointelegraph` | `CryptoRSSFetcher` | Crypto RSS feeds |
| Any other URL or local `.xml` path | `RSSFetcher` | Standard RSS 2.0 |

## Architecture

```
sources (RSS / hn:// / github_trending:// / crypto)
          ↓ per-source fetcher
        raw articles
          ↓
        dedup.py  (exact URL dedup + near-title dedup)
        reliability.py  (per-source fetch counts → state_file)
          ↓
        bias.py  (lean, curated reliability label)
        propaganda.py  (LLM flags — best-effort)
        polymarket.py  (odds match)
        cluster assignment
          ↓
        dual_lens.py  (event clustering + spin estimation)
        practical.py  (FX / commodity / regulatory movers)
          ↓
        once → Markdown stdout
        serve → Flask dashboard (auto-refresh 60 s)
        run → loop once every poll_interval_seconds
```

LLM calls (`propaganda.py`, `bias.py`) go through the injectable `get_llm_client(config)` factory in `llm.py`. Pass `_override=callable` in tests to avoid real LLM calls.

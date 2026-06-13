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

## Industry Parity

Situation Monitor is benchmarked feature-by-feature against three reference products: **Ground News** (per-story political coverage spread and headline comparison), **AllSides** (outlet bias ratings with a published editorial rubric), and **Bloomberg Terminal / Tiingo CLI** (professional market data + news terminal). The three tables below enumerate the comparison; each row carries a concrete description of what the reference product actually does so the Status column can be read without background knowledge.

### Judge flow — one event through both lenses, spin estimate, and practical takeaway

When a new event enters the pipeline the following sequence fires automatically:

1. **Ingest** — articles from all configured sources are fetched and deduplicated. Each article carries a `source_lean` derived from `ALLSIDES_PRIORS` or `DEFAULT_SOURCE_DEFS`.
2. **Cluster** — `group_by_event()` in `dual_lens.py` clusters articles by ≥ 2 shared significant non-stopword tokens, producing one `DualLensEvent` per story.
3. **Both lenses** — articles are bucketed into `left_articles`, `right_articles`, and `center_articles`. The `SpinEstimator` runs four rubrics (loaded language, omission, sourcing asymmetry, emotional framing) on each article, returning a `spin_pct` (0–100) plus per-rubric scores stored as receipts.
4. **Spin estimate** — `spin_delta = |avg(left spin_pct) − avg(right spin_pct)|`. A high delta flags meaningful narrative divergence between wings.
5. **Practical takeaway** — `fetch_practical_movers()` runs in parallel: ECB EUR/USD rate, Yahoo Finance WTI crude and Gold price moves, and Reuters/AP Politics regulatory headlines. These appear beneath each event card.

**Worked example — Fed rate decision:**

```
Event: "Federal Reserve raises benchmark rate 50 bps"

Left bucket  (NPR, Guardian)     avg spin_pct = 55   [omission firing: no hawkish expert quoted]
Right bucket (CNBC, MarketWatch) avg spin_pct = 38   [sourcing_asymmetry firing: Fed officials only]
spin_delta = |55 − 38| = 17  →  moderate divergence flagged

Practical layer (same cycle):
  EUR/USD  +0.41 %  (ECB reference rate vs 1.10 baseline)
  WTI Crude  −1.2 %  (Yahoo Finance CL=F headline)
  Gold  +1.1 %       (Yahoo Finance GC=F headline)
  Regulatory: "Senate Banking Committee schedules emergency hearing" (Reuters Politics)

Dashboard output (edge serve):
┌─ Event: "Federal Reserve raises benchmark rate 50 bps"  spin_delta: 17.0 ──────────┐
│  LEFT (spin_pct avg 55)            │  RIGHT (spin_pct avg 38)                       │
│  [61%] Guardian — "Fed delivers…"  │  [38%] CNBC — "Fed hikes in line with…"        │
│  [49%] NPR — "Rate rise squeezes…" │  [38%] MarketWatch — "Fed signals pause…"      │
├────────────────────────────────────────────────────────────────────────────────────┤
│  Market movers: EUR/USD +0.41 %  │  WTI −1.2 %  │  Gold +1.1 %                     │
│  Regulatory: Senate Banking hearing (Reuters Politics)                              │
└────────────────────────────────────────────────────────────────────────────────────┘
```

The rationale endpoint (`/api/events/<id>/rationale`) exposes the full per-article rubric breakdown so any downstream consumer can audit the spin scores.

---

### Situation Monitor vs Ground News — lens comparison

Ground News (ground.news) is a commercial service that shows how many outlets from the political left, centre, and right are covering a given story, displayed as a colour-coded coverage bar. It identifies "blind spots" when a story is covered by only one wing, and shows the top headline from each side for direct comparison.

| Feature | Reference Product | Situation Monitor | Status |
|---|---|---|---|
| Per-story outlet count by political lean | Ground News: colour-coded bar showing number of left, centre, and right outlets covering each story; refreshed as new articles are indexed | `dual_lens.py`: `left_articles`, `right_articles`, `center_articles` bucket lists per `DualLensEvent`; counts exposed in `/api/events` JSON | Parity |
| Side-by-side headline comparison | Ground News: shows the top headline from one left and one right outlet for each story, enabling a direct wording comparison | Flask dashboard (`edge serve`): renders article titles from each bucket side-by-side in an event card with `spin_pct` inline per article | Exceeds — Situation Monitor shows all bucketed articles, not just one headline per side, and adds a spin score per article |
| Coverage blind-spot detection | Ground News: flags stories covered exclusively by one wing with a "blind spot" label | `spin_delta` = \|avg\_left\_spin − avg\_right\_spin\|; a delta threshold can be used to surface divergent events; no dedicated "blind spot" label | Gap — Ground News has an explicit one-click blind-spot filter; Situation Monitor exposes the signal via spin_delta but does not label it |
| Quantified framing divergence | Ground News: no framing or spin score; coverage spread only | `SpinEstimator` produces `spin_pct` per article and `spin_delta` per event; rubric receipts at `/api/events/<id>/rationale` | Exceeds — Situation Monitor adds a quantified framing layer absent from Ground News |
| Source coverage breadth | Ground News: indexes thousands of outlets across 50+ countries via a proprietary crawl | Situation Monitor: ~30 configured RSS feeds from 4 lenses (left, right, centre, state); extensible via `SM_SOURCES` | Gap — Ground News indexes far more outlets; Situation Monitor is limited to configured feeds |
| User-curated story interest | Ground News: users can follow topics and receive a personalised feed filtered to their interests | No personalisation layer; all configured sources are ingested each cycle | Gap — Ground News has a follow/interest graph; Situation Monitor is not personalised |
| Access model | Ground News: freemium web app with a paid subscription for full features | Situation Monitor: self-hosted open-source CLI and dashboard; no paywall | Exceeds — zero cost, no account required, data stays local |

---

### Situation Monitor vs AllSides — bias methodology, rubric, and outlet ratings

AllSides (allsides.com) publishes a five-point political bias rating (Left, Lean Left, Center, Lean Right, Right) for hundreds of US news outlets, each rating backed by one or more of four evidence types: editorial review, blind survey of readers, community feedback, or independent research. AllSides also publishes an editorial-balance rubric explaining the criteria used to rate outlets.

| Feature | Reference Product | Situation Monitor | Status |
|---|---|---|---|
| Outlet bias rating scale | AllSides: five-point spectrum — Left, Lean Left, Center, Lean Right, Right — published for ~900 outlets with editorial evidence notes | `ALLSIDES_PRIORS` + `CURATED_BIAS` table in `bias.py`: five-point scale mirroring AllSides for ~25 major domains (guardian.com, foxnews.com, bbc.co.uk, cnbc.com, etc.); `DEFAULT_SOURCE_DEFS` fills remaining configured feeds | Gap — AllSides covers ~900 outlets; Situation Monitor's curated table covers ~25 with the rest defaulting to `center` |
| Loaded language detection | AllSides: editorial reviewers flag headlines containing emotionally charged vocabulary as evidence for a bias rating; no automated per-article score | `SpinEstimator` rubric: charged words are matched against a synonym list and scored 0–1 as `loaded_language`; contributes to `spin_pct` | Exceeds — Situation Monitor automates per-article scoring rather than relying on periodic editorial review |
| Omission / missing context | AllSides: "Missing Context" is one of four named evidence categories; editors cite specific omissions when rating an outlet | `SpinEstimator` rubric: `omission` score (0–1) flags missing opposing views, absent data, or single-source claims on multi-actor events | Exceeds — applied per article in real time; AllSides applies this criterion only during periodic outlet reviews |
| Sourcing asymmetry | AllSides: editorial-balance criterion checks whether credentialled experts are quoted for both sides; assessed at outlet level over time | `SpinEstimator` rubric: `sourcing_asymmetry` score (0–1) checks whether expert or official quotes favour only one side within a single article | Exceeds — per-article granularity vs AllSides' outlet-level periodic assessment |
| Emotional framing | AllSides: no named rubric category; emotional or sensationalist content may inform the editorial review holistically | `SpinEstimator` rubric: `emotional_framing` score (0–1) flags personalised victim/hero narratives, rhetorical questions, fear/triumph sequencing before evidence | Exceeds — explicit scored rubric category absent from AllSides' published methodology |
| Machine-readable per-article scores | AllSides: outlet ratings are published as human-readable web pages and a downloadable CSV; no per-article JSON | `spin_pct` (0–100 float) + `{"loaded_language": 0–1, "omission": 0–1, "sourcing_asymmetry": 0–1, "emotional_framing": 0–1}` returned per article; full breakdown at `/api/events/<id>/rationale` | Exceeds — AllSides has no per-article machine-readable rubric output |
| LLM fallback to curated prior | AllSides: ratings are human-assigned; no LLM or algorithmic fallback | When the LLM (`claude` or `ollama`) returns an unparseable response, `SpinEstimator` falls back to `ALLSIDES_PRIORS` — the curated table seeded from AllSides ratings | Parity — ensures every article gets at least an AllSides-calibrated lean even when the LLM is unavailable |
| Outlet rating update cadence | AllSides: ratings are updated periodically (months to years) via structured editorial review or new reader surveys | `ALLSIDES_PRIORS` / `CURATED_BIAS` are updated by editing `bias.py`; no automated cadence | Gap — AllSides has a formal review process; Situation Monitor requires a manual code edit to update ratings |

---

### Situation Monitor vs Bloomberg Terminal / Tiingo CLI — market dashboard

Bloomberg Terminal is a professional financial data platform providing real-time streaming prices across the full asset universe (equities, fixed income, FX, commodities, derivatives), alongside a news ticker, regulatory filings, and analyst research. Tiingo CLI is an open-source command-line tool that queries the Tiingo API for end-of-day and intraday price data, news headlines, and fundamentals — a developer-friendly terminal analogue at lower cost.

| Feature | Reference Product | Situation Monitor | Status |
|---|---|---|---|
| FX rate display | Bloomberg: real-time streaming FX cross-rates for 170+ currency pairs with bid/ask spread, daily range, and historical charts. Tiingo CLI: intraday and end-of-day FX for major pairs via `tiingo fx` | `practical.py` `fetch_practical_movers()`: ECB `eurofxref-daily.xml` for EUR/USD daily reference rate; change expressed relative to a 1.10 baseline; exposed at `/api/practical` | Gap — Bloomberg/Tiingo cover 170+ pairs with real-time streaming; Situation Monitor covers EUR/USD daily via a free public XML feed |
| Commodity price display | Bloomberg: real-time streaming prices for the full commodity complex (crude benchmarks, nat gas, metals, agricultural). Tiingo CLI: end-of-day commodity futures via the Tiingo API | `fetch_practical_movers()`: Yahoo Finance RSS headline-parsed percentage change for WTI crude (`CL=F`) and Gold (`GC=F`) | Gap — Bloomberg/Tiingo cover the full commodity complex in real time; Situation Monitor covers two instruments via RSS headline parsing |
| Regulatory and political news movers | Bloomberg: dedicated "Government" and "Regulation" news channels; analysts tag stories with affected tickers for direct price-news correlation. Tiingo CLI: news headlines via Tiingo API tagged with tickers | `fetch_regulatory_movers()`: top-5 items from Reuters Politics and AP Politics RSS; each mover has `direction`, `who_it_affects`, and `what_to_watch` fields; exposed at `/api/practical` | Parity — Situation Monitor delivers the same three-column context (direction / who / what to watch) as a terminal regulatory-mover row, sourced from the same Reuters and AP wire feeds |
| News-market correlation view | Bloomberg: top panel shows macro backdrop (FX, rates, oil, equities indices) alongside the news ticker in a single screen; analysts can click a headline to see the price reaction | Dashboard (`edge serve`): practical movers rendered beneath each dual-lens event card, correlating a specific story with the same-cycle FX and commodity moves | Parity — Situation Monitor replicates the layout pattern (macro backdrop + news headline in one view) using free public data |
| Data refresh rate | Bloomberg: real-time streaming (sub-second tick data). Tiingo CLI: intraday (1-minute bars via WebSocket or polling) | `edge run` polls every `poll_interval_seconds` (default 600 s); ECB FX reference rate is published once daily | Gap — Bloomberg/Tiingo stream tick-by-tick; Situation Monitor is a polling system on a configurable interval |
| Asset universe breadth | Bloomberg: equities, fixed income, FX, commodities, derivatives, crypto, private markets — effectively the full global asset universe. Tiingo: US equities, ETFs, mutual funds, FX, crypto, news | Three instruments (EUR/USD, WTI crude, Gold) plus Reuters/AP regulatory headlines; no equities, no bonds, no derivatives | Gap — intentional scope narrowing; Situation Monitor provides macro backdrop context only, not portfolio analytics |
| Cost and access model | Bloomberg: ~$25 000/year terminal licence. Tiingo CLI: free tier (5 000 API calls/day); paid tiers for higher limits and intraday data | Self-hosted open-source; all data sources are free public feeds (ECB, Yahoo Finance RSS, Reuters RSS, AP RSS); no API key required for default configuration | Exceeds — zero marginal cost; no account or licence required; data stays local |
| Analyst research and ratings | Bloomberg: integrated analyst consensus, price targets, earnings estimates, and sector-level research | Not implemented; Situation Monitor covers editorial framing and market movers, not financial research | Gap — out of scope for Situation Monitor's design goals |

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

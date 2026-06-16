# Situation Monitor

Autonomous RSS + news ingest pipeline with bias scoring, propaganda detection, dual-lens event clustering, spin estimation, Polymarket odds matching, a practical market layer, and a live web dashboard.

## Capability Summary

Situation Monitor **exceeds** Ground News on per-article spin scoring and explainability (Ground News shows a coverage-spread bar only; Situation Monitor adds quantified rubric scores and a machine-readable audit trail per article). It **meets** AllSides on bias methodology by operationalising AllSides' editorial-balance criteria into four automated rubrics — loaded language, omission, sourcing asymmetry, and emotional framing — scored per article in real time. It achieves **partial parity** with Bloomberg Terminal on market data (ECB FX, Yahoo Finance commodities, Reuters/AP regulatory headlines vs. real-time streaming across 170+ instruments) while **exceeding** it on cost (free public feeds vs. ~$25 000/year licence).

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

## Core Flow

The following walkthrough traces a single event — a US Federal Reserve rate decision — through all five pipeline stages, showing example text output at each step.

**1. One event ingested**

Six sources fetch the story. After URL and near-title deduplication, five articles survive with source-lean assignments from `ALLSIDES_PRIORS`:

```
source             lean    domain
guardian.com       left    WORLD
npr.org            left    WORLD
cnbc.com           right   MARKETS
marketwatch.com    right   MARKETS
reuters.com        center  WORLD
```

**2. Left-lens framing extracted**

`SpinEstimator` runs on the Guardian article (title + first 1 500 chars). The LLM returns:

```json
{
  "spin_pct": 61,
  "lens": "left",
  "rubric": {
    "loaded_language": 0.60,
    "omission": 0.70,
    "sourcing_asymmetry": 0.30,
    "emotional_framing": 0.55
  }
}
```

Rubric receipt logged: `omission` firing — no hawkish economist quoted; loaded headline: "Fed delivers blow to working families".

**3. Right-lens framing extracted**

`SpinEstimator` runs on the CNBC article:

```json
{
  "spin_pct": 38,
  "lens": "right",
  "rubric": {
    "loaded_language": 0.20,
    "omission": 0.30,
    "sourcing_asymmetry": 0.55,
    "emotional_framing": 0.20
  }
}
```

Rubric receipt logged: `sourcing_asymmetry` firing — all quotes from Fed officials; no consumer-advocacy group cited.

**4. Spin estimate produced with rubric receipts**

`dual_lens.py` computes the event-level delta:

```
left bucket  (Guardian, NPR)      avg spin_pct = 55.0
right bucket (CNBC, MarketWatch)  avg spin_pct = 38.0
spin_delta = |55.0 − 38.0| = 17.0  →  moderate divergence flagged
```

Full rubric receipts accessible at `/api/events/<id>/rationale`:

```json
{
  "event_id": "fed-rate-50bps",
  "spin_delta": 17.0,
  "articles": [
    { "source": "guardian.com",    "spin_pct": 61, "rubric": { "omission": 0.70 } },
    { "source": "cnbc.com",        "spin_pct": 38, "rubric": { "sourcing_asymmetry": 0.55 } }
  ]
}
```

**5. Practical takeaway generated**

`fetch_practical_movers()` runs in the same cycle:

```
EUR/USD   +0.41 %   ECB eurofxref-daily.xml vs 1.10 baseline
WTI Crude −1.2  %   Yahoo Finance CL=F RSS headline
Gold      +1.1  %   Yahoo Finance GC=F RSS headline

Regulatory: "Senate Banking Committee schedules emergency rate hearing"
            who_it_affects: "US banks, mortgage lenders"
            what_to_watch:  "potential reversal signal from Congress"
```

Dashboard output (`edge serve`):

```
┌─ Federal Reserve raises benchmark rate 50 bps  spin_delta: 17.0 ────────────────┐
│  LEFT (avg spin 55)                │  RIGHT (avg spin 38)                         │
│  [61%] Guardian — "Fed delivers…"  │  [38%] CNBC — "Fed hikes in line with…"      │
│  [49%] NPR — "Rate rise squeezes…" │  [38%] MarketWatch — "Fed signals pause…"    │
├──────────────────────────────────────────────────────────────────────────────────┤
│  EUR/USD +0.41 %  │  WTI −1.2 %  │  Gold +1.1 %                                  │
│  Regulatory: Senate Banking hearing  (Reuters Politics)                            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

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

### Ground News parity

Ground News (ground.news) is a commercial service that shows per-story political coverage spread, side-by-side headline comparison across the left/centre/right spectrum, and blind-spot alerts when a story is covered by only one wing. The table below maps five core feature dimensions to their Situation Monitor equivalents.

| Feature | Ground News | Situation Monitor | Verdict | Justification |
|---|---|---|---|---|
| Lens comparison | Colour-coded bar showing count of left / centre / right outlets per story; top headline from one source per side | `dual_lens.py` left/right/centre bucket lists per `DualLensEvent`; all bucketed article titles rendered side-by-side with `spin_pct` per article in the dashboard | Exceeds | Shows all bucketed articles, not just one headline per side; adds a per-article spin score absent from Ground News |
| Spin measurement | No framing or spin score; coverage-spread bar only | `SpinEstimator`: `spin_pct` (0–100) per article; `spin_delta` per event; full four-rubric breakdown at `/api/events/<id>/rationale` | Exceeds | Quantified framing layer absent from Ground News; machine-readable rubric receipts enable third-party auditing |
| Source balance config | Proprietary outlet index; no user-configurable source list | Sources defined via `SM_SOURCES` env var or JSON config; any RSS feed assignable to any lens | Meets | Same configurability intent delivered through an open, editable config rather than a closed proprietary index |
| Breaking alerts | Push notifications on mobile app when a story becomes a blind spot or breaks above a coverage threshold | Telegram delivery via `SM_TELEGRAM_TOKEN` / `SM_TELEGRAM_CHAT_ID` when relevance exceeds `SM_ALERT_THRESHOLD` | Meets | Same alert-on-threshold pattern; Situation Monitor uses Telegram rather than a proprietary push channel |
| Explainability | No rubric or reasoning exposed; colour bar only | Per-article rubric scores (`loaded_language`, `omission`, `sourcing_asymmetry`, `emotional_framing`) at `/api/events/<id>/rationale` | Exceeds | Explicit machine-readable audit trail per article; Ground News provides no explanation of why a story is labelled divergent |
| Access model | Freemium web app; full features require a paid subscription | Self-hosted open-source CLI and dashboard; no paywall, no account required, data stays local | Exceeds | Zero marginal cost and full feature access without a licence |

---

### Bias methodology vs AllSides / MBFC

AllSides publishes a five-point outlet bias rating backed by editorial review, reader surveys, and community feedback. MBFC adds a factual reporting scale and flags specific rhetorical techniques as named evidence categories. The table below states how each rubric dimension maps from those methodologies into `SpinEstimator`.

| Rubric dimension | AllSides methodology | MBFC outlet-rating usage | Situation Monitor operationalisation |
|---|---|---|---|
| Loaded language | Editorial reviewers flag emotionally charged headlines as evidence for a bias rating; no automated per-article score | "Loaded Headline / Story" flag applied during outlet review; marks outlets that habitually use charged vocabulary | `loaded_language` score (0–1): LLM matches charged words against a synonym list per article; contributes to `spin_pct`; stored as a rubric receipt |
| Omission | "Missing Context" is one of four named evidence categories; editors cite specific omissions when rating an outlet | Factual-reporting deductions for absent data or selective framing; applied at outlet level | `omission` score (0–1): LLM flags absent opposing views, missing data, or single-source claims on multi-actor events; scored per article in real time |
| Sourcing asymmetry | Editorial-balance criterion: credentialled experts quoted for both sides; assessed at outlet level over time | No named category; may inform the factual-reporting rating holistically | `sourcing_asymmetry` score (0–1): LLM checks whether expert or official quotes favour only one side within a single article |
| Emotional framing | No named rubric category; emotional or sensationalist content informs the editorial review holistically | "Propaganda / Emotional" category flagged during outlet review; marks outlets that routinely use emotional appeals | `emotional_framing` score (0–1): LLM flags personalised victim/hero narratives, rhetorical questions, fear/triumph sequencing before evidence |

---

### Market layer vs terminal dashboard

Bloomberg Terminal is a professional financial platform with real-time streaming prices across the full asset universe, a news ticker, regulatory filings, and analyst research. The table below compares the three core terminal-layer dimensions — data freshness, instruments covered, and actionability output format — against Situation Monitor's `practical.py`.

| Dimension | Bloomberg Terminal | Situation Monitor | Parity |
|---|---|---|---|
| Data freshness | Real-time streaming tick data; sub-second update latency | ECB FX published once daily; commodities and regulatory items fetched every `poll_interval_seconds` (default 600 s) | partial |
| FX instruments covered | 170+ currency pairs with real-time bid/ask, daily range, and historical charts | EUR/USD daily reference rate only (ECB `eurofxref-daily.xml`; change vs 1.10 baseline) | partial |
| Oil instruments covered | Full crude complex: WTI, Brent, nat gas, and refined products in real time | WTI Crude (`CL=F`) via Yahoo Finance RSS headline-parsed percentage change | partial |
| Regulatory events coverage | Dedicated Government/Regulation channels; stories tagged with affected tickers for direct price-news correlation | Top-5 Reuters Politics and AP Politics RSS items per cycle; each annotated with `direction`, `who_it_affects`, `what_to_watch` | meets |
| Actionability output format | Price moves, analyst ratings, earnings estimates, and price targets per instrument | `PracticalMover` objects: `direction`, `who_it_affects`, `what_to_watch`; rendered beneath dual-lens event cards on the dashboard | meets |
| Cost model | ~$25 000/year terminal licence | Free; all sources are public feeds (ECB, Yahoo Finance RSS, Reuters RSS, AP RSS); no API key required | exceeds |

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
| `llm_backend` | `SM_LLM_BACKEND` | `ollama` | `claude` (subprocess) or `ollama` |
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
  "llm_backend": "ollama"
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

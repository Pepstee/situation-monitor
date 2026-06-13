# CAPABILITY_CHECKLIST.md

Machine-readable binary feature matrix. Every `Status` cell is `PASS` or `FAIL`.
`PASS` = feature implemented and verified in code. `FAIL` = not implemented.

## vs Ground News

| Feature | Ground News | This project | Status |
|---|---|---|---|
| Lens comparison | Left/centre/right coverage-spread bar; one headline per side | `dual_lens.py` left/right/centre buckets; all article titles + `spin_pct` per article side-by-side | PASS |
| Spin measurement | No framing score; coverage count only | `SpinEstimator` returns `spin_pct` (0–100) + four-rubric breakdown per article | PASS |
| Source config | Proprietary outlet index; not user-configurable | Sources defined via `SM_SOURCES` env var or JSON; any RSS feed assignable to any lens | PASS |
| Breaking alerts | Push notifications via mobile app on coverage threshold | Telegram delivery via `SM_TELEGRAM_TOKEN` when relevance exceeds `SM_ALERT_THRESHOLD` | PASS |
| Explainability | No rubric or reasoning exposed; colour bar only | Per-article rubric scores at `/api/events/<id>/rationale`; full machine-readable audit trail | PASS |
| Open access | Freemium; full features require paid subscription | Self-hosted open-source CLI + dashboard; no paywall, no account, data stays local | PASS |

## vs AllSides

| Feature | AllSides | This project | Status |
|---|---|---|---|
| Loaded language detection | Editorial reviewers flag charged headlines at outlet level | `loaded_language` score (0–1) per article via LLM synonym matching; stored as rubric receipt | PASS |
| Omission scoring | "Missing Context" named category; assessed at outlet level over time | `omission` score (0–1): LLM flags absent opposing views or missing data per article in real time | PASS |
| Sourcing asymmetry | Editorial-balance criterion; credentialled experts on both sides; outlet-level | `sourcing_asymmetry` score (0–1): LLM checks within-article quote balance per article | PASS |
| Emotional framing | Informs editorial review holistically; no named per-article rubric | `emotional_framing` score (0–1): LLM flags victim/hero narratives and fear sequencing per article | PASS |
| Outlet bias prior | Five-point rating (Left → Right) for major outlets; editorial + reader survey | `ALLSIDES_PRIORS` / `CURATED_BIAS` table mirrors AllSides ratings for ~25 domains; LLM fallback | PASS |
| Per-article score | No per-article score; outlet-level rating only | `spin_pct` per article computed from four rubrics; not collapsed to outlet-level | PASS |

## vs Terminal dashboard

| Feature | Terminal dashboard | This project | Status |
|---|---|---|---|
| Real-time FX streaming | 170+ currency pairs; sub-second latency | EUR/USD daily reference rate only (ECB `eurofxref-daily.xml`; change vs 1.10 baseline) | FAIL |
| Multi-pair FX coverage | Full currency universe with bid/ask and daily range | EUR/USD only; no other pairs | FAIL |
| Commodity streaming | WTI, Brent, nat gas, and refined products in real time | WTI Crude (`CL=F`) via Yahoo Finance RSS; headline-parsed; no Brent or nat gas | FAIL |
| Regulatory news feed | Dedicated Gov/Regulation channels; stories tagged to affected tickers | Top-5 Reuters Politics + AP Politics RSS items per cycle; annotated with `who_it_affects` | PASS |
| Actionable output format | Price moves, analyst ratings, earnings estimates per instrument | `PracticalMover`: `direction`, `who_it_affects`, `what_to_watch`; rendered on dashboard | PASS |
| Cost | ~$25 000/year terminal licence | Free; all sources are public feeds (ECB, Yahoo Finance RSS, Reuters RSS, AP RSS) | PASS |

## Core-flow walkthrough — Fed rate decision (one concrete example per step)

1. **Ingest** — six RSS sources fetch the story; URL and near-title dedup leaves five articles.
   Source leans assigned from `ALLSIDES_PRIORS`: Guardian→left, NPR→left, CNBC→right,
   MarketWatch→right, Reuters→centre.

2. **Cluster** — `group_by_event()` in `dual_lens.py` finds ≥ 2 shared non-stopword tokens
   ("Federal", "Reserve", "rate") across all five articles; one `DualLensEvent` produced with
   `event_id="fed-rate-50bps"`.

3. **Both lenses scored** — `SpinEstimator` runs on Guardian (left): `spin_pct=61`,
   `omission=0.70` fires (no hawkish economist quoted; headline: "Fed delivers blow to working
   families"). Runs on CNBC (right): `spin_pct=38`, `sourcing_asymmetry=0.55` fires (all quotes
   from Fed officials; no consumer group cited).

4. **Spin delta computed** — left bucket (Guardian, NPR) avg `spin_pct=55`; right bucket (CNBC,
   MarketWatch) avg `spin_pct=38`; `spin_delta=|55−38|=17` — moderate divergence flagged.
   Full rubric receipts at `/api/events/fed-rate-50bps/rationale`.

5. **Practical takeaway** — `fetch_practical_movers()` returns: EUR/USD +0.41 % (ECB reference),
   WTI −1.2 % (Yahoo Finance CL=F), Gold +1.1 % (Yahoo Finance GC=F); plus Reuters Politics
   item "Senate Banking Committee schedules emergency rate hearing" annotated
   `who_it_affects: US banks, mortgage lenders`, `what_to_watch: potential reversal signal`.

# Judge Rubric

Binary checklist. Mark each row PASS or FAIL. All criteria are observable without inference.

## Ground-News

- PASS foxnews.com lean is "right" in curated bias data — situation_monitor/bias.py:get_source_lean
- PASS cnn.com lean is "left" in curated bias data — situation_monitor/bias.py:get_source_lean
- PASS reuters.com lean is "center" in curated bias data — situation_monitor/bias.py:get_source_lean
- PASS unknown domain returns None from lean lookup — situation_monitor/bias.py:get_source_lean
- PASS source config lens maps to bias lean vocabulary — situation_monitor/bias.py:_lens_to_lean

## AllSides

- PASS nytimes.com lean is "left-center" matching AllSides Lean Left — situation_monitor/bias.py:get_source_lean
- PASS wsj.com lean is "right-center" matching AllSides Lean Right — situation_monitor/bias.py:get_source_lean
- PASS bbc.com lean is "center" in curated bias data — situation_monitor/bias.py:get_source_lean
- PASS breitbart.com lean is "right" with reliability "low" — situation_monitor/bias.py:get_source_reliability
- PASS reuters.com and apnews.com have reliability tier "high" — situation_monitor/bias.py:get_source_reliability

## Terminal-Market

- PASS PolymarketClient fetches markets from gamma-api endpoint — situation_monitor/polymarket.py:fetch_markets
- PASS PolymarketClient.match returns float odds or None — situation_monitor/polymarket.py:match
- PASS PolymarketMatcher.match returns None on no keyword overlap — situation_monitor/polymarket.py:match
- PASS article polymarket_odds populated after ingest-and-enrich — situation_monitor/__main__.py:_ingest_and_enrich
- PASS polymarket slugs loaded from config into client — situation_monitor/__main__.py:_load_polymarket_markets

## Core-Flow

- PASS RSS fetcher returns list of Article objects per feed — situation_monitor/ingestion/rss.py:fetch
- PASS articles grouped into dual-lens events by title similarity — situation_monitor/dual_lens.py:group_by_event
- PASS daily digest formats and sends Telegram notification — situation_monitor/digest.py:daily_digest
- PASS dashboard make_app returns WSGI-compatible Flask app — situation_monitor/dashboard.py:make_app
- PASS ingest-and-enrich runs all source defs, returns articles — situation_monitor/__main__.py:_ingest_and_enrich
- PASS alert check emits alerts for high-relevance articles above threshold — situation_monitor/alerting.py:check_and_emit_alerts

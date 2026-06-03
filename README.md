# Situation Monitor

Autonomous RSS + news ingest pipeline with bias scoring, propaganda detection, polymarket odds matching, and a live web dashboard.

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

## Configuration

Configuration is layered: defaults → JSON file (`--config PATH`) → environment variables (highest priority).

| Config field | Env var | Default | Description |
|---|---|---|---|
| `sources` | `SM_SOURCES` | `[]` | Comma-separated list of RSS URLs or local XML file paths |
| `poll_interval_seconds` | `SM_POLL_INTERVAL` | `600` | Seconds between `run` loop iterations |
| `dashboard_port` | `SM_DASHBOARD_PORT` | `8080` | Port for `serve` subcommand |
| `max_articles_per_digest` | `SM_MAX_ARTICLES` | `20` | Maximum articles per digest cycle |
| `fetch_interval_seconds` | `SM_FETCH_INTERVAL` | `3600` | (reserved) |
| `log_level` | `SM_LOG_LEVEL` | `INFO` | Logging verbosity |
| `anthropic_model` | `SM_MODEL` | `claude-sonnet-4-6` | Anthropic model for LLM tasks |
| `llm_backend` | `SM_LLM_BACKEND` | `claude` | `claude` (subprocess) or `ollama` |
| `ollama_url` | `SM_OLLAMA_URL` | `http://localhost:11434` | Ollama API base URL |
| `ollama_model` | `SM_OLLAMA_MODEL` | `llama3` | Ollama model name |
| `polymarket_markets` | `SM_POLYMARKET_MARKETS` | `[]` | Path(s) to JSON market definition file(s) |
| `alert_threshold` | `SM_ALERT_THRESHOLD` | `0.8` | Relevance threshold for alerts |
| `digest_output_dir` | `SM_DIGEST_DIR` | `digests` | Directory for saved digests |
| `state_file` | `SM_STATE_FILE` | `null` | Path to optional state file |

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

## Architecture

```
sources (RSS/XML) → RSSFetcher → Article list
                                    ↓
                             bias.py  (lean, reliability)
                             propaganda.py (LLM flags)
                             polymarket.py (odds match)
                             cluster assignment
                                    ↓
                      once → Markdown stdout
                      serve → Flask dashboard (auto-refresh 60 s)
                      run → loop once every poll_interval_seconds
```

LLM calls (`propaganda.py`) go through the injectable `get_llm_client(config)` factory in `llm.py`. Pass `_override=callable` in tests to avoid real LLM calls.

# Situation Monitor

A lightweight, zero-dependency tool for ingesting local events and generating human-readable situational summaries.

## Purpose

Situation Monitor processes a stream of timestamped events (read from JSON files or stdin) and produces concise situational summaries by:
- **Grouping** events by context, category, or other logical boundaries
- **Computing** statistics: counts, time ranges, severity distributions
- **Formatting** results as readable text for terminal output

This is a *bounded scaffold*—ideal for learning event processing architectures or as a foundation for custom ingestion pipelines.

## Repository Layout

```
situation-monitor/
├── README.md                 # This file
├── architecture.md           # Component design and data flow
├── execution_order.md        # Build plan for 8 sequential tasks
├── task_graph.json          # Dependency graph and effort estimates
│
├── src/
│   ├── __init__.py          # Package metadata
│   ├── models.py            # Event, Situation, Summary data classes
│   ├── loader.py            # EventLoader: reads and validates events
│   ├── aggregator.py        # EventAggregator: groups and summarizes events
│   ├── formatter.py         # OutputFormatter: renders summaries as text
│   └── cli.py               # CLI argument parsing and orchestration
│
├── tests/
│   ├── test_models.py
│   ├── test_loader.py
│   ├── test_aggregator.py
│   └── test_formatter.py
│
├── data/
│   ├── sample_events.json           # Simple example event set
│   └── sample_events_complex.json   # Multi-category, multi-severity events
│
└── docs/
    ├── USAGE.md              # Usage examples and workflows
    └── EVENT_FORMAT.md       # Event schema documentation
```

## How to Run

### Prerequisites
- Python 3.8+ (no pip dependencies required)

### Basic Usage

Process a local event file:
```bash
python3 -m situation_monitor data/sample_events.json
```

This reads events from `sample_events.json`, groups and summarizes them, and prints the result to stdout.

### From stdin

```bash
cat data/sample_events.json | python3 -m situation_monitor
```

### Options

```bash
python3 -m situation_monitor --help
```

Expected options:
- `--input FILE` or positional arg: path to JSON event file (or stdin if omitted)
- `--output FORMAT` or `-f`: output format (text, table, json)
- `--group-by FIELD`: group events by field (e.g., category, severity)
- `--filter EXPR`: filter events before aggregation (e.g., severity >= ERROR)

### Explicit live sources

The archived live ingesters now use the same parsers as fixture mode:

```bash
python3 -m monitor fetch --live --source hackernews --limit 30
python3 -m monitor fetch --live --source github_trending --language python --since weekly
python3 -m monitor fetch --live --source rss --rss-url https://example.org/feed.xml
python3 -m monitor fetch --dry-run --digest
```

`--live` is required for HTTP requests. Live mode defaults to HN and GitHub when no source
is selected, with a 15-second request timeout and a 4 MB response limit. RSS needs an explicit
URL. Fetching does not start a daemon, invoke a model, send alerts or write state.

### Recurring source checks

Run selected fixture checks repeatedly into an explicit database:

```bash
python3 -m monitor watch --state state.sqlite3 --source hackernews --interval-seconds 60
python3 -m monitor watch --state state.sqlite3 --source hackernews --interval-seconds 1 --cycles 2
python3 -m monitor watch --config monitor.json --live
```

Use Ctrl-C to stop the foreground process. Each completed source check has a durable SQLite
receipt; `--cycles` provides a bounded run. JSON configuration accepts the archived `db_path`,
`interval`, `sources`, `alert_threshold`, `alert_log` and `llm_endpoint` fields. INI configuration
accepts `[database] path` and `[monitor] poll_interval_s` / `log_level`. CLI state and interval
options override configuration. Missing configuration files fail, and no database path is implicit.
Watch consumes alert configuration and uses a model endpoint only when explicitly configured.

### Local alert events

Evaluate an inclusive score rule against bundled local fixtures and retain only new
firings in an explicit SQLite state file:

```bash
python3 -m monitor alerts evaluate --state state.sqlite3 --at 5000 --threshold 20
python3 -m monitor alerts list --state state.sqlite3 --unresolved
python3 -m monitor alerts resolve 1 --state state.sqlite3
```

This path performs no network calls, callbacks, or external notifications.

### Local dashboard snapshot

Inspect an existing state file without starting a server or modifying the database:

```bash
python3 -m monitor dashboard --state state.sqlite3 --at 5000 --window-hours 24
```

The command emits a deterministic JSON snapshot of recent analyzed articles, completed
run receipts, registered-source schedules, and the resolved/unresolved alert lifecycle.
`--state` must name an existing SQLite file and `--at` is always explicit. The command
opens state read-only and performs no network calls, callbacks, providers, or daemons.

## Current Limitations

This is a **bounded scaffold**. The following are intentionally out of scope:

- **No realtime ingestion:** Events are read from static JSON files only.
- **No implicit persistent storage:** Stateful commands require an explicit `--state`
  SQLite path; summary and dry-run fetch commands remain side-effect free.
- **Explicit remote fetching:** `fetch --live` enables public source HTTP reads. Fixture commands stay offline; no background fetching is implicit.
- **No machine learning:** No anomaly detection, predictions, or statistical modeling.
- **No UI/visualization:** Terminal output only; no web interface or graphing.
- **No external dependencies:** Uses Python standard library exclusively (no pip installs).
- **Sample data only:** Bundled with toy event datasets for testing and demonstration.

## Architecture Overview

See [architecture.md](architecture.md) for detailed component descriptions and data flow diagrams.

In brief:
1. **Models** define Event, Situation, and Summary data structures.
2. **Loader** reads JSON event files and validates them.
3. **Aggregator** groups events and computes summaries.
4. **Formatter** renders summaries as human-readable text.
5. **CLI** orchestrates the entire pipeline.

## Quick Start for Developers

1. **Initialize the project** (Task 1):
   - Create directory structure: `src/`, `tests/`, `data/`, `docs/`
   - Write this README and minimal `pyproject.toml`

2. **Define data models** (Task 2):
   - `src/models.py`: Event, Situation, Summary classes with type hints

3. **Implement components** (Tasks 3–6):
   - Loader, Aggregator, Formatter, CLI

4. **Test and document** (Tasks 7–8):
   - Unit tests, sample data, usage guide

See [execution_order.md](execution_order.md) for the full 8-task build plan.

## License

MIT (or specify as needed)

### Source metadata

Article JSON includes `metadata`: HN source ID, points (`raw_score`), author and comment
count, or GitHub repository ID, stars (`raw_score`) and language. Unavailable values remain
null. Popularity is source data, not the monitor's urgency score. SQLite schema 4 retains
these values through analysis and restart. Opening an older database for writing upgrades
it in place while preserving existing articles and run receipts. Read-only snapshots of
schema 3 remain supported without altering the original database.

### Scoring and alert delivery in watch

Every collected batch is scored and persisted. The default scorer is offline. To use the
archived JSON/Ollama protocol, explicitly provide `--model-endpoint URL` or `llm_endpoint`
in configuration. This sends article content to that endpoint and can incur its provider
costs. Failed responses are reported and recorded, with collected articles preserved.
No paid endpoint was used in migration validation.

`--alert-threshold 70` selects the inclusive 0–100 threshold. Legacy JSON
`alert_threshold: 0.7` means the same value. `--alert-log PATH` (or configured `alert_log`)
appends complete event JSON lines and prevents duplicate file delivery after restart.
Alerts also print to stderr. Use one writer per state/log pair. A malformed existing log
fails visibly and is not overwritten. Without a log, stderr alerts may repeat on restart.

Programmatic `AlertRule` and `AlertManager` in `monitor.alerts` restore independent callback
rules, reset and batch evaluation. Their deduplication is process-local. Persisted alert
firing and resolution continue to belong to `StateStore`.

### Local dashboard and digest export

Run `python3 -m monitor serve --state PATH` to view the existing database at
`http://127.0.0.1:8080`. Select another port with `--port`. Ctrl-C stops the listener.
The page refreshes every 30 seconds and never fetches source articles itself. It shows
articles, scores and source/model reliability. JSON is available at `/data`, `/api/items`
and `/api/reliability`. Use an SSH tunnel to access the loopback dashboard from another
machine.

Watch measures source latency, skips URLs successfully scored within 24 hours, and retries
unscored items. `--digest-output PATH` writes the current batch's scored Markdown digest.
An empty batch writes an empty digest. Older prototype databases have different layouts and
are rejected without conversion; preserve them separately. Only earlier canonical Article
databases are upgraded automatically.

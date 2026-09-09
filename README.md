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

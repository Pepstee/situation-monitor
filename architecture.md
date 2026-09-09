## Migration reconciliation — 9 September 2026

The active implementation is the `monitor` package on
`codex/situation-monitor-capability-union-r1`. The design below is historical and its
`src` layout and proposed interfaces are not a description of the current tree.

Compared sources: the original Mac `situation-monitor`, the OX union branch, and the
archived agentic-orchestrator `situation-monitor`, `situation-monitor-v2`, and empty
`situation-monitor-v3` directories. The original Event schema tests are retained. The additional claude-orchestrator-main
`situation_monitor_run` directory contains historical task specifications targeting the
original copy, with no additional executable implementation. Its requested historical
validation report is missing evidence, not a missing product feature.
The canonical default event fixture has been restored from the original Mac copy;
a missing or wholly invalid input now exits unsuccessfully rather than claiming success.

| Capability | Current consolidation state |
| --- | --- |
| Event loading and deterministic summary | Retained; bundled default command verified |
| HN, GitHub and RSS parsing | Retained with fixture/injected byte clients |
| Scoring, deduplication and clustering | Deterministic path retained |
| SQLite state, source scheduling, alert lifecycle and dashboard JSON | Retained and tested |
| Live HN/GitHub HTTP ingestion | Restored through canonical parsers and explicit `fetch --live`; real public CLI smoke passed |
| HTTP dashboard and JSON endpoints | Restored loopback server, escaped HTML and four read-only routes, sharing canonical snapshot queries |
| Recurring scheduler lifecycle | Restored by `watch` and the interruptible canonical `run_source_loop`; bounded two-cycle CLI verified |
| Configuration loading | JSON and INI formats retained by `monitor.config`; watch consumes state, sources, interval, logging, alert and explicit model settings |
| Alert log output and callback dispatch | Restored by monitor.alerts and watch; persistent firing remains owned by StateStore, file delivery survives restart |
| Upstream popularity/author metadata | Restored in canonical Article metadata, parser output and SQLite v4; canonical schema-3 rows and receipts survive upgrade |
| Near-duplicate digest suppression | Restored optional score-ranked text suppression in the canonical digest renderer; source records remain intact |
| Generic source/check definitions | Restored in StateStore and sources/checks/events CLI; targets and conditions remain inert metadata as in v2 |
| Optional model scoring | Restored explicit JSON/Ollama HTTP scorer and injected scorer function; bounded invalid-response retries, failure receipts and default offline heuristic |

Migration is pending this capability reconciliation. An earlier bounded-union milestone
must not be treated as proof that every prototype capability has survived. Restoring code
does not activate networking, callbacks, model spend or persistent services by default.

# Situation Monitor: Architecture

## Overview

Situation Monitor is a four-stage event processing pipeline that transforms raw events into human-readable summaries. Each stage is a standalone module with a clear interface, enabling modular testing and future extensions.

```
┌──────────────┐
│ JSON Events  │
│   (stdin)    │
└──────┬───────┘
       │
       ▼
┌──────────────────────────────────────────────────────┐
│ Loader                   src/loader.py               │
│ Validates and parses events from files or stdin      │
│ Output: List[Event]                                  │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────┐
│ Aggregator                   src/aggregator.py       │
│ Groups events by context, computes statistics        │
│ Output: List[Summary]                                │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────┐
│ Formatter                    src/formatter.py        │
│ Renders summaries as human-readable text/tables      │
│ Output: str (text, table, or structured)             │
└──────────────┬───────────────────────────────────────┘
               │
               ▼
┌──────────────┐
│   stdout     │
│ (or file)    │
└──────────────┘
```

## Components

### 1. Models (`src/models.py`)

**Purpose:** Define the core data structures and contracts.

**Classes:**

#### Event
Represents a single event ingested from the source.

```python
@dataclass
class Event:
    timestamp: datetime     # When the event occurred
    source: str            # Origin (e.g., "app", "service-a", "log-file")
    category: str          # Event type (e.g., "error", "warning", "info")
    severity: str          # Severity level (e.g., "critical", "error", "warning", "info")
    message: str           # Human-readable event description
    context: dict          # Arbitrary key-value metadata
```

#### Situation
A logical grouping or classification of events. (Defined in Task 2; exact schema TBD by builder.)

#### Summary
An aggregated view of one or more events. Contains:
- Situation identifier
- Event count
- Time range (first seen, last seen)
- Severity distribution
- Category breakdown
- Key statistics (counts by source, message frequency)

### 2. Loader (`src/loader.py`)

**Purpose:** Read and validate events from JSON files or stdin.

**Class:** `EventLoader`

**Key methods:**
- `load_from_file(path: str) -> List[Event]`: Read and parse JSON file
- `load_from_stdin() -> List[Event]`: Read events from standard input
- `validate(event: dict) -> Event`: Parse and validate a single event against the Event schema

**Input format:** JSON array of event objects:
```json
[
  {
    "timestamp": "2026-06-01T10:30:00Z",
    "source": "app",
    "category": "error",
    "severity": "critical",
    "message": "Database connection lost",
    "context": {"user_id": 123, "session": "abc"}
  },
  ...
]
```

**Output:** `List[Event]` (validated Python objects)

**Error handling:** Raises `ValueError` for malformed JSON or missing required fields.

### 3. Aggregator (`src/aggregator.py`)

**Purpose:** Process events and generate summaries grouped by situation.

**Class:** `EventAggregator`

**Key methods:**
- `aggregate(events: List[Event]) -> List[Summary]`: Group events and produce summaries
- `group_by(field: str) -> Dict[str, List[Event]]`: Group events by a specified field
- `compute_statistics(events: List[Event]) -> dict`: Calculate counts, time ranges, distributions

**Logic:**
1. Accept a list of validated events
2. Group events by situation (default: by category; configurable)
3. For each group, compute:
   - Event count
   - Time range (first/last event)
   - Severity distribution (breakdown by severity level)
   - Source distribution (breakdown by source)
   - Message frequency (most common messages)
4. Return a list of `Summary` objects

**Example grouping strategies:**
- By category: "errors", "warnings", "info"
- By source: "service-a", "service-b", "app"
- By severity: "critical", "error", "warning", "info"

### 4. Formatter (`src/formatter.py`)

**Purpose:** Render summaries as human-readable text for terminal output.

**Class:** `OutputFormatter`

**Key methods:**
- `format(summaries: List[Summary], style: str = "text") -> str`: Convert summaries to formatted text
- Supports styles: `text` (narrative), `table` (columnar), `json` (structured)

**Example output (text style):**
```
═══════════════════════════════════════════════
Situation: Database Errors (Critical)
═══════════════════════════════════════════════
Total Events:    15
Time Range:      2026-06-01 09:00:00 — 10:45:00
Last Updated:    2026-06-01 10:45:30

Severity Breakdown:
  critical:      8 events
  error:         5 events
  warning:       2 events

Top Sources:
  service-db:    9 events (60%)
  app:           6 events (40%)

Most Common Messages:
  1. "Connection timeout" (5 occurrences)
  2. "Query failed" (4 occurrences)
  3. "Deadlock detected" (3 occurrences)
```

### 5. CLI (`src/cli.py` and `src/__main__.py`)

**Purpose:** Orchestrate the pipeline and expose it to the user.

**Entry point:** `python -m situation_monitor [OPTIONS] [INPUT_FILE]`

**Responsibilities:**
- Parse command-line arguments
- Instantiate Loader, Aggregator, and Formatter
- Orchestrate the pipeline: load → aggregate → format → output
- Handle errors gracefully (malformed input, missing files, etc.)

**Argument interface:**
```
Usage: situation_monitor [OPTIONS] [INPUT_FILE]

Options:
  -h, --help              Show help message
  -f, --format FORMAT     Output format: text, table, json (default: text)
  -g, --group-by FIELD    Group events by field (default: category)
  --filter EXPR           Filter events (e.g., severity >= error)

Arguments:
  INPUT_FILE              JSON event file (default: stdin)
```

## Data Flow

### 1. Input Phase
- User runs `python -m situation_monitor data/events.json`
- CLI parses arguments and instantiates Loader

### 2. Loading Phase
- Loader reads JSON file or stdin
- Each event is parsed and validated against Event schema
- Returns `List[Event]` (or raises error if invalid)

### 3. Aggregation Phase
- Aggregator receives validated events
- Groups events by category (or specified field)
- Computes statistics for each group: counts, time ranges, distributions
- Returns `List[Summary]` (one per group)

### 4. Formatting Phase
- Formatter receives summaries
- Renders each summary as text, table, or JSON
- Returns formatted string

### 5. Output Phase
- CLI writes formatted text to stdout
- User reads the result

### Example Flow

**Input:**
```json
[
  {"timestamp": "2026-06-01T10:00:00Z", "category": "error", "severity": "critical", "message": "DB timeout"},
  {"timestamp": "2026-06-01T10:05:00Z", "category": "error", "severity": "error", "message": "Query failed"},
  {"timestamp": "2026-06-01T10:10:00Z", "category": "warning", "severity": "warning", "message": "Slow query"}
]
```

**After Aggregator:**
```python
[
  Summary(situation="error", count=2, severities={"critical": 1, "error": 1}, ...),
  Summary(situation="warning", count=1, severities={"warning": 1}, ...)
]
```

**After Formatter (text style):**
```
═══════════════════════════════════════════════
Situation: Error (Critical)
═══════════════════════════════════════════════
Total Events:    2
Time Range:      2026-06-01 10:00:00 — 10:05:00

Severity Breakdown:
  critical:      1 event
  error:         1 event

Most Common Messages:
  1. "DB timeout" (1 occurrence)
  2. "Query failed" (1 occurrence)

═══════════════════════════════════════════════
Situation: Warning
═══════════════════════════════════════════════
Total Events:    1
Time Range:      2026-06-01 10:10:00 — 10:10:00

Severity Breakdown:
  warning:       1 event

Most Common Messages:
  1. "Slow query" (1 occurrence)
```

## Design Principles

1. **Separation of Concerns:** Each module handles one responsibility (loading, processing, formatting, CLI).
2. **Data Validation:** Events are validated on load; downstream modules trust the data.
3. **Immutability:** Events and Summaries are read-only dataclasses; no state mutations.
4. **Standard Library Only:** No external dependencies, ensuring portability.
5. **Testability:** Each component has clear inputs and outputs, enabling unit tests.
6. **Extensibility:** New formatters, grouping strategies, and filters can be added without changing the core pipeline.

## Future Extensions (Out of Scope)

- **Realtime ingestion:** Stream from event brokers (Kafka, Redis)
- **Persistent storage:** Cache summaries, enable historical queries
- **Advanced filtering:** DSL for complex event queries
- **Anomaly detection:** ML-based pattern recognition
- **Visualization:** Web dashboard, charts, graphs
- **Multi-threaded processing:** Parallel event processing for large datasets

---

For implementation details, see [execution_order.md](execution_order.md) and the task breakdown in [task_graph.json](task_graph.json).

Configuration has a distinct serialization responsibility, so `monitor/config.py` is the single
new owner replacing the two archived loaders. There was no configuration owner in `monitor` to
extend. Missing explicit configuration files now fail rather than silently creating a default
SQLite database. Recurrence extends the existing scheduler and state store rather than introducing
a second scheduler. Live registrations are named `live:<source>` and commands admit only their
selected registrations, preventing an offline fixture tick from executing or relabelling live work.

### Restored pipeline ownership

`monitor.analysis` retains one scoring/clustering owner. Its explicit HTTP scorer replaces
the archived generic HTTP implementation. Callable scorer injection replaces the v2
provider-specific construction path, whose prompt formatting failed before the model call.
The v2 offline heuristic remains the default. No particular hosted-provider SDK or model is
required or automatically activated. Model bounds express supplied uncertainty, not a
verified statistical confidence level.

`monitor.alerts` is a distinct output/callback lifecycle responsibility. It calls no SQLite
transaction internals and duplicates no persisted event owner. Callback failure remains
retryable. File delivery uses complete event JSON lines for restart deduplication. File and
stderr delivery are not atomic; a complete file receipt is the durable acknowledgement.
Without a log, stderr deduplication lasts only for the current process. The historical
0–1 configured threshold is converted to the canonical 0–100 scale before evaluation.

### Dashboard, timing and pipeline completion checks

`monitor.dashboard` replaces the two archived HTTP servers while reusing CLI snapshot
queries. It owns rendering and listener lifecycle only. The server binds loopback because
it has no authentication. HTML escapes untrusted text and only creates HTTP(S) links.
`/data` exposes the full snapshot, `/api/items` its articles, and `/api/reliability` all
source and model run statistics. Source checks measure elapsed time in watch; deterministic
tick keeps its supplied timestamp semantics.

Watch filters recently scored URLs before storage and scoring, preserving their analysis
and avoiding repeated model calls within 24 hours. Unscored failures remain eligible for
retry. `--digest-output` writes the current batch's actual scored Markdown digest. Foreign
v1/v2 database layouts are rejected before schema writes and must be preserved separately.
This is not an importer for prototype runtime data.

### Final known-copy capability accounting

The original Mac scaffold, OX canonical, archived agentic v1/v2 and empty v3, and the
claude-orchestrator task-specification directory have been compared. All implemented
behaviour identified in that review is represented above. V2 source/check/event persistence
uses the existing sources and StateStore owner with distinct condition_checks and
condition_events tables. These hold arbitrary target/condition definitions and supplied
events; they do not execute targets or evaluate conditions. Existing Article alert events
remain a separate lifecycle. Canonical database versions 3 and 4 upgrade to version 5.

Intentional replacements: duplicated transport/model implementations use the canonical
interfaces; provider-specific SDK auto-construction is replaced by explicit HTTP or injected
scoring. Defective threshold units, unsafe HTML, silent failure and missing-default behaviour
are repaired. Historical prototype databases are not converted or deleted. Missing historical
validation reports remain missing. No runtime capability was inferred from aspirational
portfolio text or unexecuted task specifications. Linux acceptance is recorded separately.

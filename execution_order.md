# Situation Monitor: Execution Order

## Overview
This document explains the sequencing of the 8-task plan to build a lightweight situational-awareness tool. The build follows a strict linear critical path due to tight component dependencies: each layer builds on the previous one.

## Build Phases

### Phase 1: Foundation (Tasks 1–2)
**Purpose:** Establish the project skeleton and define the core data structures.

- **Task 1 (Project Setup):** Initialize the project directory structure, documentation templates, and build configuration. This is a prerequisite for all other work; no code can be written without it.
  
- **Task 2 (Core Data Models):** Define the `Event`, `Situation`, and `Summary` classes with type hints. This establishes the contract that all downstream components will use. Must come before the loader, aggregator, or formatter can be implemented.

**Why this order:** The project structure must exist before creating any modules. Data models must be defined before any code can consume them.

---

### Phase 2: Core Processing (Tasks 3–4)
**Purpose:** Build the intake and analysis pipeline.

- **Task 3 (Event Loader):** Implement the loader that reads sample events from JSON files or stdin, validates them against the Event model, and returns a sequence of events. Depends on the Event model from Task 2.

- **Task 4 (Event Aggregator):** Implement the aggregator that consumes the stream of events from the loader, groups them by situation/context, computes statistics (counts, time ranges, severity distributions), and produces Summary objects. Depends on both the Event model (Task 2) and the Loader (Task 3).

**Why this order:** Events must be loaded before they can be aggregated. The aggregator is the business logic core—it cannot run without validated input.

---

### Phase 3: Presentation (Tasks 5–6)
**Purpose:** Define how summaries reach the user.

- **Task 5 (Output Formatter):** Implement the formatter that takes Summary objects and renders them as human-readable text or structured output. Depends on the Summary model from Task 2 and the Aggregator output from Task 4.

- **Task 6 (CLI Interface):** Wire together the loader, aggregator, and formatter into a single command-line tool. Parse arguments, orchestrate the pipeline, and handle I/O. Depends on all prior components.

**Why this order:** Formatting depends on aggregated summaries; the CLI is the final integration point that pulls everything together.

---

### Phase 4: Quality & Documentation (Tasks 7–8)
**Purpose:** Validate the implementation and document how to use it.

- **Task 7 (Unit Tests):** Write tests for models, loader, aggregator, and formatter. This validates the entire pipeline at the module level. Depends on all processing and presentation code being complete (Task 6).

- **Task 8 (Sample Data & Docs):** Create example event files and write usage guides. This documents the expected event format and demonstrates the tool in action. Depends on the full implementation being testable (Task 7).

**Why this order:** Testing requires working code. Documentation is most credible when based on a tested, working system. Sample data is useful for both testing and user onboarding.

---

## Dependency Graph

```
task_001 (Project Setup)
    ↓
task_002 (Core Data Models)
    ↓
task_003 (Event Loader)
    ↓
task_004 (Event Aggregator)
    ↓
task_005 (Output Formatter)
    ↓
task_006 (CLI Interface)
    ↓
task_007 (Unit Tests)
    ↓
task_008 (Sample Data & Docs)
```

## Parallelization
**Currently: None.** Every task depends on its predecessor. If future work separates concerns (e.g., testing the loader independently before building the aggregator), tasks 3 and 4 could be split into smaller parallelizable steps.

## Key Assumptions

1. **No external dependencies:** The plan assumes Python standard library only (json, argparse, dataclasses, etc.). If third-party libraries are introduced, Task 1 must be updated to include dependency management.

2. **Linear intake model:** Events flow in a single pass: load → aggregate → format → output. No caching, state persistence, or interactive modes are planned in this scaffold.

3. **Sample data is local:** All event sources are files or stdin. No remote fetches, APIs, or database connections.

4. **Human-readable output is text-based:** No visualization libraries, web UI, or complex rendering. Output is terminal-friendly (text, simple tables).

## Effort Estimates

| Phase | Tasks | Total Effort | Notes |
|-------|-------|--------------|-------|
| Foundation | 2 | Low | Configuration and boilerplate. |
| Core Processing | 2 | Medium | Business logic and data transformations. |
| Presentation | 2 | Medium | CLI orchestration and formatting. |
| Quality & Docs | 2 | Low–Medium | Testing and example data. |
| **Total** | **8** | **Medium** | Suitable for 2–3 developer-weeks or focused iterations. |

## Build Order Rationale

**Linear critical path:** The choice to sequence tasks strictly (no parallelization) reflects the fact that:

1. Each component's interface depends on the previous one (loader ← models, aggregator ← loader, etc.).
2. Early tasks are simple (setup, models) and unlock later, more complex work (aggregator, CLI).
3. Testing and documentation are most effective when all code is in place.

**Flexibility:** Once Phase 2 (Task 4, aggregator) is complete, the developer can optionally bifurcate into two parallel tracks:
- One developer writes Task 5 & 6 (presentation).
- Another writes tests for completed modules (partial Task 7).

However, for a lean scaffold, the linear order is clearer and less risky.

---

## Completion Criteria

Each phase is complete when:

- **Phase 1:** `src/models.py` defines Event, Situation, Summary with type hints; project structure is in place.
- **Phase 2:** `src/aggregator.py` can read events from the loader and produce Summary objects with statistics.
- **Phase 3:** Running `python -m situation_monitor <events.json>` produces human-readable output to stdout.
- **Phase 4:** All tests pass; `docs/USAGE.md` and sample data are available for user onboarding.

Once Phase 4 is complete, the scaffold is ready for production use, enhancement, or deployment.

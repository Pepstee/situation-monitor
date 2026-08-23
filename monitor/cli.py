"""Command-line interface for Situation Monitor.

Entry point for the event processing pipeline.
"""

import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from monitor.ingest import load_events
from monitor.summarize import summarize


def main() -> int:
    """Run the Situation Monitor CLI.

    Loads sample events from data/sample_events.json and prints a summary.

    Returns:
        0 on success, 1 on error.
    """
    # Determine the project root (parent of monitor directory)
    project_root = Path(__file__).parent.parent

    # Path to sample events file
    events_file = project_root / "data" / "sample_events.json"

    # Load events
    events, errors = load_events(str(events_file))

    # Report any loading errors
    if errors:
        for error in errors:
            print(f"Warning: {error}", file=sys.stderr)

    # Generate and print summary
    summary = summarize(events)
    print(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())

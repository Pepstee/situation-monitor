"""Event summarization module for Situation Monitor.

Generates human-readable summaries of event collections with deterministic output.
"""

from typing import List
from collections import Counter
import sys
from pathlib import Path

# Import Event schema from parent package
sys.path.insert(0, str(Path(__file__).parent.parent))
from schemas import Event


def summarize(events: List[Event]) -> str:
    """Generate a human-readable summary of events.

    Creates a deterministic summary string describing event counts, category
    distribution, and severity distribution. Output is always the same for
    the same input (no randomness, no timestamps).

    Args:
        events: List of Event instances to summarize.

    Returns:
        A human-readable summary string. If events list is empty, returns
        a clear "no events" message.

    Examples:
        >>> summarize([])
        'No events detected.'

        >>> summarize(events_with_3_geo_1_high)
        '3 geopolitical events detected; 1 high-severity event.'
    """
    # Handle empty event list
    if not events:
        return "No events detected."

    # Count events by category and severity
    category_counts = Counter(event.category for event in events)
    severity_counts = Counter(event.severity for event in events)

    # Build summary parts in deterministic order
    summary_parts = []

    # Add category breakdown in alphabetical order
    sorted_categories = sorted(category_counts.items())
    for category, count in sorted_categories:
        if count == 1:
            summary_parts.append(f"{count} {category} event detected")
        else:
            summary_parts.append(f"{count} {category} events detected")

    # Add severity breakdown in deterministic order (high, medium, low)
    severity_order = ["high", "medium", "low"]
    for severity in severity_order:
        if severity in severity_counts:
            count = severity_counts[severity]
            if count == 1:
                summary_parts.append(f"{count} {severity}-severity event")
            else:
                summary_parts.append(f"{count} {severity}-severity events")

    return "; ".join(summary_parts) + "."

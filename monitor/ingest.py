"""Event ingestion module for Situation Monitor.

Handles loading and parsing events from JSON files with graceful error handling.
"""

import json
import sys
from pathlib import Path
from typing import List, Tuple

# Import Event schema from parent package
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from schemas import Event


def load_events(file_path: str) -> Tuple[List[Event], List[str]]:
    """Load and parse events from a JSON file.

    Reads a JSON file containing an array of event objects, validates each event
    against the Event schema, and returns both valid events and error messages
    for invalid entries.

    Args:
        file_path: Path to the JSON file containing events.

    Returns:
        A tuple of (valid_events, error_messages) where:
        - valid_events: List of Event instances that passed validation
        - error_messages: List of error messages for invalid entries (or file errors)

    The function gracefully handles:
    - Missing files (reports error, returns empty list)
    - Invalid JSON format (reports error, returns empty list)
    - Empty JSON arrays (returns empty list with no errors)
    - Missing required fields in individual events (skips event, reports error)
    - Invalid severity values (skips event, reports error)
    """
    valid_events: List[Event] = []
    error_messages: List[str] = []

    # Check if file exists
    path = Path(file_path)
    if not path.exists():
        error_messages.append(f"Error: File not found: {file_path}")
        return valid_events, error_messages

    # Try to read and parse the JSON file
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
            # Handle empty files
            if not content.strip():
                error_messages.append(f"Warning: File is empty: {file_path}")
                return valid_events, error_messages

            data = json.loads(content)
    except json.JSONDecodeError as e:
        error_messages.append(f"Error: Invalid JSON in {file_path}: {e}")
        return valid_events, error_messages
    except Exception as e:
        error_messages.append(f"Error reading file {file_path}: {e}")
        return valid_events, error_messages

    # Ensure data is a list
    if not isinstance(data, list):
        error_messages.append(f"Error: Expected JSON array at top level, got {type(data).__name__}")
        return valid_events, error_messages

    # Handle empty array
    if len(data) == 0:
        return valid_events, error_messages

    # Process each event
    for idx, event_data in enumerate(data):
        try:
            event = Event.from_dict(event_data)
            valid_events.append(event)
        except (ValueError, TypeError) as e:
            error_messages.append(f"Error at index {idx}: {e}")
        except Exception as e:
            error_messages.append(f"Unexpected error at index {idx}: {e}")

    return valid_events, error_messages

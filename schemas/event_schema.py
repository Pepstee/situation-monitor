"""Event schema for Situation Monitor.

Defines the Event data model with validation for incoming event data.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional


class SourceReliability(str, Enum):
    """Coarse, explicit confidence in an article's source."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


@dataclass
class Article:
    """A normalized article emitted by every canonical ingestion adapter."""

    url: str
    title: str
    source: str
    body: str = ""
    published_at: Optional[datetime] = None
    reliability: SourceReliability = SourceReliability.UNKNOWN
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, str | int | float | None] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("url", "title", "source"):
            value = getattr(self, field_name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Article.{field_name} must not be empty")
        if not isinstance(self.reliability, SourceReliability):
            raise TypeError("Article.reliability must be a SourceReliability")
        if not isinstance(self.tags, list) or not all(
            isinstance(tag, str) for tag in self.tags
        ):
            raise TypeError("Article.tags must be a list of strings")


@dataclass
class Event:
    """A single event representing a discrete occurrence in the system.

    Attributes:
        id: Unique identifier for the event (string).
        title: Human-readable title/name of the event.
        source: Origin or system where the event was generated.
        timestamp: ISO-8601 formatted timestamp of when the event occurred.
        category: Logical category or type of event (e.g., 'error', 'warning', 'info').
        severity: Importance level - must be 'low', 'medium', or 'high'.
        summary: Brief description or summary of the event.
    """

    id: str
    title: str
    source: str
    timestamp: str
    category: str
    severity: str
    summary: str

    # Valid severity levels
    VALID_SEVERITIES = {"low", "medium", "high"}

    def __post_init__(self) -> None:
        """Validate the event after initialization.

        Raises:
            ValueError: If severity is not one of the valid levels.
        """
        if self.severity not in self.VALID_SEVERITIES:
            raise ValueError(
                f"Invalid severity '{self.severity}'. "
                f"Must be one of: {', '.join(sorted(self.VALID_SEVERITIES))}"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create an Event instance from a dictionary, with validation.

        This method validates that all required fields are present and have
        valid values before constructing the Event.

        Args:
            data: Dictionary containing event data.

        Returns:
            An Event instance constructed from the provided data.

        Raises:
            ValueError: If a required field is missing or if severity is invalid.
            TypeError: If data is not a dictionary.
        """
        if not isinstance(data, dict):
            raise ValueError(f"Expected dict, got {type(data).__name__}")

        required_fields = {
            "id",
            "title",
            "source",
            "timestamp",
            "category",
            "severity",
            "summary",
        }
        missing_fields = required_fields - set(data.keys())

        if missing_fields:
            raise ValueError(
                f"Missing required field(s): {', '.join(sorted(missing_fields))}"
            )

        # Extract the required fields
        event_data = {field: data[field] for field in required_fields}

        # Create the instance - __post_init__ will validate severity
        return cls(**event_data)

"""Unit tests for Event schema.

Tests the Event dataclass and its from_dict validation method.
"""

import pytest
from schemas.event_schema import Event


class TestEventCreation:
    """Tests for direct Event creation and initialization."""

    def test_valid_event_creation(self):
        """Test that a valid event can be created with all required fields."""
        event = Event(
            id="evt-001",
            title="Application Error",
            source="web-server-1",
            timestamp="2026-06-01T13:30:00Z",
            category="error",
            severity="high",
            summary="Database connection timeout",
        )

        assert event.id == "evt-001"
        assert event.title == "Application Error"
        assert event.source == "web-server-1"
        assert event.timestamp == "2026-06-01T13:30:00Z"
        assert event.category == "error"
        assert event.severity == "high"
        assert event.summary == "Database connection timeout"

    def test_valid_event_low_severity(self):
        """Test creation with low severity."""
        event = Event(
            id="evt-002",
            title="Info Log",
            source="app",
            timestamp="2026-06-01T13:31:00Z",
            category="info",
            severity="low",
            summary="Routine task completed",
        )
        assert event.severity == "low"

    def test_valid_event_medium_severity(self):
        """Test creation with medium severity."""
        event = Event(
            id="evt-003",
            title="Warning",
            source="app",
            timestamp="2026-06-01T13:32:00Z",
            category="warning",
            severity="medium",
            summary="Elevated memory usage",
        )
        assert event.severity == "medium"

    def test_invalid_severity_raises_error(self):
        """Test that an invalid severity value raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            Event(
                id="evt-004",
                title="Bad Severity",
                source="app",
                timestamp="2026-06-01T13:33:00Z",
                category="error",
                severity="critical",  # Invalid - not in {low, medium, high}
                summary="This should fail",
            )
        assert "Invalid severity" in str(excinfo.value)
        assert "critical" in str(excinfo.value)

    def test_invalid_severity_empty_string(self):
        """Test that an empty string severity raises ValueError."""
        with pytest.raises(ValueError) as excinfo:
            Event(
                id="evt-005",
                title="Empty Severity",
                source="app",
                timestamp="2026-06-01T13:34:00Z",
                category="error",
                severity="",
                summary="This should fail",
            )
        assert "Invalid severity" in str(excinfo.value)


class TestEventFromDict:
    """Tests for Event.from_dict() classmethod."""

    def test_valid_event_from_dict(self):
        """Test that a valid dictionary creates an Event successfully."""
        data = {
            "id": "evt-101",
            "title": "System Alert",
            "source": "monitor",
            "timestamp": "2026-06-01T14:00:00Z",
            "category": "alert",
            "severity": "high",
            "summary": "CPU usage exceeded threshold",
        }
        event = Event.from_dict(data)

        assert event.id == "evt-101"
        assert event.title == "System Alert"
        assert event.source == "monitor"
        assert event.timestamp == "2026-06-01T14:00:00Z"
        assert event.category == "alert"
        assert event.severity == "high"
        assert event.summary == "CPU usage exceeded threshold"

    def test_missing_required_field_id(self):
        """Test that missing 'id' field raises ValueError."""
        data = {
            "title": "Missing ID",
            "source": "app",
            "timestamp": "2026-06-01T14:01:00Z",
            "category": "error",
            "severity": "high",
            "summary": "Test summary",
        }
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(data)
        assert "Missing required field" in str(excinfo.value)
        assert "id" in str(excinfo.value)

    def test_missing_required_field_title(self):
        """Test that missing 'title' field raises ValueError."""
        data = {
            "id": "evt-201",
            "source": "app",
            "timestamp": "2026-06-01T14:02:00Z",
            "category": "error",
            "severity": "medium",
            "summary": "Test summary",
        }
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(data)
        assert "Missing required field" in str(excinfo.value)
        assert "title" in str(excinfo.value)

    def test_missing_required_field_source(self):
        """Test that missing 'source' field raises ValueError."""
        data = {
            "id": "evt-202",
            "title": "No Source",
            "timestamp": "2026-06-01T14:03:00Z",
            "category": "error",
            "severity": "high",
            "summary": "Test summary",
        }
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(data)
        assert "Missing required field" in str(excinfo.value)
        assert "source" in str(excinfo.value)

    def test_missing_required_field_timestamp(self):
        """Test that missing 'timestamp' field raises ValueError."""
        data = {
            "id": "evt-203",
            "title": "No Timestamp",
            "source": "app",
            "category": "error",
            "severity": "high",
            "summary": "Test summary",
        }
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(data)
        assert "Missing required field" in str(excinfo.value)
        assert "timestamp" in str(excinfo.value)

    def test_missing_required_field_category(self):
        """Test that missing 'category' field raises ValueError."""
        data = {
            "id": "evt-204",
            "title": "No Category",
            "source": "app",
            "timestamp": "2026-06-01T14:04:00Z",
            "severity": "high",
            "summary": "Test summary",
        }
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(data)
        assert "Missing required field" in str(excinfo.value)
        assert "category" in str(excinfo.value)

    def test_missing_required_field_severity(self):
        """Test that missing 'severity' field raises ValueError."""
        data = {
            "id": "evt-205",
            "title": "No Severity",
            "source": "app",
            "timestamp": "2026-06-01T14:05:00Z",
            "category": "error",
            "summary": "Test summary",
        }
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(data)
        assert "Missing required field" in str(excinfo.value)
        assert "severity" in str(excinfo.value)

    def test_missing_required_field_summary(self):
        """Test that missing 'summary' field raises ValueError."""
        data = {
            "id": "evt-206",
            "title": "No Summary",
            "source": "app",
            "timestamp": "2026-06-01T14:06:00Z",
            "category": "error",
            "severity": "high",
        }
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(data)
        assert "Missing required field" in str(excinfo.value)
        assert "summary" in str(excinfo.value)

    def test_missing_multiple_required_fields(self):
        """Test that multiple missing fields are all reported."""
        data = {
            "id": "evt-207",
            "title": "Multiple Missing",
        }
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(data)
        error_msg = str(excinfo.value)
        assert "Missing required field" in error_msg
        # Should mention at least some missing fields
        assert any(field in error_msg for field in ["source", "timestamp", "category", "severity", "summary"])

    def test_invalid_severity_from_dict(self):
        """Test that invalid severity in dict raises ValueError."""
        data = {
            "id": "evt-208",
            "title": "Bad Severity",
            "source": "app",
            "timestamp": "2026-06-01T14:07:00Z",
            "category": "error",
            "severity": "catastrophic",  # Invalid
            "summary": "Test summary",
        }
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(data)
        assert "Invalid severity" in str(excinfo.value)
        assert "catastrophic" in str(excinfo.value)

    def test_from_dict_with_non_dict_input(self):
        """Test that from_dict raises ValueError when given non-dict input."""
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict("not a dict")
        assert "Expected dict" in str(excinfo.value)

    def test_from_dict_with_list_input(self):
        """Test that from_dict raises ValueError when given a list."""
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict([1, 2, 3])
        assert "Expected dict" in str(excinfo.value)

    def test_from_dict_with_none_input(self):
        """Test that from_dict raises ValueError when given None."""
        with pytest.raises(ValueError) as excinfo:
            Event.from_dict(None)
        assert "Expected dict" in str(excinfo.value)

    def test_from_dict_allows_extra_fields(self):
        """Test that from_dict ignores extra fields not in the schema."""
        data = {
            "id": "evt-209",
            "title": "Extra Fields",
            "source": "app",
            "timestamp": "2026-06-01T14:08:00Z",
            "category": "error",
            "severity": "high",
            "summary": "Test summary",
            "extra_field_1": "ignored",
            "extra_field_2": 12345,
        }
        event = Event.from_dict(data)
        assert event.id == "evt-209"
        assert not hasattr(event, "extra_field_1")

    def test_from_dict_with_all_severity_levels(self):
        """Test that all valid severity levels work in from_dict."""
        for severity in ["low", "medium", "high"]:
            data = {
                "id": f"evt-{severity}",
                "title": f"Event with {severity} severity",
                "source": "app",
                "timestamp": "2026-06-01T14:09:00Z",
                "category": "test",
                "severity": severity,
                "summary": "Test summary",
            }
            event = Event.from_dict(data)
            assert event.severity == severity

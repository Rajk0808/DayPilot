"""Provider-independent calendar interface consumed by DayPilot callers."""

from datetime import datetime
from typing import Protocol, runtime_checkable

from daypilot.domain.times import CalendarEvent


@runtime_checkable
class CalendarIntegration(Protocol):
    """CRUD operations over domain calendar events from an external calendar."""

    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        """Fetch events overlapping the requested time range."""

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        """Create an external event from a DayPilot event."""

    def update_event(self, event: CalendarEvent) -> CalendarEvent:
        """Update the external event identified by ``event.id``."""

    def delete_event(self, event_id: str) -> None:
        """Delete the external event identified by its DayPilot ID."""

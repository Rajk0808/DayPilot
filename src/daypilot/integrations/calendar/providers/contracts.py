"""Provider-client contract and DTO used only inside integration adapters."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, Sequence, runtime_checkable


@dataclass(frozen=True)
class ProviderCalendarEvent:
    """Provider-shaped event data that never crosses into domain/application."""

    id: str
    title: str
    start: datetime
    end: datetime
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class CalendarProvider(Protocol):
    """Small client contract implemented by a concrete external provider."""

    def list_events(self, start: datetime, end: datetime) -> Sequence[ProviderCalendarEvent]: ...

    def create_event(self, event: ProviderCalendarEvent) -> ProviderCalendarEvent: ...

    def update_event(
        self, event_id: str, event: ProviderCalendarEvent
    ) -> ProviderCalendarEvent: ...

    def delete_event(self, event_id: str) -> None: ...

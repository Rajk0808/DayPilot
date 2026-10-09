"""Fake provider implementation used for local development and tests."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Sequence

from daypilot.integrations.calendar.providers.contracts import (
    ProviderCalendarEvent,
)


class InMemoryCalendarProvider:
    """Deterministic, credential-free provider client for tests and demos."""

    def __init__(self, events: Sequence[ProviderCalendarEvent] = ()) -> None:
        self._events: dict[str, ProviderCalendarEvent] = {}
        for event in events:
            if event.id in self._events:
                raise ValueError(f"Duplicate provider event ID {event.id!r}.")
            self._events[event.id] = deepcopy(event)

    def list_events(self, start: datetime, end: datetime) -> list[ProviderCalendarEvent]:
        return [
            deepcopy(event)
            for event in self._events.values()
            if event.start < end and event.end > start
        ]

    def create_event(self, event: ProviderCalendarEvent) -> ProviderCalendarEvent:
        if event.id in self._events:
            raise KeyError(f"Provider event {event.id!r} already exists.")
        self._events[event.id] = deepcopy(event)
        return deepcopy(self._events[event.id])

    def update_event(
        self, event_id: str, event: ProviderCalendarEvent
    ) -> ProviderCalendarEvent:
        if event_id not in self._events:
            raise KeyError(f"Provider event {event_id!r} does not exist.")
        if event.id != event_id:
            raise ValueError("Updated provider event ID must match the target ID.")
        self._events[event_id] = deepcopy(event)
        return deepcopy(self._events[event_id])

    def delete_event(self, event_id: str) -> None:
        if event_id not in self._events:
            raise KeyError(f"Provider event {event_id!r} does not exist.")
        del self._events[event_id]

    def get_event(self, event_id: str) -> ProviderCalendarEvent:
        """Inspect the fake provider's stored DTO in tests."""
        return deepcopy(self._events[event_id])

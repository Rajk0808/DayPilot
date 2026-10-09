"""Map provider events to DayPilot and contain provider failures."""

from copy import deepcopy
from datetime import datetime

from daypilot.domain.times import CalendarEvent, TimeWindow
from daypilot.integrations.calendar.errors import CalendarIntegrationError
from daypilot.integrations.calendar.ports import CalendarIntegration
from daypilot.integrations.calendar.providers.contracts import (
    CalendarProvider,
    ProviderCalendarEvent,
)


class CalendarProviderAdapter(CalendarIntegration):
    """Adapt a provider client to DayPilot's provider-neutral calendar port."""

    def __init__(self, provider: CalendarProvider) -> None:
        self._provider = provider

    def fetch_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        time_range = TimeWindow(start, end)
        try:
            provider_events = self._provider.list_events(time_range.start, time_range.end)
            return [self._to_domain(event) for event in provider_events]
        except Exception as exc:
            raise CalendarIntegrationError("fetch_events") from exc

    def create_event(self, event: CalendarEvent) -> CalendarEvent:
        provider_event = self._to_provider(event)
        try:
            created = self._provider.create_event(provider_event)
            return self._to_domain(created)
        except Exception as exc:
            raise CalendarIntegrationError("create_event") from exc

    def update_event(self, event: CalendarEvent) -> CalendarEvent:
        provider_event = self._to_provider(event)
        try:
            updated = self._provider.update_event(event.id, provider_event)
            return self._to_domain(updated)
        except Exception as exc:
            raise CalendarIntegrationError("update_event") from exc

    def delete_event(self, event_id: str) -> None:
        try:
            self._provider.delete_event(event_id)
        except Exception as exc:
            raise CalendarIntegrationError("delete_event") from exc

    @staticmethod
    def _to_domain(event: ProviderCalendarEvent) -> CalendarEvent:
        if not isinstance(event, ProviderCalendarEvent):
            raise TypeError("Provider returned an unsupported event DTO")
        return CalendarEvent(
            id=event.id,
            title=event.title,
            start=event.start,
            end=event.end,
            metadata=deepcopy(event.metadata),
        )

    @staticmethod
    def _to_provider(event: CalendarEvent) -> ProviderCalendarEvent:
        if not isinstance(event, CalendarEvent):
            raise TypeError("event must be a DayPilot CalendarEvent")
        return ProviderCalendarEvent(
            id=event.id,
            title=event.title,
            start=event.start,
            end=event.end,
            metadata=deepcopy(event.metadata),
        )

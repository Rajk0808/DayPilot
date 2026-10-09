from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daypilot.domain.times import CalendarEvent
from daypilot.integrations.calendar import (
    CalendarIntegration,
    CalendarIntegrationError,
    CalendarProviderAdapter,
)
from daypilot.integrations.calendar.providers.in_memory import (
    InMemoryCalendarProvider,
    ProviderCalendarEvent,
)

START = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)
END = START + timedelta(hours=1)


def provider_event(event_id="event-1", start=START, end=END, **kwargs):
    return ProviderCalendarEvent(
        id=event_id,
        title=kwargs.get("title", "Provider meeting"),
        start=start,
        end=end,
        metadata=kwargs.get("metadata", {"room": "A"}),
    )


def test_provider_event_maps_to_domain_event_with_isolated_metadata():
    provider = InMemoryCalendarProvider([provider_event()])
    adapter = CalendarProviderAdapter(provider)

    events = adapter.fetch_events(START, END)

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, CalendarEvent)
    assert (event.id, event.title, event.start, event.end) == (
        "event-1",
        "Provider meeting",
        START,
        END,
    )
    assert event.metadata == {"room": "A"}
    assert event.metadata is not provider.get_event("event-1").metadata
    event.metadata["room"] = "changed in domain"
    assert provider.get_event("event-1").metadata == {"room": "A"}


def test_calendar_event_maps_to_provider_dto_on_create():
    provider = InMemoryCalendarProvider()
    adapter = CalendarProviderAdapter(provider)
    assert isinstance(adapter, CalendarIntegration)
    event = CalendarEvent("new-event", "New meeting", START, END, {"room": "B"})

    created = adapter.create_event(event)
    stored = provider.get_event("new-event")

    assert created == event
    assert isinstance(stored, ProviderCalendarEvent)
    assert stored.id == event.id
    assert stored.title == event.title
    assert stored.start == event.start
    assert stored.end == event.end
    assert stored.metadata == event.metadata
    assert stored.metadata is not event.metadata


def test_fetch_events_only_returns_events_intersecting_requested_range():
    provider = InMemoryCalendarProvider(
        [
            provider_event("before", START - timedelta(hours=2), START - timedelta(hours=1)),
            provider_event("overlap", START - timedelta(minutes=15), START + timedelta(minutes=15)),
            provider_event("after", END + timedelta(hours=1), END + timedelta(hours=2)),
        ]
    )

    events = CalendarProviderAdapter(provider).fetch_events(START, END)

    assert [event.id for event in events] == ["overlap"]


def test_update_event_maps_domain_changes_to_provider_dto():
    provider = InMemoryCalendarProvider([provider_event()])
    adapter = CalendarProviderAdapter(provider)
    changed = CalendarEvent(
        "event-1",
        "Updated title",
        START + timedelta(minutes=5),
        END + timedelta(minutes=5),
        {"room": "C"},
    )

    updated = adapter.update_event(changed)

    assert updated == changed
    assert provider.get_event("event-1") == ProviderCalendarEvent(
        id="event-1",
        title="Updated title",
        start=changed.start,
        end=changed.end,
        metadata={"room": "C"},
    )


def test_delete_event_removes_provider_event():
    provider = InMemoryCalendarProvider([provider_event()])
    adapter = CalendarProviderAdapter(provider)

    adapter.delete_event("event-1")

    assert adapter.fetch_events(START, END) == []


def test_provider_failures_are_wrapped_at_the_integration_boundary():
    class BrokenProvider:
        def list_events(self, start, end):
            raise ConnectionError("provider unavailable")

        def create_event(self, event):
            raise ConnectionError("provider unavailable")

        def update_event(self, event_id, event):
            raise ConnectionError("provider unavailable")

        def delete_event(self, event_id):
            raise ConnectionError("provider unavailable")

    adapter = CalendarProviderAdapter(BrokenProvider())

    with pytest.raises(CalendarIntegrationError) as caught:
        adapter.fetch_events(START, END)

    assert caught.value.operation == "fetch_events"
    assert isinstance(caught.value.__cause__, ConnectionError)


def test_domain_and_application_sources_do_not_depend_on_provider_dtos():
    source_root = Path(__file__).parents[2] / "src" / "daypilot"
    forbidden_names = (
        "ProviderCalendarEvent",
        "InMemoryCalendarProvider",
        "daypilot.integrations.calendar.providers",
    )
    for layer in ("domain", "application"):
        for source in (source_root / layer).rglob("*.py"):
            contents = source.read_text(encoding="utf-8")
            assert not any(name in contents for name in forbidden_names), source

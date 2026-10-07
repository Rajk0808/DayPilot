from datetime import datetime, timedelta, timezone

from daypilot.domain.times import CalendarEvent
from daypilot.persistence.mappers.times import from_record, to_record
from daypilot.persistence.models.times import CalendarEventRecord


def test_to_record_stores_utc_timestamp_microseconds_and_copied_metadata():
    event = CalendarEvent(
        id="event-1",
        title="Meeting",
        start=datetime(2030, 1, 2, 0, 0, 0, 125_000, tzinfo=timezone.utc),
        end=datetime(2030, 1, 2, 1, 0, 0, 875_000, tzinfo=timezone.utc),
        metadata={"source": "calendar"},
    )

    record = to_record(event)

    assert isinstance(record, CalendarEventRecord)
    assert record.start_timestamp_microseconds == 1_893_542_400_125_000
    assert record.end_timestamp_microseconds == 1_893_546_000_875_000
    assert record.metadata == event.metadata
    assert record.metadata is not event.metadata


def test_from_record_restores_utc_datetimes_and_metadata():
    record = CalendarEventRecord(
        id="event-1",
        title="Meeting",
        start_timestamp_microseconds=1_893_542_400_125_000,
        end_timestamp_microseconds=1_893_546_000_875_000,
        metadata={"source": "calendar"},
    )

    event = from_record(record)

    assert event.start == datetime(2030, 1, 2, 0, 0, 0, 125_000, tzinfo=timezone.utc)
    assert event.end == datetime(2030, 1, 2, 1, 0, 0, 875_000, tzinfo=timezone.utc)
    assert event.start.tzinfo is timezone.utc
    assert event.end.tzinfo is timezone.utc
    assert event.metadata == record.metadata
    assert event.metadata is not record.metadata


def test_calendar_event_round_trip_preserves_subsecond_precision():
    start = datetime(2026, 10, 7, 9, 30, 0, 123_456, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    end = start + timedelta(minutes=30, microseconds=654_321)
    event = CalendarEvent("event-1", "Meeting", start, end)

    restored = from_record(to_record(event))

    assert restored.start == event.start
    assert restored.end == event.end

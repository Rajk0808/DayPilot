from daypilot.domain.times import CalendarEvent
from daypilot.persistence.models.times import CalendarEventRecord
from daypilot.persistence.time_utils import (
    datetime_to_timestamp_microseconds,
    timestamp_microseconds_to_datetime,
)


def to_record(calendar_event: CalendarEvent) -> CalendarEventRecord:
    """Convert a DayPilot calendar event to a persistence record."""
    return CalendarEventRecord(
        id=calendar_event.id,
        title=calendar_event.title,
        start_timestamp_microseconds=datetime_to_timestamp_microseconds(calendar_event.start),
        end_timestamp_microseconds=datetime_to_timestamp_microseconds(calendar_event.end),
        metadata=dict(calendar_event.metadata),
    )


def from_record(record: CalendarEventRecord) -> CalendarEvent:
    """Convert a persistence record to a UTC-normalized calendar event."""
    return CalendarEvent(
        id=record.id,
        title=record.title,
        start=timestamp_microseconds_to_datetime(record.start_timestamp_microseconds),
        end=timestamp_microseconds_to_datetime(record.end_timestamp_microseconds),
        metadata=dict(record.metadata),
    )

"""Mapping between ``CalendarEventRecord`` and its ORM row."""

from daypilot.persistence.models.times import CalendarEventRecord
from daypilot.persistence.orm.calendar_event import CalendarEventORM


def to_orm(record: CalendarEventRecord, state_id: str) -> CalendarEventORM:
    """Create an event row using the supplied aggregate state ID."""
    if not isinstance(record, CalendarEventRecord):
        raise TypeError("record must be a CalendarEventRecord")
    if not isinstance(state_id, str) or not state_id:
        raise ValueError("state_id must be a non-empty string")
    return CalendarEventORM(
        state_id=state_id,
        id=record.id,
        title=record.title,
        start_timestamp_microseconds=record.start_timestamp_microseconds,
        end_timestamp_microseconds=record.end_timestamp_microseconds,
        metadata_json=dict(record.metadata),
    )


def from_orm(orm: CalendarEventORM) -> CalendarEventRecord:
    """Create an event record from its scalar ORM row fields."""
    if not isinstance(orm, CalendarEventORM):
        raise TypeError("orm must be a CalendarEventORM")
    return CalendarEventRecord(
        id=orm.id,
        title=orm.title,
        start_timestamp_microseconds=orm.start_timestamp_microseconds,
        end_timestamp_microseconds=orm.end_timestamp_microseconds,
        metadata=dict(orm.metadata_json),
    )

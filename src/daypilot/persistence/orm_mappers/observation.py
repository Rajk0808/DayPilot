"""Mapping between observation records and ORM rows."""

from daypilot.persistence.models.observation import ObservationRecord
from daypilot.persistence.orm.observation import ObservationORM


def to_orm(record: ObservationRecord, state_id: str) -> ObservationORM:
    """Create an observation row using the supplied aggregate state ID."""
    if not isinstance(record, ObservationRecord):
        raise TypeError("record must be an ObservationRecord")
    if not isinstance(state_id, str) or not state_id:
        raise ValueError("state_id must be a non-empty string")
    return ObservationORM(
        state_id=state_id,
        id=record.id,
        task_id=record.task_id,
        schedule_block_id=record.schedule_block_id,
        actual_start_timestamp_microseconds=record.actual_start_timestamp_microseconds,
        actual_end_timestamp_microseconds=record.actual_end_timestamp_microseconds,
        outcome=record.outcome,
        metadata_json=dict(record.metadata),
    )


def from_orm(orm: ObservationORM) -> ObservationRecord:
    """Create an observation record from its persisted row values."""
    if not isinstance(orm, ObservationORM):
        raise TypeError("orm must be an ObservationORM")
    return ObservationRecord(
        id=orm.id,
        task_id=orm.task_id,
        schedule_block_id=orm.schedule_block_id,
        actual_start_timestamp_microseconds=orm.actual_start_timestamp_microseconds,
        actual_end_timestamp_microseconds=orm.actual_end_timestamp_microseconds,
        outcome=orm.outcome,
        metadata=dict(orm.metadata_json),
    )

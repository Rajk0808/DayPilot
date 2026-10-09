"""Mapping between schedule-block records and ORM rows."""

from daypilot.persistence.models.schedule import ScheduleBlockRecord
from daypilot.persistence.orm.schedule_block import ScheduleBlockORM


def to_orm(
    record: ScheduleBlockRecord,
    state_id: str,
    *,
    plan_id: str | None = None,
) -> ScheduleBlockORM:
    """Create a block row; plan membership is supplied as relation context."""
    if not isinstance(record, ScheduleBlockRecord):
        raise TypeError("record must be a ScheduleBlockRecord")
    if not isinstance(state_id, str) or not state_id:
        raise ValueError("state_id must be a non-empty string")
    if plan_id is not None and (not isinstance(plan_id, str) or not plan_id):
        raise ValueError("plan_id must be None or a non-empty string")
    return ScheduleBlockORM(
        state_id=state_id,
        id=record.id,
        task_id=record.task_id,
        plan_id=plan_id,
        start_timestamp_microseconds=record.start_timestamp_microseconds,
        end_timestamp_microseconds=record.end_timestamp_microseconds,
    )


def from_orm(orm: ScheduleBlockORM) -> ScheduleBlockRecord:
    """Create a block record; plan membership is reconstructed separately."""
    if not isinstance(orm, ScheduleBlockORM):
        raise TypeError("orm must be a ScheduleBlockORM")
    return ScheduleBlockRecord(
        id=orm.id,
        task_id=orm.task_id,
        start_timestamp_microseconds=orm.start_timestamp_microseconds,
        end_timestamp_microseconds=orm.end_timestamp_microseconds,
    )

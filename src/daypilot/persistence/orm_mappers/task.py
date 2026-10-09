"""Mapping between ``TaskRecord`` and its aggregate-scoped ORM row."""

from collections.abc import Iterable

from daypilot.persistence.models.task import TaskRecord
from daypilot.persistence.orm.task import TaskORM


def to_orm(record: TaskRecord, state_id: str) -> TaskORM:
    """Create a task ORM row from a record and its owning state ID.

    ``children_ids`` is deliberately omitted: the relational hierarchy is
    stored once in each child's ``parent_task_id`` column.
    """
    if not isinstance(record, TaskRecord):
        raise TypeError("record must be a TaskRecord.")
    if not isinstance(state_id, str) or not state_id:
        raise ValueError("state_id must be a non-empty string.")

    return TaskORM(
        state_id=state_id,
        id=record.id,
        title=record.title,
        description=record.description,
        status=record.status,
        scheduling_status=record.scheduling_status,
        priority=record.priority,
        estimated_duration_microseconds=record.estimated_duration_microseconds,
        deadline_timestamp_microseconds=record.deadline_timestamp_microseconds,
        metadata_json=dict(record.metadata),
        parent_task_id=record.parent_id,
    )


def from_orm(orm: TaskORM, *, children_ids: Iterable[str] = ()) -> TaskRecord:
    """Create a record, with child IDs supplied by collection-level mapping."""
    if not isinstance(orm, TaskORM):
        raise TypeError("orm must be a TaskORM.")

    return TaskRecord(
        id=orm.id,
        title=orm.title,
        description=orm.description,
        status=orm.status,
        scheduling_status=orm.scheduling_status,
        priority=orm.priority,
        estimated_duration_microseconds=orm.estimated_duration_microseconds,
        deadline_timestamp_microseconds=orm.deadline_timestamp_microseconds,
        metadata=dict(orm.metadata_json),
        parent_id=orm.parent_task_id,
        children_ids=list(children_ids),
    )

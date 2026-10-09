"""Mapping between ``GoalRecord`` and its aggregate-scoped ORM row."""

from collections.abc import Iterable

from daypilot.persistence.models.goal import GoalRecord
from daypilot.persistence.orm.goal import GoalORM


def to_orm(record: GoalRecord, state_id: str) -> GoalORM:
    """Create a goal ORM row from scalar record fields and its owning state ID.

    Root task IDs are represented by ``GoalRootTaskORM`` association rows and
    are intentionally handled by the separate association mapper.
    """
    if not isinstance(record, GoalRecord):
        raise TypeError("record must be a GoalRecord.")
    if not isinstance(state_id, str) or not state_id:
        raise ValueError("state_id must be a non-empty string.")

    return GoalORM(
        state_id=state_id,
        id=record.id,
        title=record.title,
        description=record.description,
        deadline_timestamp_microseconds=record.deadline_timestamp_microseconds,
        status=record.status,
    )


def from_orm(orm: GoalORM, *, root_task_ids: Iterable[str] = ()) -> GoalRecord:
    """Create a goal record, with root task IDs supplied by collection mapping."""
    if not isinstance(orm, GoalORM):
        raise TypeError("orm must be a GoalORM.")

    return GoalRecord(
        id=orm.id,
        title=orm.title,
        description=orm.description,
        deadline_timestamp_microseconds=orm.deadline_timestamp_microseconds,
        status=orm.status,
        root_task_ids=list(root_task_ids),
    )

from daypilot.domain.goal import Goal
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.goal import GoalRecord
from daypilot.persistence.time_utils import (
    datetime_to_timestamp_microseconds,
    timestamp_microseconds_to_datetime,
)


def to_record(goal: Goal) -> GoalRecord:
    """Convert a DayPilot goal to a persistence record."""
    status = getattr(goal.status, "value", goal.status)
    return GoalRecord(
        id=goal.id,
        title=goal.title,
        description=goal.description,
        deadline_timestamp_microseconds=(
            datetime_to_timestamp_microseconds(goal.deadline)
            if goal.deadline is not None
            else None
        ),
        status=str(status),
        root_task_ids=[task.id for task in goal.root_tasks],
    )


def from_record(record: GoalRecord, task_mapping_context: TaskMappingContext) -> Goal:
    """Convert a persistence record using the canonical tasks in the identity map."""
    root_ids = record.root_task_ids
    if len(root_ids) != len(set(root_ids)):
        raise ValueError("Goal record contains duplicate root task IDs.")

    missing_ids = [task_id for task_id in root_ids if task_id not in task_mapping_context.tasks]
    if missing_ids:
        raise ValueError(f"Goal record references missing root task ID {missing_ids[0]!r}.")

    goal = Goal(
        id=record.id,
        title=record.title,
        description=record.description,
        deadline=(
            timestamp_microseconds_to_datetime(record.deadline_timestamp_microseconds)
            if record.deadline_timestamp_microseconds is not None
            else None
        ),
        status=record.status,
    )
    for task_id in root_ids:
        goal.add_root_task(task_mapping_context.tasks[task_id])
    return goal

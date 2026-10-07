from datetime import datetime, timezone

import pytest

from daypilot.domain.enums import TaskStatus
from daypilot.domain.goal import Goal
from daypilot.persistence.mappers.goal import from_record, to_record
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.goal import GoalRecord
from daypilot.persistence.models.task import TaskRecord


def task_record(task_id="root"):
    return TaskRecord(
        id=task_id,
        title=task_id,
        description="",
        status="not_started",
        scheduling_status="unscheduled",
        priority=None,
        estimated_duration_microseconds=0,
        deadline_timestamp_microseconds=None,
        metadata={},
        parent_id=None,
        children_ids=[],
    )


def goal_record(*, root_task_ids=None, deadline_timestamp_microseconds=None):
    return GoalRecord(
        id="goal",
        title="Goal",
        description="Description",
        deadline_timestamp_microseconds=deadline_timestamp_microseconds,
        status="in_progress",
        root_task_ids=root_task_ids or [],
    )


def test_to_record_serializes_enum_value_and_preserves_deadline_microseconds():
    deadline = datetime(2030, 1, 2, 0, 0, 0, 500_000, tzinfo=timezone.utc)
    goal = Goal(
        id="goal",
        title="Goal",
        deadline=deadline,
        status=TaskStatus.IN_PROGRESS,
    )

    record = to_record(goal)

    assert record.status == TaskStatus.IN_PROGRESS.value
    assert record.deadline_timestamp_microseconds == 1_893_542_400_500_000


def test_from_record_uses_canonical_tasks_and_restores_utc_deadline():
    context = TaskMappingContext()
    task = context.reconstruct([task_record()])["root"]
    record = goal_record(
        root_task_ids=["root"],
        deadline_timestamp_microseconds=1_893_542_400_500_000,
    )

    goal = from_record(record, context)

    assert goal.root_tasks[0] is task
    assert goal.deadline == datetime(2030, 1, 2, 0, 0, 0, 500_000, tzinfo=timezone.utc)
    assert goal.deadline.tzinfo is timezone.utc
    assert goal.status == "in_progress"


def test_from_record_rejects_missing_root_task_id():
    with pytest.raises(ValueError, match="missing root task ID"):
        from_record(goal_record(root_task_ids=["missing"]), TaskMappingContext())


def test_from_record_rejects_duplicate_root_task_ids():
    context = TaskMappingContext()
    context.reconstruct([task_record()])

    with pytest.raises(ValueError, match="duplicate root task IDs"):
        from_record(goal_record(root_task_ids=["root", "root"]), context)

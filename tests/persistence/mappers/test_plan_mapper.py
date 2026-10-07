from datetime import datetime, timedelta, timezone

from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task
from daypilot.persistence.mappers.plan import from_record, to_record
from daypilot.persistence.mappers.schedule_block import to_record as block_to_record
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.task import TaskRecord


def test_plan_round_trip_resolves_schedule_block_task_and_preserves_precision():
    start = datetime(2030, 1, 2, 0, 0, 0, 250_000, tzinfo=timezone.utc)
    task = Task("task", "Task")
    block = ScheduleBlock(task, start, start + timedelta(minutes=30))
    plan = Plan("plan", start, timedelta(days=1, microseconds=5), [block], {"source": "test"})
    plan_record = to_record(plan)
    block_record = block_to_record(block)
    context = TaskMappingContext()
    context.reconstruct([TaskRecord(
        "task", "Task", "", "not_started", "unscheduled", None,
        0, None, {}, None, [],
    )])

    restored = from_record(plan_record, context, {block_record.id: block_record})

    assert restored.id == "plan"
    assert restored.date == start
    assert restored.planning_horizon == timedelta(days=1, microseconds=5)
    assert restored.schedule_blocks[0].task is context.tasks["task"]
    assert restored.metadata == plan.metadata

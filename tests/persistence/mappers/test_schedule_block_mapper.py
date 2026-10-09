from datetime import datetime, timezone

from daypilot.domain.schedule import ScheduleBlock
from daypilot.domain.task import Task
from daypilot.persistence.mappers.schedule_block import from_record, to_record
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.task import TaskRecord


def test_schedule_block_maps_task_id_and_utc_microseconds():
    task = Task("task", "Task")
    block = ScheduleBlock(
        task,
        datetime(2030, 1, 2, 9, 0, 0, 123_456, tzinfo=timezone.utc),
        datetime(2030, 1, 2, 10, 0, 0, 654_321, tzinfo=timezone.utc),
    )
    record = to_record(block)
    context = TaskMappingContext()
    context.reconstruct([TaskRecord(
        "task", "Task", "", "not_started", "unscheduled", None,
        0, None, {}, None, [],
    )])

    restored = from_record(record, context)

    assert record.task_id == "task"
    assert not hasattr(record, "status")
    assert not hasattr(restored, "status")
    assert restored.task is context.tasks["task"]
    assert restored.start == block.start
    assert restored.end == block.end

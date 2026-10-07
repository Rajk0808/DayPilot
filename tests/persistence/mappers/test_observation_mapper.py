from datetime import datetime, timedelta, timezone

from daypilot.domain.enums import ObservationOutcome
from daypilot.domain.observation import Observation
from daypilot.domain.schedule import ScheduleBlock
from daypilot.domain.task import Task
from daypilot.persistence.mappers.observation import from_record, to_record
from daypilot.persistence.mappers.schedule_block import to_record as block_to_record
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.task import TaskRecord


def test_observation_round_trip_uses_canonical_task_and_block():
    start = datetime(2030, 1, 2, 9, 0, tzinfo=timezone.utc)
    task = Task("task", "Task")
    block = ScheduleBlock(task, start, start + timedelta(hours=1))
    observation = Observation(
        task, block, start + timedelta(minutes=2), start + timedelta(minutes=58),
        ObservationOutcome.COMPLETED, {"note": "done"},
    )
    record = to_record(observation)
    block_record = block_to_record(block)
    context = TaskMappingContext()
    context.reconstruct([TaskRecord(
        "task", "Task", "", "not_started", "unscheduled", None,
        0, None, {}, None, [],
    )])

    restored = from_record(record, context, {block_record.id: block_record})

    assert restored.task is context.tasks["task"]
    assert restored.scheduled_block.task is restored.task
    assert restored.actual_start == observation.actual_start
    assert restored.actual_end == observation.actual_end
    assert restored.outcome is ObservationOutcome.COMPLETED
    assert restored.metadata == observation.metadata

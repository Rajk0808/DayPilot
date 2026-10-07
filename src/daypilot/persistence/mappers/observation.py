import json
from collections.abc import Mapping

from daypilot.domain.enums import ObservationOutcome
from daypilot.domain.observation import Observation
from daypilot.persistence.mappers.schedule_block import (
    ScheduleBlockMappingContext,
    from_record as block_from_record,
)
from daypilot.persistence.mappers.schedule_block import schedule_block_id
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.observation import ObservationRecord
from daypilot.persistence.models.schedule import ScheduleBlockRecord
from daypilot.persistence.time_utils import (
    datetime_to_timestamp_microseconds,
    timestamp_microseconds_to_datetime,
)


def observation_id(
    task_id: str,
    schedule_block_id_value: str,
    actual_start_timestamp_microseconds: int,
    actual_end_timestamp_microseconds: int,
) -> str:
    return json.dumps(
        [task_id, schedule_block_id_value, actual_start_timestamp_microseconds,
         actual_end_timestamp_microseconds],
        separators=(",", ":"),
    )


def to_record(observation: Observation) -> ObservationRecord:
    start = datetime_to_timestamp_microseconds(observation.actual_start)
    end = datetime_to_timestamp_microseconds(observation.actual_end)
    block_start = datetime_to_timestamp_microseconds(observation.scheduled_block.start)
    block_end = datetime_to_timestamp_microseconds(observation.scheduled_block.end)
    block_id = schedule_block_id(observation.task.id, block_start, block_end)
    return ObservationRecord(
        id=observation_id(observation.task.id, block_id, start, end),
        task_id=observation.task.id,
        schedule_block_id=block_id,
        actual_start_timestamp_microseconds=start,
        actual_end_timestamp_microseconds=end,
        outcome=observation.outcome.value,
        metadata=dict(observation.metadata),
    )


def from_record(
    record: ObservationRecord,
    task_mapping_context: TaskMappingContext,
    schedule_block_records: Mapping[str, ScheduleBlockRecord],
    schedule_block_context: ScheduleBlockMappingContext | None = None,
) -> Observation:
    task = task_mapping_context.tasks.get(record.task_id)
    if task is None:
        raise ValueError(f"Observation references missing task ID {record.task_id!r}.")
    block_record = schedule_block_records.get(record.schedule_block_id)
    if block_record is None:
        raise ValueError(
            f"Observation references missing schedule block ID {record.schedule_block_id!r}."
        )
    block = block_from_record(block_record, task_mapping_context, schedule_block_context)
    if block.task is not task:
        raise ValueError("Observation task and scheduled block must reference the same task.")
    expected_id = observation_id(
        record.task_id,
        record.schedule_block_id,
        record.actual_start_timestamp_microseconds,
        record.actual_end_timestamp_microseconds,
    )
    if record.id != expected_id:
        raise ValueError(f"Observation record ID {record.id!r} does not match its contents.")
    return Observation(
        task=task,
        scheduled_block=block,
        actual_start=timestamp_microseconds_to_datetime(record.actual_start_timestamp_microseconds),
        actual_end=timestamp_microseconds_to_datetime(record.actual_end_timestamp_microseconds),
        outcome=ObservationOutcome(record.outcome),
        metadata=dict(record.metadata),
    )

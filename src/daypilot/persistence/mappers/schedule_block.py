import json

from daypilot.domain.schedule import ScheduleBlock
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.schedule import ScheduleBlockRecord
from daypilot.persistence.time_utils import (
    datetime_to_timestamp_microseconds,
    timestamp_microseconds_to_datetime,
)


def schedule_block_id(task_id: str, start_timestamp_microseconds: int, end_timestamp_microseconds: int) -> str:
    """Return a stable key for a schedule block, which has no domain ID."""
    return json.dumps(
        [task_id, start_timestamp_microseconds, end_timestamp_microseconds],
        separators=(",", ":"),
    )


def to_record(block: ScheduleBlock) -> ScheduleBlockRecord:
    start = datetime_to_timestamp_microseconds(block.start)
    end = datetime_to_timestamp_microseconds(block.end)
    return ScheduleBlockRecord(
        id=schedule_block_id(block.task.id, start, end),
        task_id=block.task.id,
        start_timestamp_microseconds=start,
        end_timestamp_microseconds=end,
    )


def _map_record(record: ScheduleBlockRecord, task_mapping_context: TaskMappingContext) -> ScheduleBlock:
    task = task_mapping_context.tasks.get(record.task_id)
    if task is None:
        raise ValueError(f"Schedule block references missing task ID {record.task_id!r}.")
    expected_id = schedule_block_id(
        record.task_id,
        record.start_timestamp_microseconds,
        record.end_timestamp_microseconds,
    )
    if record.id != expected_id:
        raise ValueError(f"Schedule block record ID {record.id!r} does not match its contents.")
    return ScheduleBlock(
        task=task,
        start=timestamp_microseconds_to_datetime(record.start_timestamp_microseconds),
        end=timestamp_microseconds_to_datetime(record.end_timestamp_microseconds),
    )


class ScheduleBlockMappingContext:
    """Identity map that reuses schedule blocks across plans and observations."""

    def __init__(self) -> None:
        self.blocks: dict[str, ScheduleBlock] = {}
        self._records: dict[str, ScheduleBlockRecord] = {}

    def resolve(
        self,
        record: ScheduleBlockRecord,
        task_mapping_context: TaskMappingContext,
    ) -> ScheduleBlock:
        expected_id = schedule_block_id(
            record.task_id,
            record.start_timestamp_microseconds,
            record.end_timestamp_microseconds,
        )
        if record.id != expected_id:
            raise ValueError(f"Schedule block record ID {record.id!r} does not match its contents.")
        existing = self.blocks.get(record.id)
        if existing is not None:
            if self._records[record.id] != record:
                raise ValueError(f"Conflicting schedule block records use ID {record.id!r}.")
            return existing
        block = _map_record(record, task_mapping_context)
        self.blocks[record.id] = block
        self._records[record.id] = record
        return block


def from_record(
    record: ScheduleBlockRecord,
    task_mapping_context: TaskMappingContext,
    context: ScheduleBlockMappingContext | None = None,
) -> ScheduleBlock:
    if context is not None:
        return context.resolve(record, task_mapping_context)
    return _map_record(record, task_mapping_context)

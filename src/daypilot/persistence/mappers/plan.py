from datetime import timedelta
from collections.abc import Mapping

from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.persistence.mappers.schedule_block import (
    ScheduleBlockMappingContext,
    from_record as block_from_record,
)
from daypilot.persistence.mappers.schedule_block import to_record as block_to_record
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.plan import PlanRecord
from daypilot.persistence.models.schedule import ScheduleBlockRecord
from daypilot.persistence.time_utils import (
    datetime_to_timestamp_microseconds,
    timestamp_microseconds_to_datetime,
)


def to_record(plan: Plan) -> PlanRecord:
    block_records = [block_to_record(block) for block in plan.schedule_blocks]
    return PlanRecord(
        id=plan.id,
        date_timestamp_microseconds=datetime_to_timestamp_microseconds(plan.date),
        planning_horizon_microseconds=(
            (plan.planning_horizon.days * 86_400 + plan.planning_horizon.seconds) * 1_000_000
            + plan.planning_horizon.microseconds
        ),
        schedule_block_ids=[record.id for record in block_records],
        metadata=dict(plan.metadata),
    )


def from_record(
    record: PlanRecord,
    task_mapping_context: TaskMappingContext,
    schedule_block_records: Mapping[str, ScheduleBlockRecord],
    schedule_block_context: ScheduleBlockMappingContext | None = None,
) -> Plan:
    if len(record.schedule_block_ids) != len(set(record.schedule_block_ids)):
        raise ValueError("Plan record contains duplicate schedule block IDs.")
    missing = [block_id for block_id in record.schedule_block_ids if block_id not in schedule_block_records]
    if missing:
        raise ValueError(f"Plan record references missing schedule block ID {missing[0]!r}.")
    blocks: list[ScheduleBlock] = []
    for block_id in record.schedule_block_ids:
        block_record = schedule_block_records[block_id]
        if block_record.id != block_id:
            raise ValueError(f"Schedule block mapping key {block_id!r} does not match record ID.")
        blocks.append(
            block_from_record(block_record, task_mapping_context, schedule_block_context)
        )
    return Plan(
        id=record.id,
        date=timestamp_microseconds_to_datetime(record.date_timestamp_microseconds),
        planning_horizon=timedelta(microseconds=record.planning_horizon_microseconds),
        schedule_blocks=blocks,
        metadata=dict(record.metadata),
    )

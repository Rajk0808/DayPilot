"""Mapping between ``PlanRecord`` and its aggregate-scoped ORM row."""

from collections.abc import Iterable

from daypilot.persistence.models.plan import PlanRecord
from daypilot.persistence.orm.plan import PlanORM


def to_orm(record: PlanRecord, state_id: str) -> PlanORM:
    """Create a plan row; block associations are mapped separately."""
    if not isinstance(record, PlanRecord):
        raise TypeError("record must be a PlanRecord")
    if not isinstance(state_id, str) or not state_id:
        raise ValueError("state_id must be a non-empty string")
    return PlanORM(
        state_id=state_id,
        id=record.id,
        date_timestamp_microseconds=record.date_timestamp_microseconds,
        planning_horizon_microseconds=record.planning_horizon_microseconds,
        metadata_json=dict(record.metadata),
    )


def from_orm(
    orm: PlanORM,
    *,
    schedule_block_ids: Iterable[str] = (),
) -> PlanRecord:
    """Create a plan record with block IDs provided by collection mapping."""
    if not isinstance(orm, PlanORM):
        raise TypeError("orm must be a PlanORM")
    return PlanRecord(
        id=orm.id,
        date_timestamp_microseconds=orm.date_timestamp_microseconds,
        planning_horizon_microseconds=orm.planning_horizon_microseconds,
        schedule_block_ids=list(schedule_block_ids),
        metadata=dict(orm.metadata_json),
    )

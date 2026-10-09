"""Mapping between persistence-identified constraint records and ORM rows."""

from daypilot.persistence.models.constraint import ConstraintRecord
from daypilot.persistence.orm.constraint import ConstraintORM


def to_orm(record: ConstraintRecord, state_id: str) -> ConstraintORM:
    """Create a constraint row, preserving its persistence-owned UUID."""
    if not isinstance(record, ConstraintRecord):
        raise TypeError("record must be a ConstraintRecord")
    if not isinstance(state_id, str) or not state_id:
        raise ValueError("state_id must be a non-empty string")
    return ConstraintORM(
        state_id=state_id,
        constraint_id=record.constraint_id,
        type=record.type,
        start_timestamp_microseconds=record.rule_information_start_timestamp_microseconds,
        end_timestamp_microseconds=record.rule_information_end_timestamp_microseconds,
        description=record.description,
    )


def from_orm(orm: ConstraintORM) -> ConstraintRecord:
    """Create a constraint record, retaining the ORM's stable UUID identity."""
    if not isinstance(orm, ConstraintORM):
        raise TypeError("orm must be a ConstraintORM")
    return ConstraintRecord(
        constraint_id=orm.constraint_id,
        type=orm.type,
        rule_information_start_timestamp_microseconds=orm.start_timestamp_microseconds,
        rule_information_end_timestamp_microseconds=orm.end_timestamp_microseconds,
        description=orm.description,
    )

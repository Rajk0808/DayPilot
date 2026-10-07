from daypilot.domain.enums import ConstraintType
from daypilot.domain.times import Constraint, TimeWindow
from daypilot.persistence.models.constraint import ConstraintRecord
from daypilot.persistence.time_utils import (
    datetime_to_timestamp_microseconds,
    timestamp_microseconds_to_datetime,
)


def to_record(constraint: Constraint) -> ConstraintRecord:
    """Convert a DayPilot constraint to a persistence record."""
    return ConstraintRecord(
        type=constraint.type.value,
        rule_information_start_timestamp_microseconds=(
            datetime_to_timestamp_microseconds(constraint.rule_information.start)
        ),
        rule_information_end_timestamp_microseconds=(
            datetime_to_timestamp_microseconds(constraint.rule_information.end)
        ),
        description=constraint.description,
    )


def from_record(record: ConstraintRecord) -> Constraint:
    """Convert a persistence record to a domain constraint."""
    return Constraint(
        type=ConstraintType(record.type),
        rule_information=TimeWindow(
            timestamp_microseconds_to_datetime(
                record.rule_information_start_timestamp_microseconds
            ),
            timestamp_microseconds_to_datetime(
                record.rule_information_end_timestamp_microseconds
            ),
        ),
        description=record.description,
    )

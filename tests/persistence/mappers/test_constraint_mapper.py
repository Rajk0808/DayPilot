from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

from daypilot.domain.enums import ConstraintType
from daypilot.domain.times import Constraint, TimeWindow
from daypilot.persistence.mappers.constraint import from_record, to_record
from daypilot.persistence.mappers.planner_state import constraint_id


def make_constraint(description="Work window"):
    start = datetime(2030, 1, 2, 9, tzinfo=timezone.utc)
    return Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(start, start + timedelta(hours=1)),
        description,
    )


def test_constraint_record_has_stable_uuid_identity_separate_from_values():
    record = to_record(make_constraint())
    record_with_changed_values = to_record(make_constraint("Updated description"))
    updated_record = replace(record, description="Updated description")

    assert isinstance(record.constraint_id, UUID)
    assert isinstance(record_with_changed_values.constraint_id, UUID)
    assert record.constraint_id != record_with_changed_values.constraint_id
    assert constraint_id(record) == str(record.constraint_id)
    assert constraint_id(updated_record) == constraint_id(record)


def test_mapper_can_preserve_identity_when_persistence_layer_supplies_it():
    identity = UUID("28d645ba-4956-4ee3-b412-e830c295cc9d")

    record = to_record(make_constraint("Updated description"), constraint_id=identity)

    assert record.constraint_id == identity


def test_constraint_record_round_trip_preserves_domain_values_and_record_identity():
    record = to_record(make_constraint())

    restored = from_record(record)

    assert restored.type is ConstraintType.HARD_CONSTRAINT
    assert restored.description == "Work window"
    assert restored.rule_information.start == datetime(2030, 1, 2, 9, tzinfo=timezone.utc)
    assert restored.rule_information.end == datetime(2030, 1, 2, 10, tzinfo=timezone.utc)
    assert record.constraint_id is not None

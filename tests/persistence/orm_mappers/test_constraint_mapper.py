from pathlib import Path
from uuid import UUID, uuid4

import pytest

from daypilot.persistence.models.constraint import ConstraintRecord
from daypilot.persistence.orm.constraint import ConstraintORM
from daypilot.persistence.orm_mappers.constraint import from_orm, to_orm


def make_record(**overrides):
    values = {
        "constraint_id": UUID("3c0a15ae-d4ec-4e7d-b513-d2a86eefb404"),
        "type": "unavailable",
        "rule_information_start_timestamp_microseconds": 1_900_000_000_123_456,
        "rule_information_end_timestamp_microseconds": 1_900_000_900_654_321,
        "description": "Personal appointment",
    }
    values.update(overrides)
    return ConstraintRecord(**values)


def test_record_to_orm_preserves_uuid_scalar_fields_and_state_context():
    record = make_record()

    orm = to_orm(record, "state-1")

    assert isinstance(orm, ConstraintORM)
    assert orm.state_id == "state-1"
    assert orm.constraint_id == record.constraint_id
    assert orm.type == record.type
    assert orm.start_timestamp_microseconds == record.rule_information_start_timestamp_microseconds
    assert orm.end_timestamp_microseconds == record.rule_information_end_timestamp_microseconds
    assert orm.description == record.description


def test_orm_to_record_preserves_persistence_identity():
    orm = to_orm(make_record(), "state-1")

    record = from_orm(orm)

    assert record == make_record()
    assert isinstance(record.constraint_id, UUID)


def test_constraints_with_same_values_can_have_distinct_persistence_ids():
    first = make_record()
    second = make_record(constraint_id=uuid4())

    first_orm = to_orm(first, "state-1")
    second_orm = to_orm(second, "state-1")

    assert first_orm.constraint_id != second_orm.constraint_id


def test_to_orm_rejects_invalid_state_id():
    with pytest.raises(ValueError, match="state_id"):
        to_orm(make_record(), "")


def test_from_orm_rejects_wrong_type():
    with pytest.raises(TypeError, match="ConstraintORM"):
        from_orm(object())


def test_mapper_does_not_import_domain_or_application_modules():
    source = Path(__file__).parents[3] / "src/daypilot/persistence/orm_mappers/constraint.py"
    contents = source.read_text(encoding="utf-8")
    assert "daypilot.domain" not in contents
    assert "daypilot.application" not in contents

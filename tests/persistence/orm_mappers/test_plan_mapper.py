from pathlib import Path

import pytest

from daypilot.persistence.models.plan import PlanRecord
from daypilot.persistence.orm.plan import PlanORM
from daypilot.persistence.orm_mappers.plan import from_orm, to_orm


def make_record(**overrides):
    values = {
        "id": "plan-1",
        "date_timestamp_microseconds": 1_900_000_000_123_456,
        "planning_horizon_microseconds": 86_400_000_000,
        "schedule_block_ids": ["block-a", "block-b"],
        "metadata": {"source": "planner"},
    }
    values.update(overrides)
    return PlanRecord(**values)


def test_record_to_orm_preserves_fields_and_external_state_id():
    record = make_record()

    orm = to_orm(record, "state-1")

    assert isinstance(orm, PlanORM)
    assert orm.state_id == "state-1"
    assert orm.id == record.id
    assert orm.date_timestamp_microseconds == record.date_timestamp_microseconds
    assert orm.planning_horizon_microseconds == record.planning_horizon_microseconds
    assert orm.metadata_json == record.metadata
    assert orm.metadata_json is not record.metadata
    assert not hasattr(orm, "schedule_block_ids")


def test_orm_to_record_preserves_separately_supplied_block_ids():
    orm = to_orm(make_record(), "state-1")

    record = from_orm(orm, schedule_block_ids=("block-a", "block-b"))

    assert record == make_record()
    assert not hasattr(record, "state_id")


def test_timestamp_and_duration_microseconds_are_preserved_exactly():
    record = make_record(
        date_timestamp_microseconds=1_900_000_000_123_456,
        planning_horizon_microseconds=123_456_789,
    )

    restored = from_orm(to_orm(record, "state-1"))

    assert restored.date_timestamp_microseconds == 1_900_000_000_123_456
    assert restored.planning_horizon_microseconds == 123_456_789


def test_metadata_is_copied_in_both_directions():
    record = make_record()
    orm = to_orm(record, "state-1")
    record.metadata["changed"] = "record"
    assert "changed" not in orm.metadata_json

    restored = from_orm(orm)
    orm.metadata_json["changed"] = "orm"
    assert "changed" not in restored.metadata


def test_to_orm_rejects_invalid_state_id():
    with pytest.raises(ValueError, match="state_id"):
        to_orm(make_record(), "")


def test_from_orm_rejects_wrong_type():
    with pytest.raises(TypeError, match="PlanORM"):
        from_orm(object())


def test_mapper_does_not_import_domain_or_application_modules():
    source = Path(__file__).parents[3] / "src/daypilot/persistence/orm_mappers/plan.py"
    contents = source.read_text(encoding="utf-8")
    assert "daypilot.domain" not in contents
    assert "daypilot.application" not in contents

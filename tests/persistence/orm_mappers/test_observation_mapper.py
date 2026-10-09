from pathlib import Path

import pytest

from daypilot.persistence.models.observation import ObservationRecord
from daypilot.persistence.orm.observation import ObservationORM
from daypilot.persistence.orm_mappers.observation import from_orm, to_orm


def make_record():
    return ObservationRecord(
        id="observation-1",
        task_id="task-1",
        schedule_block_id="block-1",
        actual_start_timestamp_microseconds=1_900_000_000_123_456,
        actual_end_timestamp_microseconds=1_900_000_123_654_321,
        outcome="partially_completed",
        metadata={"note": "in progress"},
    )


def test_record_to_orm_maps_all_values_and_aggregate_context():
    record = make_record()

    orm = to_orm(record, "state-1")

    assert isinstance(orm, ObservationORM)
    assert orm.state_id == "state-1"
    assert orm.id == record.id
    assert orm.task_id == record.task_id
    assert orm.schedule_block_id == record.schedule_block_id
    assert orm.actual_start_timestamp_microseconds == record.actual_start_timestamp_microseconds
    assert orm.actual_end_timestamp_microseconds == record.actual_end_timestamp_microseconds
    assert orm.outcome == record.outcome
    assert orm.metadata_json == record.metadata
    assert orm.metadata_json is not record.metadata


def test_orm_to_record_preserves_microseconds_and_copies_metadata():
    orm = to_orm(make_record(), "state-1")

    restored = from_orm(orm)

    assert restored == make_record()
    assert restored.actual_start_timestamp_microseconds == 1_900_000_000_123_456
    assert restored.actual_end_timestamp_microseconds == 1_900_000_123_654_321
    assert restored.metadata is not orm.metadata_json


def test_to_orm_rejects_invalid_state_id():
    with pytest.raises(ValueError, match="state_id"):
        to_orm(make_record(), "")


def test_from_orm_rejects_wrong_type():
    with pytest.raises(TypeError, match="ObservationORM"):
        from_orm(object())


def test_mapper_does_not_import_domain_or_application_modules():
    source = Path(__file__).parents[3] / "src/daypilot/persistence/orm_mappers/observation.py"
    contents = source.read_text(encoding="utf-8")
    assert "daypilot.domain" not in contents
    assert "daypilot.application" not in contents

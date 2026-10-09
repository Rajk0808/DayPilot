from pathlib import Path

import pytest

from daypilot.persistence.models.schedule import ScheduleBlockRecord
from daypilot.persistence.orm.schedule_block import ScheduleBlockORM
from daypilot.persistence.orm_mappers.schedule_block import from_orm, to_orm


def make_record():
    return ScheduleBlockRecord(
        id='["task-1",1900000000123456,1900003600654321]',
        task_id="task-1",
        start_timestamp_microseconds=1_900_000_000_123_456,
        end_timestamp_microseconds=1_900_003_600_654_321,
    )


def test_record_to_orm_maps_ids_timestamps_and_external_context():
    record = make_record()

    orm = to_orm(record, "state-1", plan_id="plan-1")

    assert isinstance(orm, ScheduleBlockORM)
    assert orm.state_id == "state-1"
    assert orm.id == record.id
    assert orm.task_id == record.task_id
    assert orm.plan_id == "plan-1"
    assert orm.start_timestamp_microseconds == record.start_timestamp_microseconds
    assert orm.end_timestamp_microseconds == record.end_timestamp_microseconds
    assert not hasattr(orm, "status")


def test_nullable_plan_id_and_timestamp_precision_round_trip():
    record = make_record()

    restored = from_orm(to_orm(record, "state-1", plan_id=None))

    assert restored == record


def test_to_orm_rejects_invalid_state_id():
    with pytest.raises(ValueError, match="state_id"):
        to_orm(make_record(), "")


def test_from_orm_rejects_wrong_type():
    with pytest.raises(TypeError, match="ScheduleBlockORM"):
        from_orm(object())


def test_mapper_does_not_import_domain_or_application_modules():
    source = Path(__file__).parents[3] / "src/daypilot/persistence/orm_mappers/schedule_block.py"
    contents = source.read_text(encoding="utf-8")
    assert "daypilot.domain" not in contents
    assert "daypilot.application" not in contents

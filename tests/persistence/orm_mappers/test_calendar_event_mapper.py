from pathlib import Path

import pytest

from daypilot.persistence.models.times import CalendarEventRecord
from daypilot.persistence.orm.calendar_event import CalendarEventORM
from daypilot.persistence.orm_mappers.calendar_event import from_orm, to_orm


def make_record(**overrides):
    values = {
        "id": "event-1",
        "title": "Focus time",
        "start_timestamp_microseconds": 1_900_000_000_123_456,
        "end_timestamp_microseconds": 1_900_000_900_654_321,
        "metadata": {"location": "desk"},
    }
    values.update(overrides)
    return CalendarEventRecord(**values)


def test_record_to_orm_preserves_fields_and_external_state_id():
    record = make_record()

    orm = to_orm(record, "state-1")

    assert isinstance(orm, CalendarEventORM)
    assert orm.state_id == "state-1"
    assert orm.id == record.id
    assert orm.title == record.title
    assert orm.start_timestamp_microseconds == record.start_timestamp_microseconds
    assert orm.end_timestamp_microseconds == record.end_timestamp_microseconds
    assert orm.metadata_json == record.metadata
    assert orm.metadata_json is not record.metadata


def test_orm_to_record_preserves_timestamp_precision_and_copies_metadata():
    orm = to_orm(make_record(), "state-1")

    record = from_orm(orm)

    assert record == make_record()
    assert record.start_timestamp_microseconds == 1_900_000_000_123_456
    assert record.end_timestamp_microseconds == 1_900_000_900_654_321
    assert record.metadata is not orm.metadata_json


def test_metadata_is_isolated_in_both_directions():
    record = make_record()
    orm = to_orm(record, "state-1")
    record.metadata["new"] = True
    assert "new" not in orm.metadata_json

    restored = from_orm(orm)
    orm.metadata_json["another"] = True
    assert "another" not in restored.metadata


def test_to_orm_rejects_invalid_state_id():
    with pytest.raises(ValueError, match="state_id"):
        to_orm(make_record(), "")


def test_from_orm_rejects_wrong_type():
    with pytest.raises(TypeError, match="CalendarEventORM"):
        from_orm(object())


def test_mapper_does_not_import_domain_or_application_modules():
    source = Path(__file__).parents[3] / "src/daypilot/persistence/orm_mappers/calendar_event.py"
    contents = source.read_text(encoding="utf-8")
    assert "daypilot.domain" not in contents
    assert "daypilot.application" not in contents

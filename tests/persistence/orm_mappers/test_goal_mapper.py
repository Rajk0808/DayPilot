from daypilot.persistence.models.goal import GoalRecord
from daypilot.persistence.orm.goal import GoalORM
from daypilot.persistence.orm_mappers.goal import from_orm, to_orm


def make_record(**overrides):
    values = {
        "id": "goal-1",
        "title": "Finish project",
        "description": "Ship the project",
        "deadline_timestamp_microseconds": 1_900_000_000_123_456,
        "status": "active",
        "root_task_ids": ["task-a", "task-b"],
    }
    values.update(overrides)
    return GoalRecord(**values)


def test_record_to_orm_maps_scalar_fields_and_aggregate_id():
    record = make_record()

    orm = to_orm(record, "state-1")

    assert isinstance(orm, GoalORM)
    assert orm.state_id == "state-1"
    assert orm.id == record.id
    assert orm.title == record.title
    assert orm.description == record.description
    assert orm.deadline_timestamp_microseconds == record.deadline_timestamp_microseconds
    assert orm.status == record.status
    assert not hasattr(orm, "root_task_ids")


def test_orm_to_record_accepts_root_ids_from_collection_mapping():
    orm = to_orm(make_record(), "state-1")

    record = from_orm(orm, root_task_ids=("task-a", "task-b"))

    assert record == make_record()
    assert not hasattr(record, "state_id")


def test_optional_deadline_round_trips_as_none():
    record = make_record(deadline_timestamp_microseconds=None, root_task_ids=[])

    restored = from_orm(to_orm(record, "state-1"))

    assert restored.deadline_timestamp_microseconds is None
    assert restored.root_task_ids == []


def test_root_task_ids_are_copied_from_input():
    root_ids = ["task-a"]
    orm = to_orm(make_record(), "state-1")

    record = from_orm(orm, root_task_ids=root_ids)
    root_ids.append("task-b")

    assert record.root_task_ids == ["task-a"]

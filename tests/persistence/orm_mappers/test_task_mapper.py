from daypilot.persistence.models.task import TaskRecord
from daypilot.persistence.orm.task import TaskORM
from daypilot.persistence.orm_mappers.task import from_orm, to_orm


def make_record(**overrides):
    values = {
        "id": "task-1",
        "title": "Write mapper tests",
        "description": "Check the ORM boundary",
        "status": "in_progress",
        "scheduling_status": "unscheduled",
        "priority": "high",
        "estimated_duration_microseconds": 1_234_567,
        "deadline_timestamp_microseconds": 1_900_000_000_123_456,
        "metadata": {"source": "test"},
        "parent_id": "parent-1",
        "children_ids": ["child-1", "child-2"],
    }
    values.update(overrides)
    return TaskRecord(**values)


def test_record_to_orm_maps_all_columns_and_aggregate_id():
    record = make_record()

    orm = to_orm(record, "state-1")

    assert isinstance(orm, TaskORM)
    assert orm.state_id == "state-1"
    assert orm.id == record.id
    assert orm.title == record.title
    assert orm.description == record.description
    assert orm.status == record.status
    assert orm.scheduling_status == record.scheduling_status
    assert orm.priority == record.priority
    assert orm.estimated_duration_microseconds == record.estimated_duration_microseconds
    assert orm.deadline_timestamp_microseconds == record.deadline_timestamp_microseconds
    assert orm.parent_task_id == record.parent_id
    assert orm.metadata_json == record.metadata
    assert orm.metadata_json is not record.metadata
    assert not hasattr(orm, "children_ids")


def test_orm_to_record_maps_columns_and_accepts_derived_children():
    orm = to_orm(make_record(), "state-1")

    record = from_orm(orm, children_ids=("child-a", "child-b"))

    assert record == make_record(children_ids=["child-a", "child-b"])
    assert not hasattr(record, "state_id")
    assert record.metadata is not orm.metadata_json


def test_optional_task_values_round_trip_as_none():
    record = make_record(
        priority=None,
        deadline_timestamp_microseconds=None,
        parent_id=None,
        children_ids=[],
    )

    restored = from_orm(to_orm(record, "state-1"))

    assert restored.priority is None
    assert restored.deadline_timestamp_microseconds is None
    assert restored.parent_id is None
    assert restored.children_ids == []


def test_from_orm_does_not_require_children_for_a_leaf_task():
    orm = TaskORM(
        state_id="state-1",
        id="leaf",
        title="Leaf",
        description="",
        status="not_started",
        scheduling_status="unscheduled",
        priority=None,
        estimated_duration_microseconds=0,
        deadline_timestamp_microseconds=None,
        metadata_json={},
        parent_task_id=None,
    )

    record = from_orm(orm)

    assert record.children_ids == []

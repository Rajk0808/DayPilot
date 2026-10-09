from datetime import datetime, timedelta, timezone

import pytest

from daypilot.domain.enums import Priority, SchedulingStatus, TaskStatus
from daypilot.domain.task import Task
from daypilot.persistence.mappers.task import TaskMappingContext, from_record, to_record
from daypilot.persistence.models.task import TaskRecord


def make_record(task_id, *, parent_id=None, children_ids=None, deadline_timestamp_microseconds=None):
    return TaskRecord(
        id=task_id,
        title=task_id,
        description="description",
        status=TaskStatus.NOT_STARTED.value,
        scheduling_status=SchedulingStatus.UNSCHEDULED.value,
        priority=Priority.HIGH.value,
        estimated_duration_microseconds=90_000_000,
        deadline_timestamp_microseconds=deadline_timestamp_microseconds,
        metadata={"key": "value"},
        parent_id=parent_id,
        children_ids=children_ids or [],
    )


def test_to_record_maps_task_values_and_copies_metadata():
    parent = Task("parent", "Parent")
    task = Task(
        "child",
        "Child",
        status=TaskStatus.IN_PROGRESS,
        scheduling_status=SchedulingStatus.SCHEDULED,
        priority=Priority.HIGH,
        estimated_duration=timedelta(minutes=3, microseconds=500_000),
        deadline=datetime(2030, 1, 2, 0, 0, 0, 500_000, tzinfo=timezone.utc),
        metadata={"key": "value"},
    )
    parent.add_child(task)

    record = to_record(task)

    assert record.status == TaskStatus.IN_PROGRESS.value
    assert record.scheduling_status == SchedulingStatus.SCHEDULED.value
    assert record.priority == Priority.HIGH.value
    assert record.estimated_duration_microseconds == 180_500_000
    assert record.deadline_timestamp_microseconds == 1_893_542_400_500_000
    assert record.parent_id == "parent"
    assert record.children_ids == []
    assert record.metadata == task.metadata
    assert record.metadata is not task.metadata


def test_reconstruct_uses_two_phases_and_one_identity_per_id():
    records = [
        make_record("C", parent_id="B"),
        make_record("A", children_ids=["B"]),
        make_record("B", parent_id="A", children_ids=["C"]),
    ]

    tasks = TaskMappingContext().reconstruct(records)

    assert tasks["B"].parent is tasks["A"]
    assert tasks["A"].children == [tasks["B"]]
    assert tasks["C"].parent is tasks["B"]
    assert tasks["B"].children == [tasks["C"]]


def test_same_task_id_resolves_to_same_object():
    records = [make_record("parent", children_ids=["child"]),
               make_record("child", parent_id="parent")]
    context = TaskMappingContext()

    tasks = context.reconstruct(records)

    assert tasks["parent"].children[0] is tasks["child"]
    assert tasks["child"].parent is tasks["parent"]


def test_reconstruct_requires_a_fresh_context():
    context = TaskMappingContext()
    context.register_record(make_record("existing"))

    with pytest.raises(ValueError, match="fresh mapping context"):
        context.reconstruct([make_record("new")])

    assert set(context.tasks) == {"existing"}


def test_duplicate_records_are_rejected_before_context_mutation():
    context = TaskMappingContext()

    with pytest.raises(ValueError, match="Duplicate task record IDs"):
        context.reconstruct([make_record("duplicate"), make_record("duplicate")])

    assert context.tasks == {}


@pytest.mark.parametrize(
    ("record", "expected"),
    [
        (make_record("child", parent_id="missing"), "missing parent"),
        (make_record("parent", children_ids=["missing"]), "missing child"),
    ],
)
def test_reconstruction_rejects_missing_hierarchy_references(record, expected):
    context = TaskMappingContext()
    context.register_record(record)

    with pytest.raises(ValueError, match=expected):
        context.resolve_hierarchy([record])


@pytest.mark.parametrize(
    ("records", "expected"),
    [
        ([make_record("self", parent_id="self")], "own parent"),
        ([make_record("self", children_ids=["self"])], "own child"),
        (
            [make_record("parent", children_ids=["child"]), make_record("child")],
            "does not reference it as its parent",
        ),
        (
            [make_record("parent"), make_record("child", parent_id="parent")],
            "does not list it as a child",
        ),
        (
            [make_record("parent", children_ids=["child", "child"]),
             make_record("child", parent_id="parent")],
            "duplicate child ID",
        ),
    ],
)
def test_reconstruction_rejects_invalid_hierarchy_records(records, expected):
    context = TaskMappingContext()
    for record in records:
        context.register_record(record)

    with pytest.raises(ValueError, match=expected):
        context.resolve_hierarchy(records)


def test_reconstruction_rejects_actual_descendant_cycle_atomically():
    records = [
        make_record("A", parent_id="C", children_ids=["B"]),
        make_record("B", parent_id="A", children_ids=["C"]),
        make_record("C", parent_id="B", children_ids=["A"]),
    ]
    context = TaskMappingContext()
    for record in records:
        context.register_record(record)

    with pytest.raises(ValueError, match="cycle"):
        context.resolve_hierarchy(records)
    assert all(task.parent is None and task.children == [] for task in context.tasks.values())


def test_from_record_registers_in_supplied_identity_context():
    context = TaskMappingContext()
    record = make_record("task")
    task = from_record(record, context)

    assert context.tasks["task"] is task
    assert task.metadata == {"key": "value"}
    assert task.metadata is not record.metadata
    record.metadata["key"] = "changed"
    assert task.metadata == {"key": "value"}


def test_deadline_reconstruction_is_utc_aware():
    record = make_record("task", deadline_timestamp_microseconds=1_893_542_400_500_000)
    context = TaskMappingContext()

    task = from_record(record, context)

    assert task.deadline == datetime(2030, 1, 2, 0, 0, 0, 500_000, tzinfo=timezone.utc)
    assert task.deadline.tzinfo is timezone.utc


def test_duration_round_trip_preserves_microseconds():
    source = Task("duration", "Duration", estimated_duration=timedelta(seconds=10, microseconds=500_000))
    restored = TaskMappingContext().reconstruct([to_record(source)])["duration"]

    assert restored.estimated_duration == source.estimated_duration

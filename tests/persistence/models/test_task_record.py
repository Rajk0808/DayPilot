from dataclasses import fields

import pytest

from daypilot.persistence.models.task import TaskRecord


def test_task_record_can_be_created_with_the_persistence_fields():
    record = TaskRecord(
        id="task-1",
        title="Write tests",
        description="Define the persistence shape",
        status="not_started",
        scheduling_status="unscheduled",
        priority="high",
        estimated_duration_microseconds=5_400_000_000,
        deadline_timestamp_microseconds=1_798_762_500_000_000,
        metadata={"source": "test"},
        parent_id="parent-1",
        children_ids=["child-1"],
    )

    assert record.id == "task-1"
    assert record.title == "Write tests"
    assert record.description == "Define the persistence shape"
    assert record.status == "not_started"
    assert record.scheduling_status == "unscheduled"
    assert record.priority == "high"
    assert record.estimated_duration_microseconds == 5_400_000_000
    assert record.deadline_timestamp_microseconds == 1_798_762_500_000_000
    assert record.metadata == {"source": "test"}
    assert record.parent_id == "parent-1"
    assert record.children_ids == ["child-1"]


def test_task_record_represents_every_domain_task_field():
    record_fields = {item.name for item in fields(TaskRecord)}

    assert {
        "id",
        "title",
        "description",
        "status",
        "scheduling_status",
        "priority",
        "estimated_duration_microseconds",
        "deadline_timestamp_microseconds",
        "metadata",
        "parent_id",
        "children_ids",
    } <= record_fields


def test_task_record_fields_are_required_at_construction():
    required_fields = {item.name for item in fields(TaskRecord) if item.init}

    assert required_fields == {
        "id",
        "title",
        "description",
        "status",
        "scheduling_status",
        "priority",
        "estimated_duration_microseconds",
        "deadline_timestamp_microseconds",
        "metadata",
        "parent_id",
        "children_ids",
    }
    with pytest.raises(TypeError):
        TaskRecord()


def test_optional_task_record_fields_accept_none():
    record = TaskRecord(
        id="task-1",
        title="No optional values",
        description="",
        status="not_started",
        scheduling_status="unscheduled",
        priority=None,
        estimated_duration_microseconds=0,
        deadline_timestamp_microseconds=None,
        metadata={},
        parent_id=None,
        children_ids=[],
    )

    assert record.priority is None
    assert record.deadline_timestamp_microseconds is None
    assert record.parent_id is None


def test_hierarchy_is_persisted_as_ids_not_task_objects():
    record = TaskRecord(
        id="task-1",
        title="Child",
        description="",
        status="not_started",
        scheduling_status="unscheduled",
        priority=None,
        estimated_duration_microseconds=60_000_000,
        deadline_timestamp_microseconds=None,
        metadata={},
        parent_id="parent-1",
        children_ids=["child-1"],
    )

    assert isinstance(record.parent_id, str)
    assert all(isinstance(child_id, str) for child_id in record.children_ids)
    assert not hasattr(record, "parent")
    assert not hasattr(record, "children")


def test_duration_and_deadline_have_explicit_units_and_representation():
    names = {item.name for item in fields(TaskRecord)}
    record = TaskRecord(
        id="task-1",
        title="Timed",
        description="",
        status="not_started",
        scheduling_status="unscheduled",
        priority=None,
        estimated_duration_microseconds=90_000_000,
        deadline_timestamp_microseconds=1_798_762_500_000_000,
        metadata={},
        parent_id=None,
        children_ids=[],
    )

    assert "estimated_duration_microseconds" in names
    assert "deadline_timestamp_microseconds" in names
    assert isinstance(record.estimated_duration_microseconds, int)
    assert isinstance(record.deadline_timestamp_microseconds, int)

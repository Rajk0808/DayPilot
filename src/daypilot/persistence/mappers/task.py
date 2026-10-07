from datetime import timedelta
from typing import Iterable

from daypilot.domain.enums import Priority, SchedulingStatus, TaskStatus
from daypilot.domain.task import Task
from daypilot.persistence.models.task import TaskRecord
from daypilot.persistence.time_utils import (
    datetime_to_timestamp_microseconds,
    timestamp_microseconds_to_datetime,
)


def to_record(task: Task) -> TaskRecord:
    """Convert a DayPilot task to a persistence record."""
    return TaskRecord(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status.value,
        scheduling_status=task.scheduling_status.value,
        priority=task.priority.value if task.priority is not None else None,
        estimated_duration_microseconds=(
            (task.estimated_duration.days * 86_400 + task.estimated_duration.seconds) * 1_000_000
            + task.estimated_duration.microseconds
        ),
        deadline_timestamp_microseconds=(
            datetime_to_timestamp_microseconds(task.deadline)
            if task.deadline is not None
            else None
        ),
        metadata=dict(task.metadata),
        parent_id=task.parent.id if task.parent is not None else None,
        children_ids=[child.id for child in task.children],
    )
class TaskMappingContext:
    """Identity map used to reconstruct a set of related tasks in two phases."""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}

    def register_record(self, record: TaskRecord) -> Task:
        """Create and register one task, without resolving its hierarchy yet."""
        if record.id in self.tasks:
            raise ValueError(f"Duplicate task record ID {record.id!r}.")

        task = Task(
            id=record.id,
            title=record.title,
            description=record.description,
            status=TaskStatus(record.status),
            scheduling_status=SchedulingStatus(record.scheduling_status),
            priority=Priority(record.priority) if record.priority is not None else None,
            estimated_duration=timedelta(microseconds=record.estimated_duration_microseconds),
            deadline=(
                timestamp_microseconds_to_datetime(record.deadline_timestamp_microseconds)
                if record.deadline_timestamp_microseconds is not None
                else None
            ),
            metadata=dict(record.metadata),
        )
        self.tasks[record.id] = task
        return task

    def resolve_hierarchy(self, records: Iterable[TaskRecord]) -> None:
        """Connect task references after all tasks have been registered."""
        record_list = list(records)
        record_ids = [record.id for record in record_list]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Duplicate task record IDs.")
        records_by_id = {record.id: record for record in record_list}

        # Validate all references and their reciprocal representation before
        # mutating the reconstructed domain objects.
        for record in record_list:
            if record.id not in self.tasks:
                raise ValueError(f"Task record {record.id!r} has not been registered.")
            if record.parent_id is not None and record.parent_id not in self.tasks:
                raise ValueError(
                    f"Task {record.id!r} references missing parent {record.parent_id!r}."
                )
            if record.parent_id == record.id:
                raise ValueError(f"Task {record.id!r} cannot be its own parent.")
            if len(record.children_ids) != len(set(record.children_ids)):
                raise ValueError(f"Task {record.id!r} contains a duplicate child ID.")
            for child_id in record.children_ids:
                if child_id not in self.tasks:
                    raise ValueError(
                        f"Task {record.id!r} references missing child {child_id!r}."
                    )
                if child_id == record.id:
                    raise ValueError(f"Task {record.id!r} cannot be its own child.")
                child_record = records_by_id.get(child_id)
                if child_record is None:
                    raise ValueError(f"Task record {child_id!r} is missing.")
                if child_record.parent_id != record.id:
                    raise ValueError(
                        f"Task {record.id!r} lists {child_id!r} as a child, but the child "
                        "does not reference it as its parent."
                    )
            if record.parent_id is not None:
                parent_record = records_by_id.get(record.parent_id)
                if parent_record is None:
                    raise ValueError(f"Task record {record.parent_id!r} is missing.")
                if record.id not in parent_record.children_ids:
                    raise ValueError(
                        f"Task {record.id!r} references parent {record.parent_id!r}, but "
                        "the parent does not list it as a child."
                    )

        # Detect cycles in the ID graph before connecting any domain objects.
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(task_id: str) -> None:
            if task_id in visiting:
                raise ValueError("Task hierarchy contains a cycle.")
            if task_id in visited:
                return
            visiting.add(task_id)
            for child_id in records_by_id[task_id].children_ids:
                visit(child_id)
            visiting.remove(task_id)
            visited.add(task_id)

        for record in record_list:
            visit(record.id)

        for record in record_list:
            parent = self.tasks[record.id]
            for child_id in record.children_ids:
                parent.add_child(self.tasks[child_id])

    def reconstruct(self, records: Iterable[TaskRecord]) -> dict[str, Task]:
        """Reconstruct one record set in two phases using a fresh context."""
        if self.tasks:
            raise ValueError("Task reconstruction requires a fresh mapping context.")
        record_list = list(records)
        record_ids = [record.id for record in record_list]
        if len(record_ids) != len(set(record_ids)):
            raise ValueError("Duplicate task record IDs.")
        for record in record_list:
            self.register_record(record)
        self.resolve_hierarchy(record_list)
        return self.tasks


def from_record(record: TaskRecord, context: TaskMappingContext) -> Task:
    """Create and register a task; call ``resolve_hierarchy`` after registering the set."""
    return context.register_record(record)

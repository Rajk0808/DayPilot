from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.task import Task
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.dependency import DependencyRecord


def to_record(dependent_task: Task, prerequisite_task: Task) -> DependencyRecord:
    """Convert a dependency edge to its persisted task IDs."""
    return DependencyRecord(
        dependent_task_id=dependent_task.id,
        prerequisite_task_id=prerequisite_task.id,
    )


def from_record(
    record: DependencyRecord,
    task_mapping_context: TaskMappingContext,
    dependency_graph: DependencyGraph,
) -> None:
    """Resolve canonical tasks and add their dependency through the domain graph."""
    dependent_task = task_mapping_context.tasks.get(record.dependent_task_id)
    if dependent_task is None:
        raise ValueError(
            f"Dependency references missing dependent task ID {record.dependent_task_id!r}."
        )
    prerequisite_task = task_mapping_context.tasks.get(record.prerequisite_task_id)
    if prerequisite_task is None:
        raise ValueError(
            "Dependency references missing prerequisite task ID "
            f"{record.prerequisite_task_id!r}."
        )
    dependency_graph.add_dependency(dependent_task, prerequisite_task)

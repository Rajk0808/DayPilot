import pytest

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.task import Task
from daypilot.persistence.mappers.dependency import from_record, to_record
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.models.dependency import DependencyRecord
from daypilot.persistence.models.task import TaskRecord


def make_task_record(task_id):
    return TaskRecord(
        id=task_id,
        title=task_id,
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


def task_context(*task_ids):
    context = TaskMappingContext()
    context.reconstruct([make_task_record(task_id) for task_id in task_ids])
    return context


def registered_graph(context):
    graph = DependencyGraph()
    for task in context.tasks.values():
        graph.register_task(task)
    return graph


def test_to_record_stores_dependent_and_prerequisite_ids():
    dependent = Task("B", "Task B")
    prerequisite = Task("A", "Task A")

    record = to_record(dependent, prerequisite)

    assert record == DependencyRecord(dependent_task_id="B", prerequisite_task_id="A")
    assert not hasattr(record, "dependent_task")
    assert not hasattr(record, "prerequisite_task")


def test_from_record_uses_registered_canonical_tasks_and_adds_dependency():
    context = TaskMappingContext()
    tasks = context.reconstruct([make_task_record("A"), make_task_record("B")])
    graph = registered_graph(context)

    result = from_record(DependencyRecord("B", "A"), context, graph)

    assert result is None
    assert graph.tasks["B"] is context.tasks["B"]
    assert graph.tasks["A"] is context.tasks["A"]
    assert graph.has_dependency(tasks["B"], tasks["A"])
    assert graph.get_prerequisites(tasks["B"]) == [tasks["A"]]


@pytest.mark.parametrize(
    ("record", "message"),
    [
        (DependencyRecord("missing", "A"), "missing dependent task ID"),
        (DependencyRecord("B", "missing"), "missing prerequisite task ID"),
    ],
)
def test_from_record_rejects_missing_task_ids(record, message):
    context = task_context("A", "B")

    with pytest.raises(ValueError, match=message):
        from_record(record, context, registered_graph(context))


def test_from_record_rejects_self_dependency():
    context = task_context("A")

    with pytest.raises(ValueError, match="dependent on itself"):
        from_record(DependencyRecord("A", "A"), context, registered_graph(context))


def test_domain_graph_rejects_duplicate_dependency():
    context = task_context("A", "B")
    graph = registered_graph(context)
    record = DependencyRecord("B", "A")
    from_record(record, context, graph)

    with pytest.raises(ValueError, match="already dependent"):
        from_record(record, context, graph)


def test_domain_graph_rejects_dependency_cycle():
    context = task_context("A", "B")
    graph = registered_graph(context)
    from_record(DependencyRecord("B", "A"), context, graph)

    with pytest.raises(ValueError, match="cycle"):
        from_record(DependencyRecord("A", "B"), context, graph)

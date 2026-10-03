from pathlib import Path
import sys
import pytest
sys.path.append(str(Path(__file__).parent.parent))
from src.daypilot.domain.dependency_graph import DependencyGraph
from src.daypilot.domain.task import Task
from src.daypilot.domain.enums import TaskStatus


def make_graph(*tasks: Task) -> DependencyGraph:
    graph = DependencyGraph()
    for task in tasks:
        graph.register_task(task)
    return graph


def test_add_dependency_records_edge():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    graph = make_graph(a, b)

    graph.add_dependency(a, b)

    assert graph.has_dependency(a, b)


def test_register_task_rejects_none():
    with pytest.raises(ValueError, match="Task cannot be None"):
        DependencyGraph().register_task(None)


def test_query_methods_reject_equal_valued_unowned_tasks():
    owned_a = Task(id="A", title="A")
    owned_b = Task(id="B", title="B")
    lookalike_a = Task(id="A", title="A")
    graph = make_graph(owned_a, owned_b)
    graph.add_dependency(owned_a, owned_b)

    with pytest.raises(ValueError):
        graph.get_prerequisites(lookalike_a)
    with pytest.raises(ValueError):
        graph.get_dependents(lookalike_a)
    with pytest.raises(ValueError):
        graph.has_dependency(lookalike_a, owned_b)


def test_cannot_add_self_dependency():
    a = Task(id="A", title="A")
    graph = make_graph(a)

    with pytest.raises(ValueError):
        graph.add_dependency(a, a)


def test_cannot_add_duplicate_dependency():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    graph = make_graph(a, b)
    graph.add_dependency(a, b)

    with pytest.raises(ValueError):
        graph.add_dependency(a, b)


def test_cannot_add_direct_cycle():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    graph = make_graph(a, b)
    graph.add_dependency(a, b)

    with pytest.raises(ValueError):
        graph.add_dependency(b, a)


def test_cannot_add_dependency_that_creates_cycle():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    c = Task(id="C", title="C")
    graph = make_graph(a, b, c)
    graph.add_dependency(a, b)
    graph.add_dependency(b, c)

    with pytest.raises(ValueError):
        graph.add_dependency(c, a)


def test_cannot_make_task_depend_on_its_parent():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    a.add_child(b)
    graph = make_graph(a, b)

    with pytest.raises(ValueError):
        graph.add_dependency(a, b)


def test_cannot_make_task_depend_on_its_ancestor():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    c = Task(id="C", title="C")
    a.add_child(b)
    b.add_child(c)
    graph = make_graph(a, b, c)

    with pytest.raises(ValueError):
        graph.add_dependency(a, c)


def test_multiple_tasks_can_depend_on_same_task():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    c = Task(id="C", title="C")
    graph = make_graph(a, b, c)

    graph.add_dependency(a, c)
    graph.add_dependency(b, c)

    assert graph.has_dependency(a, c)
    assert graph.has_dependency(b, c)


def test_remove_existing_dependency():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    graph = make_graph(a, b)
    graph.add_dependency(a, b)

    graph.remove_dependency(a, b)

    assert not graph.has_dependency(a, b)


def test_remove_nonexistent_dependency_is_rejected():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    graph = make_graph(a, b)

    with pytest.raises(ValueError):
        graph.remove_dependency(a, b)


def test_remove_reverse_direction_dependency_is_rejected():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    graph = make_graph(a, b)
    graph.add_dependency(a, b)

    with pytest.raises(ValueError):
        graph.remove_dependency(b, a)


def test_removing_dependency_does_not_remove_tasks():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    graph = make_graph(a, b)
    graph.add_dependency(a, b)

    graph.remove_dependency(a, b)

    assert graph.tasks[a.id] is a
    assert graph.tasks[b.id] is b


def test_removing_dependency_preserves_other_dependencies():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    c = Task(id="C", title="C")
    graph = make_graph(a, b, c)
    graph.add_dependency(a, b)
    graph.add_dependency(a, c)

    graph.remove_dependency(a, b)

    assert not graph.has_dependency(a, b)
    assert graph.has_dependency(a, c)


def test_removing_dependency_can_make_task_executable():
    a = Task(id="A", title="A", status=TaskStatus.NOT_STARTED)
    b = Task(id="B", title="B", status=TaskStatus.IN_PROGRESS)
    graph = make_graph(a, b)
    graph.add_dependency(a, b)

    assert graph.can_execute(a) is False

    graph.remove_dependency(a, b)

    assert graph.can_execute(a) is True


def test_can_execute_requires_eligible_status_and_completed_prerequisites():
    task = Task(id="A", title="A", status=TaskStatus.NOT_STARTED)
    prerequisite = Task(id="B", title="B", status=TaskStatus.IN_PROGRESS)
    graph = make_graph(task, prerequisite)
    graph.add_dependency(task, prerequisite)

    assert graph.can_execute(task) is False

    prerequisite.status = TaskStatus.COMPLETED
    assert graph.can_execute(task) is True

    task.status = TaskStatus.COMPLETED
    assert graph.can_execute(task) is False


def test_can_execute_rejects_equal_valued_task_that_is_not_owned():
    owned = Task(id="A", title="A", status=TaskStatus.NOT_STARTED)
    lookalike = Task(id="A", title="A", status=TaskStatus.NOT_STARTED)
    graph = make_graph(owned)

    assert graph.can_execute(lookalike) is False


def test_get_ready_tasks_returns_only_executable_tasks():
    ready = Task(id="ready", title="Ready", status=TaskStatus.NOT_STARTED)
    ineligible = Task(id="done", title="Done", status=TaskStatus.COMPLETED)
    waiting = Task(id="waiting", title="Waiting", status=TaskStatus.NOT_STARTED)
    prerequisite = Task(id="prerequisite", title="Prerequisite", status=TaskStatus.IN_PROGRESS)
    graph = make_graph(ready, ineligible, waiting, prerequisite)
    graph.add_dependency(waiting, prerequisite)

    assert graph.get_ready_tasks() == [ready]


def test_execution_order_places_prerequisites_first():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    c = Task(id="C", title="C")
    graph = make_graph(a, b, c)
    graph.add_dependency(a, b)
    graph.add_dependency(b, c)

    order = graph.get_execution_order()
    positions = {task.id: index for index, task in enumerate(order)}

    assert positions["C"] < positions["B"] < positions["A"]


def test_execution_order_places_all_branching_prerequisites_before_dependent():
    a = Task(id="A", title="A")
    b = Task(id="B", title="B")
    c = Task(id="C", title="C")
    graph = make_graph(a, b, c)
    graph.add_dependency(c, a)
    graph.add_dependency(c, b)

    order = graph.get_execution_order()
    positions = {task.id: index for index, task in enumerate(order)}

    assert positions["A"] < positions["C"]
    assert positions["B"] < positions["C"]

from datetime import timedelta

import pytest

from daypilot.application.hierarchy_service import TaskHierarchyApplicationService
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.planner import PlannerState
from daypilot.domain.task import Task


def make_state(*tasks: Task) -> PlannerState:
    graph = DependencyGraph()
    for task in tasks:
        graph.register_task(task)
    return PlannerState([], list(tasks), graph, [], [], None, [])


def test_valid_add_child():
    parent, child = Task("P", "Parent"), Task("C", "Child")
    state = make_state(parent, child)

    result = TaskHierarchyApplicationService().add_child(state, parent, child)

    assert result is None
    assert parent.children == [child]
    assert child.parent is parent


def test_valid_remove_child():
    parent, child = Task("P", "Parent"), Task("C", "Child")
    state = make_state(parent, child)
    state.add_child_task(parent, child)

    result = TaskHierarchyApplicationService().remove_child(state, parent, child)

    assert result is None
    assert parent.children == []
    assert child.parent is None


def test_equal_valued_non_owned_parent_is_rejected():
    owned_parent, child = Task("P", "Parent"), Task("C", "Child")
    lookalike_parent = Task("P", "Parent")
    state = make_state(owned_parent, child)

    with pytest.raises(ValueError, match="Parent task is not registered"):
        TaskHierarchyApplicationService().add_child(
            state, lookalike_parent, child
        )


def test_equal_valued_non_owned_child_is_rejected():
    parent, owned_child = Task("P", "Parent"), Task("C", "Child")
    lookalike_child = Task("C", "Child")
    state = make_state(parent, owned_child)

    with pytest.raises(ValueError, match="Child task is not registered"):
        TaskHierarchyApplicationService().add_child(
            state, parent, lookalike_child
        )


def test_duplicate_child_is_rejected_without_mutation():
    parent, child = Task("P", "Parent"), Task("C", "Child")
    state = make_state(parent, child)
    state.add_child_task(parent, child)
    before_children = list(parent.children)
    before_parent = child.parent

    with pytest.raises(ValueError, match="already has a parent"):
        TaskHierarchyApplicationService().add_child(state, parent, child)

    assert parent.children == before_children
    assert child.parent is before_parent


def test_child_with_existing_parent_is_rejected_without_mutation():
    first_parent = Task("P1", "Parent 1")
    second_parent = Task("P2", "Parent 2")
    child = Task("C", "Child")
    state = make_state(first_parent, second_parent, child)
    state.add_child_task(first_parent, child)
    before_first_children = list(first_parent.children)
    before_second_children = list(second_parent.children)

    with pytest.raises(ValueError, match="already has a parent"):
        TaskHierarchyApplicationService().add_child(state, second_parent, child)

    assert first_parent.children == before_first_children
    assert second_parent.children == before_second_children
    assert child.parent is first_parent


def test_hierarchy_cycle_is_rejected_without_mutation():
    parent, child = Task("P", "Parent"), Task("C", "Child")
    state = make_state(parent, child)
    state.add_child_task(parent, child)
    before_parent_children = list(parent.children)
    before_child_children = list(child.children)
    before_parent_parent = parent.parent

    with pytest.raises(ValueError, match="cycle|descendant"):
        TaskHierarchyApplicationService().add_child(state, child, parent)

    assert parent.children == before_parent_children
    assert child.children == before_child_children
    assert parent.parent is before_parent_parent
    assert child.parent is parent


def test_missing_child_removal_is_rejected_without_mutation():
    parent, child = Task("P", "Parent"), Task("C", "Child")
    state = make_state(parent, child)

    with pytest.raises(ValueError, match="not a child"):
        TaskHierarchyApplicationService().remove_child(state, parent, child)

    assert parent.children == []
    assert child.parent is None


def test_self_parenting_is_rejected_without_mutation():
    task = Task("A", "Task")
    state = make_state(task)

    with pytest.raises(ValueError, match="itself"):
        TaskHierarchyApplicationService().add_child(state, task, task)

    assert task.parent is None
    assert task.children == []

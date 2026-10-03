from datetime import datetime, timedelta, timezone

import pytest

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import ObservationOutcome, Priority, SchedulingStatus, TaskStatus
from daypilot.domain.goal import Goal
from daypilot.domain.observation import Observation
from daypilot.domain.planner import PlannerState
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task


DATE = datetime(2026, 9, 28, tzinfo=timezone.utc)


def task(task_id: str, status: TaskStatus = TaskStatus.NOT_STARTED) -> Task:
    return Task(
        task_id,
        task_id,
        status=status,
        priority=Priority.MEDIUM,
        estimated_duration=timedelta(hours=1),
    )


def state(tasks, goals=None, plan=None):
    graph = DependencyGraph()
    for item in tasks:
        graph.register_task(item)
    return PlannerState(goals or [], tasks, graph, [], [], plan, [])


def test_constructor_rejects_task_graph_identity_mismatch():
    owned, lookalike = task("A"), task("A")
    graph = DependencyGraph()
    graph.register_task(lookalike)

    with pytest.raises(ValueError, match="same task objects"):
        PlannerState([], [owned], graph, [], [], None, [])


def test_constructor_rejects_invalid_task_hierarchy():
    parent, child = task("P"), task("C")
    parent.children.append(child)
    child.parent = parent
    child.children.append(parent)
    parent.parent = child
    graph = DependencyGraph()
    graph.register_task(parent)
    graph.register_task(child)

    with pytest.raises(ValueError, match="cycle"):
        PlannerState([], [parent, child], graph, [], [], None, [])


def test_constructor_rejects_duplicate_child_reference():
    parent, child = task("P"), task("C")
    parent.children.extend([child, child])
    child.parent = parent
    graph = DependencyGraph()
    graph.register_task(parent)
    graph.register_task(child)

    with pytest.raises(ValueError, match="duplicate children"):
        PlannerState([], [parent, child], graph, [], [], None, [])


def test_constructor_rejects_duplicate_goal_ids_and_nested_goal_roots():
    root, child = task("R"), task("C")
    root.children.append(child)
    child.parent = root
    first = Goal("G", "first", root_tasks=[root])
    duplicate = Goal("G", "duplicate")
    with pytest.raises(ValueError, match="goal with ID"):
        state([root, child], [first, duplicate])

    with pytest.raises(ValueError, match="must not have a parent"):
        state([root, child], [Goal("nested", "nested", root_tasks=[child])])


def test_constructor_rejects_duplicate_root_task_references_in_one_goal():
    root = task("R")

    with pytest.raises(ValueError, match="duplicate root tasks"):
        state([root], [Goal("G", "goal", root_tasks=[root, root])])


def test_plan_replacement_synchronizes_composite_scheduling_state():
    parent, first, second = task("P"), task("A"), task("B")
    parent.children.extend([first, second])
    first.parent = second.parent = parent
    planner = state([parent, first, second])
    plan = Plan(
        "plan",
        DATE,
        timedelta(hours=3),
        [
            ScheduleBlock(first, DATE, DATE + timedelta(hours=1)),
            ScheduleBlock(second, DATE + timedelta(hours=1), DATE + timedelta(hours=2)),
        ],
        {},
    )

    planner.set_current_plan(plan)

    assert planner.current_plan is plan
    assert parent.scheduling_status is SchedulingStatus.SCHEDULED
    assert planner.derive_task_status(parent) is TaskStatus.NOT_STARTED

    planner.unschedule_task(first)
    assert parent.scheduling_status is SchedulingStatus.UNSCHEDULED


def test_constructor_rejects_current_plan_with_completed_task():
    completed = task("A", TaskStatus.COMPLETED)
    completed.scheduling_status = SchedulingStatus.SCHEDULED
    graph = DependencyGraph()
    graph.register_task(completed)
    plan = Plan(
        "plan",
        DATE,
        timedelta(hours=2),
        [ScheduleBlock(completed, DATE, DATE + timedelta(hours=1))],
        {},
    )

    with pytest.raises(ValueError, match="Completed or cancelled"):
        PlannerState([], [completed], graph, [], [], plan, [])


def test_constructor_rejects_current_plan_that_violates_dependency_chronology():
    prerequisite, dependent = task("A"), task("B")
    graph = DependencyGraph()
    graph.register_task(prerequisite)
    graph.register_task(dependent)
    graph.add_dependency(dependent, prerequisite)
    prerequisite.scheduling_status = dependent.scheduling_status = SchedulingStatus.SCHEDULED
    plan = Plan(
        "plan",
        DATE,
        timedelta(hours=2),
        [
            ScheduleBlock(dependent, DATE, DATE + timedelta(hours=1)),
            ScheduleBlock(prerequisite, DATE + timedelta(hours=1), DATE + timedelta(hours=2)),
        ],
        {},
    )

    with pytest.raises(ValueError, match="dependency chronology"):
        PlannerState([], [prerequisite, dependent], graph, [], [], plan, [])


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([TaskStatus.NOT_STARTED, TaskStatus.NOT_STARTED], TaskStatus.NOT_STARTED),
        ([TaskStatus.COMPLETED, TaskStatus.NOT_STARTED], TaskStatus.IN_PROGRESS),
        ([TaskStatus.BLOCKED, TaskStatus.NOT_STARTED], TaskStatus.BLOCKED),
        ([TaskStatus.CANCELLED, TaskStatus.NOT_STARTED], TaskStatus.IN_PROGRESS),
        ([TaskStatus.IN_PROGRESS, TaskStatus.NOT_STARTED], TaskStatus.IN_PROGRESS),
        ([TaskStatus.COMPLETED, TaskStatus.COMPLETED], TaskStatus.COMPLETED),
    ],
)
def test_composite_task_status_precedence(statuses, expected):
    parent = task("P")
    children = [task("A", statuses[0]), task("B", statuses[1])]
    parent.children.extend(children)
    for child in children:
        child.parent = parent
    planner = state([parent, *children])

    assert planner.derive_task_status(parent) is expected


def test_composite_scheduling_status_ignores_terminal_children():
    parent = task("P")
    completed = task("completed", TaskStatus.COMPLETED)
    cancelled = task("cancelled", TaskStatus.CANCELLED)
    parent.children.extend([completed, cancelled])
    completed.parent = cancelled.parent = parent
    planner = state([parent, completed, cancelled])

    assert planner.derive_task_scheduling_status(parent) is SchedulingStatus.UNSCHEDULED


def test_empty_composite_derives_not_started_and_unscheduled():
    parent = task("P")
    planner = state([parent])

    assert planner.derive_task_status(parent) is TaskStatus.NOT_STARTED
    assert planner.derive_task_scheduling_status(parent) is SchedulingStatus.UNSCHEDULED


def test_synchronize_task_states_updates_composite_after_child_status_change():
    parent, child = task("P"), task("A")
    parent.children.append(child)
    child.parent = parent
    planner = state([parent, child])

    child.status = TaskStatus.COMPLETED
    planner.synchronize_task_states()

    assert parent.status is TaskStatus.COMPLETED
    assert parent.scheduling_status is SchedulingStatus.UNSCHEDULED


def test_record_observation_synchronizes_composite_parent():
    parent, child = task("P"), task("A")
    parent.children.append(child)
    child.parent = parent
    child.scheduling_status = SchedulingStatus.SCHEDULED
    block = ScheduleBlock(child, DATE, DATE + timedelta(hours=1))
    plan = Plan("plan", DATE, timedelta(hours=2), [block], {})
    planner = state([parent, child], plan=plan)
    observation = Observation(
        child,
        block,
        DATE,
        DATE + timedelta(hours=1),
        ObservationOutcome.COMPLETED,
    )

    planner.record_observation(observation)

    assert child.status is TaskStatus.COMPLETED
    assert parent.status is TaskStatus.COMPLETED
    assert parent.scheduling_status is SchedulingStatus.UNSCHEDULED


def test_composite_scheduling_status_requires_all_relevant_children_scheduled():
    parent = task("P")
    first = task("A")
    second = task("B", TaskStatus.IN_PROGRESS)
    parent.children.extend([first, second])
    first.parent = second.parent = parent
    planner = state([parent, first, second])

    first.scheduling_status = SchedulingStatus.SCHEDULED
    assert planner.derive_task_scheduling_status(parent) is SchedulingStatus.UNSCHEDULED

    second.scheduling_status = SchedulingStatus.SCHEDULED
    assert planner.derive_task_scheduling_status(parent) is SchedulingStatus.SCHEDULED


def test_nested_composite_status_and_scheduling_status_are_derived_recursively():
    parent = task("P")
    child = task("child")
    grandchild_a = task("grandchild-a", TaskStatus.COMPLETED)
    grandchild_b = task("grandchild-b", TaskStatus.NOT_STARTED)
    child.children.extend([grandchild_a, grandchild_b])
    grandchild_a.parent = grandchild_b.parent = child
    parent.children.append(child)
    child.parent = parent
    planner = state([parent, child, grandchild_a, grandchild_b])

    assert planner.derive_task_status(child) is TaskStatus.IN_PROGRESS
    assert planner.derive_task_status(parent) is TaskStatus.IN_PROGRESS
    assert planner.derive_task_scheduling_status(parent) is SchedulingStatus.UNSCHEDULED

    grandchild_b.scheduling_status = SchedulingStatus.SCHEDULED
    assert planner.derive_task_scheduling_status(parent) is SchedulingStatus.SCHEDULED

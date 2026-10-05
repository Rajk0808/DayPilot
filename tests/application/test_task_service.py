from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from daypilot.application import task_service
from daypilot.application.task_service import TaskApplicationService, TaskUpdateRequest
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import (
    ObservationOutcome,
    Priority,
    SchedulingStatus,
    TaskStatus,
)
from daypilot.domain.observation import Observation
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import ReplanningResult
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task


DATE = datetime(2026, 10, 3, 9, tzinfo=timezone.utc)
HORIZON = timedelta(hours=4)


def make_state() -> tuple[PlannerState, Task]:
    task = Task(
        "A",
        "Original title",
        description="Original description",
        priority=Priority.MEDIUM,
        estimated_duration=timedelta(hours=1),
    )
    task.scheduling_status = SchedulingStatus.SCHEDULED
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    plan = Plan("old", DATE, HORIZON, [block], {})
    graph = DependencyGraph()
    graph.register_task(task)
    return PlannerState([], [task], graph, [], [], plan, []), task


def test_successful_update_returns_result_and_commits_same_state():
    state, task = make_state()
    result = TaskApplicationService().change_task(
        task,
        state,
        TaskUpdateRequest(priority=Priority.HIGH),
        DATE,
        DATE + HORIZON,
    )

    assert isinstance(result, ReplanningResult)
    assert task.priority is Priority.HIGH
    assert state.current_plan is result.new_plan


def test_scheduled_task_removal_returns_removed_task_and_commits_removal():
    state, task = make_state()
    old_plan = state.current_plan
    assert old_plan is not None
    old_blocks = list(old_plan.schedule_blocks)

    result = TaskApplicationService().remove_task(
        state,
        task,
        DATE,
        DATE + HORIZON,
    )

    assert result.removed_tasks == [task]
    assert task not in state.tasks
    assert state.dependency_graph.tasks.get(task.id) is None
    assert state.current_plan is result.new_plan
    assert state.current_plan is not None
    assert state.current_plan.schedule_blocks == []
    assert old_blocks[0].task is task


def test_unscheduled_task_removal_commits_task_and_graph_removal():
    task = Task("A", "A", estimated_duration=timedelta(hours=1))
    graph = DependencyGraph()
    graph.register_task(task)
    state = PlannerState([], [task], graph, [], [], None, [])

    result = TaskApplicationService().remove_task(
        state,
        task,
        DATE,
        DATE + HORIZON,
    )

    assert result.removed_tasks == [task]
    assert task not in state.tasks
    assert state.dependency_graph.tasks.get(task.id) is None
    assert state.current_plan is result.new_plan


def test_removal_replan_failure_preserves_task_graph_and_plan(monkeypatch):
    state, task = make_state()
    old_plan = state.current_plan
    old_tasks = list(state.tasks)
    old_graph = dict(state.dependency_graph.tasks)

    def fail_replan(*args, **kwargs):
        raise RuntimeError("planning failed")

    monkeypatch.setattr(task_service, "replan", fail_replan)

    with pytest.raises(RuntimeError, match="planning failed"):
        TaskApplicationService().remove_task(state, task, DATE, DATE + HORIZON)

    assert state.tasks == old_tasks
    assert state.dependency_graph.tasks == old_graph
    assert state.current_plan is old_plan


def test_removal_commit_failure_preserves_task_graph_and_plan(monkeypatch):
    state, task = make_state()
    old_plan = state.current_plan
    old_tasks = list(state.tasks)
    old_graph = dict(state.dependency_graph.tasks)

    def fail_commit(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(task_service, "apply_replanning_result", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        TaskApplicationService().remove_task(state, task, DATE, DATE + HORIZON)

    assert state.tasks == old_tasks
    assert state.dependency_graph.tasks == old_graph
    assert state.current_plan is old_plan


def test_task_with_dependencies_cannot_be_removed():
    prerequisite = Task("A", "A", estimated_duration=timedelta(hours=1))
    dependent = Task("B", "B", estimated_duration=timedelta(hours=1))
    graph = DependencyGraph()
    graph.register_task(prerequisite)
    graph.register_task(dependent)
    graph.add_dependency(dependent, prerequisite)
    state = PlannerState([], [prerequisite, dependent], graph, [], [], None, [])

    with pytest.raises(ValueError, match="dependents"):
        TaskApplicationService().remove_task(
            state, prerequisite, DATE, DATE + HORIZON
        )


def test_task_with_parent_or_children_cannot_be_removed():
    parent = Task("P", "P", estimated_duration=timedelta(hours=1))
    child = Task("C", "C", estimated_duration=timedelta(hours=1))
    parent.children.append(child)
    child.parent = parent
    graph = DependencyGraph()
    graph.register_task(parent)
    graph.register_task(child)
    state = PlannerState([], [parent, child], graph, [], [], None, [])

    with pytest.raises(ValueError, match="children"):
        TaskApplicationService().remove_task(state, parent, DATE, DATE + HORIZON)
    with pytest.raises(ValueError, match="parent"):
        TaskApplicationService().remove_task(state, child, DATE, DATE + HORIZON)


def test_task_with_observations_cannot_be_removed():
    state, task = make_state()
    assert state.current_plan is not None
    block = state.current_plan.schedule_blocks[0]
    observation = Observation(
        task,
        block,
        DATE,
        DATE + timedelta(minutes=30),
        ObservationOutcome.PARTIALLY_COMPLETED,
    )
    state.add_observation(observation)

    with pytest.raises(ValueError, match="observations"):
        TaskApplicationService().remove_task(state, task, DATE, DATE + HORIZON)


def test_equal_valued_different_task_is_rejected_for_removal():
    state, owned = make_state()
    lookalike = Task(
        owned.id,
        owned.title,
        description=owned.description,
        priority=owned.priority,
        estimated_duration=owned.estimated_duration,
    )

    with pytest.raises(ValueError, match="not registered"):
        TaskApplicationService().remove_task(
            state, lookalike, DATE, DATE + HORIZON
        )


def test_update_requires_exact_task_identity():
    state, owned = make_state()
    lookalike = Task(
        owned.id,
        owned.title,
        description=owned.description,
        priority=owned.priority,
        estimated_duration=owned.estimated_duration,
    )

    with pytest.raises(ValueError, match="not registered"):
        TaskApplicationService().change_task(
            lookalike,
            state,
            TaskUpdateRequest(title="Changed"),
            DATE,
            DATE + HORIZON,
        )


def test_empty_update_is_rejected_without_replanning(monkeypatch):
    state, task = make_state()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("replan must not be called")

    monkeypatch.setattr(task_service, "replan", fail_if_called)

    with pytest.raises(ValueError, match="empty"):
        TaskApplicationService().change_task(
            task,
            state,
            TaskUpdateRequest(),
            DATE,
            DATE + HORIZON,
        )


def test_title_and_description_update():
    state, task = make_state()

    TaskApplicationService().change_task(
        task,
        state,
        TaskUpdateRequest(title="New title", description="New description"),
        DATE,
        DATE + HORIZON,
    )

    assert task.title == "New title"
    assert task.description == "New description"


@pytest.mark.parametrize(
    "updates",
    [
        TaskUpdateRequest(priority=Priority.CRITICAL),
        TaskUpdateRequest(estimated_duration=timedelta(hours=2)),
        TaskUpdateRequest(deadline=DATE + timedelta(hours=2)),
    ],
)
def test_scheduling_relevant_updates_trigger_replanning(updates):
    state, task = make_state()

    result = TaskApplicationService().change_task(
        task,
        state,
        updates,
        DATE,
        DATE + HORIZON,
    )

    assert state.current_plan is result.new_plan
    assert result.invalidated_blocks


def test_planning_timestamps_require_aware_ordered_values():
    state, task = make_state()
    service = TaskApplicationService()

    with pytest.raises(ValueError, match="timezone-aware"):
        service.change_task(
            task,
            state,
            TaskUpdateRequest(title="Changed"),
            datetime(2026, 10, 3, 9),
            DATE + HORIZON,
        )
    with pytest.raises(ValueError, match="after"):
        service.change_task(
            task,
            state,
            TaskUpdateRequest(title="Changed"),
            DATE + HORIZON,
            DATE,
        )


@pytest.mark.parametrize(
    "updates",
    [
        TaskUpdateRequest(estimated_duration=timedelta(0)),
        TaskUpdateRequest(deadline=datetime(2026, 10, 3, 12)),
        cast(TaskUpdateRequest, TaskUpdateRequest(priority=cast(Priority, "high"))),
        cast(TaskUpdateRequest, TaskUpdateRequest(status=cast(TaskStatus, "completed"))),
    ],
)
def test_invalid_update_values_do_not_mutate_task(updates):
    state, task = make_state()
    original = (task.priority, task.estimated_duration, task.deadline, task.status)

    with pytest.raises(ValueError):
        TaskApplicationService().change_task(
            task,
            state,
            updates,
            DATE,
            DATE + HORIZON,
        )

    assert (task.priority, task.estimated_duration, task.deadline, task.status) == original


def test_replan_failure_rolls_back_task_mutation(monkeypatch):
    state, task = make_state()
    original_priority = task.priority

    def fail_replan(*args, **kwargs):
        raise RuntimeError("planning failed")

    monkeypatch.setattr(task_service, "replan", fail_replan)

    with pytest.raises(RuntimeError, match="planning failed"):
        TaskApplicationService().change_task(
            task,
            state,
            TaskUpdateRequest(priority=Priority.HIGH),
            DATE,
            DATE + HORIZON,
        )

    assert task.priority is original_priority


def test_commit_failure_rolls_back_task_mutation(monkeypatch):
    state, task = make_state()
    original_priority = task.priority
    assert state.current_plan is not None
    original_blocks = list(state.current_plan.schedule_blocks)
    original_scheduling_statuses = [item.scheduling_status for item in state.tasks]
    original_dependency_graph = state.dependency_graph
    def fail_commit(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(task_service, "apply_replanning_result", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        TaskApplicationService().change_task(
            task,
            state,
            TaskUpdateRequest(priority=Priority.HIGH),
            DATE,
            DATE + HORIZON,
        )

    assert task.priority is original_priority
    assert state.current_plan is not None
    assert state.current_plan.id == "old"
    assert state.current_plan.schedule_blocks == original_blocks
    assert state.dependency_graph == original_dependency_graph
    assert [item.scheduling_status for item in state.tasks] == original_scheduling_statuses

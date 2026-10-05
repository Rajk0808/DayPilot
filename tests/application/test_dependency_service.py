from datetime import datetime, timedelta, timezone

import pytest

from daypilot.application import dependency_service
from daypilot.application.dependency_service import DependencyApplicationService
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import Priority, SchedulingStatus
from daypilot.domain.planner import PlannerState
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task


DATE = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
HORIZON = timedelta(hours=6)


def make_task(task_id: str) -> Task:
    return Task(
        task_id,
        task_id,
        priority=Priority.MEDIUM,
        estimated_duration=timedelta(hours=1),
    )


def make_state(*, scheduled: bool = False) -> tuple[PlannerState, Task, Task]:
    prerequisite, dependent = make_task("A"), make_task("B")
    graph = DependencyGraph()
    graph.register_task(prerequisite)
    graph.register_task(dependent)
    plan = None
    if scheduled:
        prerequisite.scheduling_status = dependent.scheduling_status = SchedulingStatus.SCHEDULED
        plan = Plan(
            "old",
            DATE,
            HORIZON,
            [
                ScheduleBlock(prerequisite, DATE, DATE + timedelta(hours=1)),
                ScheduleBlock(dependent, DATE + timedelta(hours=1), DATE + timedelta(hours=2)),
            ],
            {},
        )
    return PlannerState([], [prerequisite, dependent], graph, [], [], plan, []), prerequisite, dependent


def graph_snapshot(state: PlannerState) -> dict[str, set[str]]:
    return {
        task_id: set(prerequisites)
        for task_id, prerequisites in state.dependency_graph.prerequisites.items()
    }


def test_add_dependency_replans_and_preserves_graph_mutation():
    state, prerequisite, dependent = make_state(scheduled=True)
    assert state.current_plan is not None
    old_dependent_block = state.current_plan.schedule_blocks[1]

    result = DependencyApplicationService().add_dependency(
        state, dependent, prerequisite, DATE, DATE + HORIZON
    )

    assert state.dependency_graph.has_dependency(dependent, prerequisite)
    assert result.invalidated_blocks == [old_dependent_block]
    assert result.rescheduled_blocks[0].task is dependent
    assert state.current_plan is result.new_plan


def test_remove_dependency_replans_and_preserves_valid_schedule():
    state, prerequisite, dependent = make_state(scheduled=True)
    state.add_dependency(dependent, prerequisite)
    old_plan = state.current_plan
    assert old_plan is not None
    old_blocks = list(old_plan.schedule_blocks)

    result = DependencyApplicationService().remove_dependency(
        state, dependent, prerequisite, DATE, DATE + HORIZON
    )

    assert not state.dependency_graph.has_dependency(dependent, prerequisite)
    assert result.invalidated_blocks == []
    assert result.rescheduled_blocks == []
    assert state.current_plan is result.new_plan
    assert result.new_plan.schedule_blocks == old_blocks


@pytest.mark.parametrize("method", ["add_dependency", "remove_dependency"])
def test_dependency_service_rejects_equal_valued_unowned_tasks(method):
    state, prerequisite, dependent = make_state()
    lookalike = make_task(dependent.id)

    if method == "remove_dependency":
        state.add_dependency(dependent, prerequisite)

    with pytest.raises(ValueError, match="not registered"):
        getattr(DependencyApplicationService(), method)(
            state, lookalike, prerequisite, DATE, DATE + HORIZON
        )


def test_add_dependency_delegates_duplicate_and_cycle_validation_to_domain():
    state, prerequisite, dependent = make_state()
    state.add_dependency(dependent, prerequisite)

    with pytest.raises(ValueError):
        DependencyApplicationService().add_dependency(
            state, dependent, prerequisite, DATE, DATE + HORIZON
        )

    third = make_task("C")
    state.add_task(third)
    state.add_dependency(third, dependent)
    with pytest.raises(ValueError):
        DependencyApplicationService().add_dependency(
            state, prerequisite, third, DATE, DATE + HORIZON
        )


def test_remove_dependency_rejects_missing_dependency():
    state, prerequisite, dependent = make_state()

    with pytest.raises(ValueError, match="does not exist"):
        DependencyApplicationService().remove_dependency(
            state, dependent, prerequisite, DATE, DATE + HORIZON
        )


def test_add_dependency_replan_failure_rolls_back_graph_and_plan(monkeypatch):
    state, prerequisite, dependent = make_state(scheduled=True)
    old_plan = state.current_plan
    old_graph = graph_snapshot(state)

    def fail_replan(*args, **kwargs):
        raise RuntimeError("planning failed")

    monkeypatch.setattr(dependency_service, "replan", fail_replan)

    with pytest.raises(RuntimeError, match="planning failed"):
        DependencyApplicationService().add_dependency(
            state, dependent, prerequisite, DATE, DATE + HORIZON
        )

    assert graph_snapshot(state) == old_graph
    assert not state.dependency_graph.has_dependency(dependent, prerequisite)
    assert state.current_plan is old_plan


def test_add_dependency_commit_failure_rolls_back_graph_and_plan(monkeypatch):
    state, prerequisite, dependent = make_state(scheduled=True)
    old_plan = state.current_plan
    old_graph = graph_snapshot(state)

    def fail_commit(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(dependency_service, "apply_replanning_result", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        DependencyApplicationService().add_dependency(
            state, dependent, prerequisite, DATE, DATE + HORIZON
        )

    assert graph_snapshot(state) == old_graph
    assert not state.dependency_graph.has_dependency(dependent, prerequisite)
    assert state.current_plan is old_plan


def test_remove_dependency_replan_failure_rolls_back_graph_and_plan(monkeypatch):
    state, prerequisite, dependent = make_state(scheduled=True)
    state.add_dependency(dependent, prerequisite)
    old_plan = state.current_plan
    old_graph = graph_snapshot(state)

    def fail_replan(*args, **kwargs):
        raise RuntimeError("planning failed")

    monkeypatch.setattr(dependency_service, "replan", fail_replan)

    with pytest.raises(RuntimeError, match="planning failed"):
        DependencyApplicationService().remove_dependency(
            state, dependent, prerequisite, DATE, DATE + HORIZON
        )

    assert graph_snapshot(state) == old_graph
    assert state.dependency_graph.has_dependency(dependent, prerequisite)
    assert state.current_plan is old_plan


def test_remove_dependency_commit_failure_rolls_back_graph_and_plan(monkeypatch):
    state, prerequisite, dependent = make_state(scheduled=True)
    state.add_dependency(dependent, prerequisite)
    old_plan = state.current_plan
    old_graph = graph_snapshot(state)

    def fail_commit(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(dependency_service, "apply_replanning_result", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        DependencyApplicationService().remove_dependency(
            state, dependent, prerequisite, DATE, DATE + HORIZON
        )

    assert graph_snapshot(state) == old_graph
    assert state.dependency_graph.has_dependency(dependent, prerequisite)
    assert state.current_plan is old_plan

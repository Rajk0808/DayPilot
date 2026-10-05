from datetime import datetime, timedelta, timezone

import pytest

from daypilot.application import observation_service
from daypilot.application.observation_service import (
    ObservationApplicationService,
    ObservationRequest,
)
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import ObservationOutcome, Priority, SchedulingStatus, TaskStatus
from daypilot.domain.observation import Observation
from daypilot.domain.planner import PlannerState
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task


DATE = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
HORIZON = timedelta(hours=4)


def make_composite_state() -> tuple[PlannerState, Task, Task, ScheduleBlock]:
    parent = Task("P", "Parent", estimated_duration=timedelta(hours=1))
    child = Task(
        "C",
        "Child",
        priority=Priority.MEDIUM,
        estimated_duration=timedelta(hours=1),
    )
    parent.children.append(child)
    child.parent = parent
    child.scheduling_status = SchedulingStatus.SCHEDULED
    block = ScheduleBlock(child, DATE, DATE + timedelta(hours=1))
    plan = Plan("old", DATE, HORIZON, [block], {})
    graph = DependencyGraph()
    graph.register_task(parent)
    graph.register_task(child)
    state = PlannerState([], [parent, child], graph, [], [], plan, [])
    return state, parent, child, block


def make_request(child: Task, block: ScheduleBlock) -> ObservationRequest:
    return ObservationRequest(
        task=child,
        scheduled_block=block,
        actual_start=DATE,
        actual_end=DATE + timedelta(hours=1),
        outcome=ObservationOutcome.COMPLETED,
    )


def test_successful_record_uses_observation_and_commits_replan():
    state, parent, child, block = make_composite_state()

    result = ObservationApplicationService().record_observation(
        make_request(child, block), state, DATE, DATE + HORIZON
    )

    assert len(state.observations) == 1
    assert state.observations[0].task is child
    assert child.status is TaskStatus.COMPLETED
    assert parent.status is TaskStatus.COMPLETED
    assert state.current_plan is result.new_plan


def test_replan_failure_restores_observation_tasks_composite_and_plan(monkeypatch):
    state, parent, child, block = make_composite_state()
    old_plan = state.current_plan
    original = {
        task.id: (task.status, task.scheduling_status)
        for task in state.tasks
    }

    def fail_replan(*args, **kwargs):
        raise RuntimeError("planning failed")

    monkeypatch.setattr(observation_service, "replan", fail_replan)

    with pytest.raises(RuntimeError, match="planning failed"):
        ObservationApplicationService().record_observation(
            make_request(child, block), state, DATE, DATE + HORIZON
        )

    assert state.observations == []
    assert state.current_plan is old_plan
    assert {
        task.id: (task.status, task.scheduling_status)
        for task in state.tasks
    } == original
    assert parent.status is original[parent.id][0]
    assert parent.scheduling_status is original[parent.id][1]


def test_commit_failure_restores_observation_tasks_composite_and_plan(monkeypatch):
    state, parent, child, block = make_composite_state()
    old_plan = state.current_plan
    original = {
        task.id: (task.status, task.scheduling_status)
        for task in state.tasks
    }

    def fail_commit(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(observation_service, "apply_replanning_result", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        ObservationApplicationService().record_observation(
            make_request(child, block), state, DATE, DATE + HORIZON
        )

    assert state.observations == []
    assert state.current_plan is old_plan
    assert {
        task.id: (task.status, task.scheduling_status)
        for task in state.tasks
    } == original
    assert parent.status is original[parent.id][0]
    assert parent.scheduling_status is original[parent.id][1]


def test_record_failure_does_not_pop_previous_observation(monkeypatch):
    state, _, child, block = make_composite_state()
    previous = Observation(
        child,
        block,
        DATE,
        DATE + timedelta(minutes=30),
        ObservationOutcome.PARTIALLY_COMPLETED,
    )
    state.record_observation(previous)
    original_status = child.status
    original_scheduling_status = child.scheduling_status
    original_observations = list(state.observations)

    overlapping_request = ObservationRequest(
        task=child,
        scheduled_block=block,
        actual_start=DATE + timedelta(minutes=15),
        actual_end=DATE + timedelta(minutes=45),
        outcome=ObservationOutcome.PARTIALLY_COMPLETED,
    )
    monkeypatch.setattr(
        observation_service,
        "replan",
        lambda *args, **kwargs: pytest.fail("replan must not be called"),
    )

    with pytest.raises(ValueError, match="non-overlapping"):
        ObservationApplicationService().record_observation(
            overlapping_request, state, DATE, DATE + HORIZON
        )

    assert state.observations == original_observations
    assert child.status is original_status
    assert child.scheduling_status is original_scheduling_status

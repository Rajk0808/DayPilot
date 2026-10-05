from datetime import datetime, timedelta, timezone

import pytest

from daypilot.application.planning_service import PlanningApplicationService
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import PlanningChangeType, Priority, SchedulingStatus, TaskStatus
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import PlanningChange, ReplanningResult
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task


DATE = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
HORIZON = timedelta(hours=4)


def make_state() -> tuple[PlannerState, Task]:
    task = Task(
        "A",
        "Task",
        priority=Priority.MEDIUM,
        estimated_duration=timedelta(hours=1),
    )
    graph = DependencyGraph()
    graph.register_task(task)
    return PlannerState([], [task], graph, [], [], None, []), task


def test_replan_returns_preview_proposal_without_mutating_state():
    state, task = make_state()
    change = PlanningChange(PlanningChangeType.TASK_ADDED, task=task)
    old_tasks = list(state.tasks)
    old_statuses = [(item.status, item.scheduling_status) for item in state.tasks]
    old_graph = dict(state.dependency_graph.tasks)
    old_observations = list(state.observations)
    old_calendar_events = list(state.calendar_events)
    old_constraints = list(state.constraints)

    result = PlanningApplicationService().replan(
        state, change, DATE, DATE + HORIZON
    )

    assert result.new_plan is not None
    assert state.current_plan is None
    assert state.tasks == old_tasks
    assert [(item.status, item.scheduling_status) for item in state.tasks] == old_statuses
    assert state.dependency_graph.tasks == old_graph
    assert state.observations == old_observations
    assert state.calendar_events == old_calendar_events
    assert state.constraints == old_constraints
    assert task.scheduling_status is SchedulingStatus.UNSCHEDULED


def test_valid_result_can_be_explicitly_applied():
    state, task = make_state()
    result = PlanningApplicationService().replan(
        state,
        PlanningChange(PlanningChangeType.TASK_ADDED, task=task),
        DATE,
        DATE + HORIZON,
    )

    applied = PlanningApplicationService().apply_replanning_result(state, result)

    assert applied is result
    assert state.current_plan is result.new_plan
    assert task.scheduling_status is SchedulingStatus.SCHEDULED


def test_invalid_result_propagates_domain_validation_and_leaves_state_unchanged():
    state, task = make_state()
    outside = Task(
        "outside",
        "Outside",
        priority=Priority.MEDIUM,
        estimated_duration=timedelta(hours=1),
    )
    invalid_plan = Plan(
        "invalid",
        DATE,
        HORIZON,
        [ScheduleBlock(outside, DATE, DATE + timedelta(hours=1))],
        {},
    )
    result = ReplanningResult(invalid_plan, [], [], [], [])
    old_plan = state.current_plan
    old_statuses = [item.scheduling_status for item in state.tasks]
    old_tasks = list(state.tasks)

    with pytest.raises(ValueError, match="not in the planner state"):
        PlanningApplicationService().apply_replanning_result(state, result)

    assert state.current_plan is old_plan
    assert state.tasks == old_tasks
    assert [item.scheduling_status for item in state.tasks] == old_statuses
    assert state.dependency_graph.tasks == {task.id: task}


@pytest.mark.parametrize(
    "operation",
    ["replan", "apply_replanning_result"],
)
def test_planning_service_rejects_none_inputs(operation):
    service = PlanningApplicationService()
    state, task = make_state()
    change = PlanningChange(PlanningChangeType.TASK_ADDED, task=task)
    result = Plan("empty", DATE, HORIZON, [], {})
    proposal = ReplanningResult(result, [], [], [], [])

    if operation == "replan":
        with pytest.raises(ValueError, match="Planning change"):
            service.replan(state, None, DATE, DATE + HORIZON)
        with pytest.raises(ValueError, match="Planner state"):
            service.replan(None, change, DATE, DATE + HORIZON)
    else:
        with pytest.raises(ValueError, match="Replanning result"):
            service.apply_replanning_result(state, None)
        with pytest.raises(ValueError, match="Planner state"):
            service.apply_replanning_result(None, proposal)


def test_replan_rejects_invalid_planning_window():
    state, task = make_state()
    change = PlanningChange(PlanningChangeType.TASK_ADDED, task=task)

    with pytest.raises(ValueError, match="timezone-aware"):
        PlanningApplicationService().replan(
            state,
            change,
            datetime(2026, 10, 5, 9),
            DATE + HORIZON,
        )
    with pytest.raises(ValueError, match="after"):
        PlanningApplicationService().replan(
            state,
            change,
            DATE + HORIZON,
            DATE,
        )

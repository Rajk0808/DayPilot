"""Cross-service workflows through the public application facade."""

from datetime import datetime, timedelta, timezone

import pytest

from daypilot.application.application_service import DayPilotApplicationService
from daypilot.application.times_service import CalendarApplicationService
from daypilot.application.constraint_service import ConstraintApplicationService
from daypilot.application.dependency_service import DependencyApplicationService
from daypilot.application.goal_service import GoalApplicationService
from daypilot.application.hierarchy_service import TaskHierarchyApplicationService
from daypilot.application.observation_service import (
    ObservationApplicationService,
    ObservationRequest,
)
from daypilot.application.planning_service import PlanningApplicationService
from daypilot.application.task_service import (
    TaskApplicationService,
    TaskCreateRequest,
    TaskUpdateRequest,
)
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import (
    ConstraintType,
    ObservationOutcome,
    PlanningChangeType,
    Priority,
    SchedulingStatus,
    TaskStatus,
)
from daypilot.domain.goal import Goal
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import PlanningChange
from daypilot.domain.schedule import ScheduleBlock
from daypilot.domain.task import Task
from daypilot.domain.times import CalendarEvent, Constraint, TimeWindow


START = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
END = START + timedelta(hours=8)


def make_facade():
    return DayPilotApplicationService(
        task_service=TaskApplicationService(),
        goal_service=GoalApplicationService(),
        dependency_service=DependencyApplicationService(),
        calendar_service=CalendarApplicationService(),
        constraint_service=ConstraintApplicationService(),
        observation_service=ObservationApplicationService(),
        hierarchy_service=TaskHierarchyApplicationService(),
        planning_service=PlanningApplicationService(),
    )


def make_state(*tasks, goals=None, events=None, constraints=None):
    graph = DependencyGraph()
    for task in tasks:
        graph.register_task(task)
    return PlannerState(
        goals=[] if goals is None else goals,
        tasks=list(tasks),
        dependency_graph=graph,
        calendar_events=[] if events is None else events,
        constraints=[] if constraints is None else constraints,
        current_plan=None,
        observations=[],
    )


def task(task_id, duration=timedelta(hours=1), **kwargs):
    return Task(task_id, task_id, estimated_duration=duration, **kwargs)


def blocks_by_id(state):
    return {block.task.id: block for block in state.current_plan.schedule_blocks}


# Task workflows

def test_create_change_and_replan_commits_consistent_plan():
    app = make_facade()
    state = make_state()
    app.create_task(
        state, TaskCreateRequest("A", "Initial", estimated_duration=timedelta(hours=1)), START, END
    )
    owned = state.tasks[0]
    original_block = blocks_by_id(state)["A"]

    result = app.change_task(
        state, owned,
        TaskUpdateRequest(title="Updated", priority=Priority.HIGH,
                          estimated_duration=timedelta(hours=2)),
        START, END,
    )

    block = blocks_by_id(state)["A"]
    assert result.new_plan is state.current_plan
    assert owned is state.tasks[0] is block.task
    assert owned.title == "Updated"
    assert owned.estimated_duration == timedelta(hours=2)
    assert block.end - block.start == timedelta(hours=2)
    assert owned.scheduling_status is SchedulingStatus.SCHEDULED
    assert block is not original_block


def test_create_goal_and_attach_task_as_root_preserves_state_identity():
    app = make_facade()
    state = make_state()
    app.create_task(state, TaskCreateRequest("A", "Task"), START, END)
    owned = state.tasks[0]
    goal = app.create_goal(Goal("G", "Goal"), state)
    goal.add_root_task(owned)

    assert goal in state.goals
    assert goal.root_tasks == [owned]
    assert owned.parent is None
    assert state.dependency_graph.tasks[owned.id] is owned
    assert state.current_plan.schedule_blocks[0].task is owned


# Dependency workflows

def test_dependency_addition_replans_in_prerequisite_order():
    app = make_facade()
    state = make_state()
    app.create_task(state, TaskCreateRequest("A", "A"), START, END)
    a = state.tasks[0]
    app.create_task(state, TaskCreateRequest("B", "B"), START, END)
    b = next(item for item in state.tasks if item.id == "B")

    app.add_dependency(state, b, a, START, END)
    planned = blocks_by_id(state)
    assert planned["B"].start >= planned["A"].end
    assert state.dependency_graph.has_dependency(b, a)


def test_dependency_removal_allows_b_to_be_scheduled_before_a():
    app = make_facade()
    a, b = task("A"), task("B")
    state = make_state(a, b)
    # A later deadline makes B win the available opening before dependency is added.
    state.add_dependency(b, a)
    app.apply_replanning_result(
        state, app.replan(state, PlanningChange(PlanningChangeType.PLAN_REPLACED), START, START + timedelta(hours=1))
    )
    assert "B" not in blocks_by_id(state)

    app.remove_dependency(state, b, a, START, END)
    assert not state.dependency_graph.has_dependency(b, a)
    assert "B" in blocks_by_id(state)


# Calendar and constraint workflows

def test_calendar_event_replans_existing_task_around_busy_time():
    app = make_facade()
    state = make_state()
    app.create_task(state, TaskCreateRequest("A", "Task"), START, END)
    old = blocks_by_id(state)["A"]
    event = CalendarEvent("E", "Busy", START, START + timedelta(hours=2))

    app.add_calendar_event(event, state, START, END)
    new = blocks_by_id(state)["A"]
    assert old not in state.current_plan.schedule_blocks
    assert new.start >= event.end or new.end <= event.start
    assert event in state.calendar_events


def test_hard_constraint_moves_task_outside_blocked_window():
    app = make_facade()
    state = make_state()
    app.create_task(state, TaskCreateRequest("A", "Task"), START, END)
    old = blocks_by_id(state)["A"]
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(START, START + timedelta(hours=2)),
    )

    app.add_constraint(state, constraint, START, END)
    new = blocks_by_id(state)["A"]
    assert old not in state.current_plan.schedule_blocks
    assert new.start >= constraint.rule_information.end or new.end <= constraint.rule_information.start
    assert constraint in state.constraints


# Observation workflows

@pytest.mark.parametrize(
    ("outcome", "worked", "remaining"),
    [
        (ObservationOutcome.PARTIALLY_COMPLETED, timedelta(minutes=45), timedelta(hours=1, minutes=15)),
        (ObservationOutcome.COMPLETED, timedelta(hours=2), timedelta(0)),
    ],
)
def test_observation_preserves_remaining_work_or_removes_completed_task(outcome, worked, remaining):
    app = make_facade()
    state = make_state()
    app.create_task(
        state, TaskCreateRequest("A", "Task", estimated_duration=timedelta(hours=2)), START, END
    )
    owned = state.tasks[0]
    scheduled = blocks_by_id(state)["A"]
    actual_start = scheduled.start
    app.record_observation(
        ObservationRequest(
            owned, scheduled, actual_start, actual_start + worked, outcome
        ), state, START, END,
    )

    assert len(state.observations) == 1
    assert state.observations[0].task is owned
    if outcome is ObservationOutcome.PARTIALLY_COMPLETED:
        assert owned.status is TaskStatus.IN_PROGRESS
        assert blocks_by_id(state)["A"].end - blocks_by_id(state)["A"].start == remaining
    else:
        assert state.observations[0].remaining_duration == timedelta(0)
        assert owned.status is TaskStatus.COMPLETED
        assert "A" not in blocks_by_id(state)


# Scheduled removal and explicit replanning

def test_remove_scheduled_task_updates_plan_and_dependency_graph_atomically():
    app = make_facade()
    state = make_state()
    app.create_task(state, TaskCreateRequest("A", "Task"), START, END)
    owned = state.tasks[0]

    app.remove_task(state, owned, START, END)
    assert all(existing is not owned for existing in state.tasks)
    assert owned.id not in state.dependency_graph.tasks
    assert all(block.task is not owned for block in state.current_plan.schedule_blocks)


def test_preview_can_be_inspected_before_explicit_commit():
    app = make_facade()
    state = make_state()
    app.create_task(state, TaskCreateRequest("A", "Task"), START, END)
    before_plan = state.current_plan
    before_status = state.tasks[0].scheduling_status

    preview = app.replan(
        state, PlanningChange(PlanningChangeType.PLAN_REPLACED), START, END
    )
    assert state.current_plan is before_plan
    assert state.tasks[0].scheduling_status is before_status
    assert preview.new_plan is before_plan or preview.new_plan.schedule_blocks

    app.apply_replanning_result(state, preview)
    assert state.current_plan is preview.new_plan
    assert state.tasks[0].scheduling_status is SchedulingStatus.SCHEDULED


# Failure and atomicity workflows

def test_failed_dependency_operation_restores_graph_and_keeps_other_state_intact():
    app = make_facade()
    a, b = task("A"), task("B")
    event = CalendarEvent("E", "Existing", START + timedelta(hours=4), END)
    state = make_state(a, b, events=[event])
    app.apply_replanning_result(
        state, app.replan(state, PlanningChange(PlanningChangeType.PLAN_REPLACED), START, END)
    )
    # A dependency cycle fails during replanning after the first edge was staged.
    app.add_dependency(state, b, a, START, END)
    prior_plan = state.current_plan
    prior_blocks = list(prior_plan.schedule_blocks)
    observation_count = len(state.observations)

    with pytest.raises(ValueError):
        app.add_dependency(state, a, b, START, END)

    assert not state.dependency_graph.has_dependency(a, b)
    assert state.dependency_graph.has_dependency(b, a)
    assert state.current_plan is prior_plan
    assert state.current_plan.schedule_blocks == prior_blocks
    assert state.calendar_events == [event]
    assert len(state.observations) == observation_count
    assert state.tasks == [a, b]


# Identity workflows

def test_application_rejects_equal_id_foreign_task_goal_event_and_constraint():
    app = make_facade()
    owned = task("A")
    state = make_state(owned)
    foreign = task("A")
    with pytest.raises(ValueError):
        app.change_task(state, foreign, TaskUpdateRequest(title="Wrong"), START, END)
    assert state.tasks == [owned]
    assert state.dependency_graph.tasks["A"] is owned

    goal = Goal("G", "Goal")
    app.create_goal(goal, state)
    with pytest.raises(ValueError):
        app.change_goal(Goal("G", "Foreign"), state, object())
    assert state.goals == [goal]

    event = CalendarEvent("E", "Event", START, START + timedelta(minutes=30))
    app.add_calendar_event(event, state, START, END)
    with pytest.raises(ValueError):
        app.remove_calendar_event(
            CalendarEvent("E", "Foreign", START, START + timedelta(minutes=30)),
            state, START, END,
        )
    assert state.calendar_events[0] is event

    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(START + timedelta(hours=3), START + timedelta(hours=4)),
    )
    app.add_constraint(state, constraint, START, END)
    foreign_constraint = Constraint(constraint.type, constraint.rule_information)
    with pytest.raises(ValueError):
        app.remove_constraint(state, foreign_constraint, START, END)
    assert state.constraints[0] is constraint

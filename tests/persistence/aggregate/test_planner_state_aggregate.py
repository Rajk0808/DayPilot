from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import (
    ConstraintType,
    ObservationOutcome,
    SchedulingStatus,
    TaskStatus,
)
from daypilot.domain.goal import Goal
from daypilot.domain.observation import Observation
from daypilot.domain.planner import PlannerState
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task
from daypilot.domain.times import CalendarEvent, Constraint, TimeWindow
from daypilot.persistence.aggregate.planner_state import (
    PersistedPlannerState,
    from_persisted_planner_state,
    to_persisted_planner_state,
)


def make_state():
    start = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    prerequisite = Task(
        "task-a",
        "Collect data",
        status=TaskStatus.NOT_STARTED,
        scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1),
    )
    dependent = Task(
        "task-b",
        "Prepare report",
        status=TaskStatus.NOT_STARTED,
        scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1),
    )
    graph = DependencyGraph()
    graph.register_task(prerequisite)
    graph.register_task(dependent)
    graph.add_dependency(dependent, prerequisite)
    goal = Goal("goal-1", "Finish report", root_tasks=[prerequisite, dependent])
    prerequisite_block = ScheduleBlock(
        prerequisite, start, start + timedelta(hours=1), TaskStatus.NOT_STARTED
    )
    dependent_block = ScheduleBlock(
        dependent, start + timedelta(hours=1), start + timedelta(hours=2), TaskStatus.NOT_STARTED
    )
    plan = Plan(
        "plan-1", start, timedelta(hours=3),
        [prerequisite_block, dependent_block], {"kind": "daily"}
    )
    observation = Observation(
        prerequisite,
        prerequisite_block,
        start + timedelta(minutes=5),
        start + timedelta(minutes=20),
        ObservationOutcome.PARTIALLY_COMPLETED,
        {"note": "drafted"},
    )
    event = CalendarEvent(
        "event-1", "Standup", start + timedelta(hours=1), start + timedelta(hours=1, minutes=15)
    )
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(start, start + timedelta(hours=3)),
        "Available window",
    )
    return PlannerState(
        [goal], [prerequisite, dependent], graph, [event], [constraint], plan, [observation]
    )


def test_planner_state_snapshot_round_trip_preserves_graph_identity():
    state = make_state()

    snapshot = to_persisted_planner_state(state, "state-1", version=3)
    restored = from_persisted_planner_state(snapshot)

    assert snapshot.state_id == "state-1"
    assert snapshot.version == 3
    assert isinstance(restored, PlannerState)
    assert [task.id for task in restored.tasks] == ["task-a", "task-b"]
    assert restored.goals[0].id == state.goals[0].id
    assert restored.goals[0].root_tasks[0] is restored.tasks[0]
    assert restored.goals[0].root_tasks[1] is restored.tasks[1]
    assert restored.dependency_graph.tasks["task-a"] is restored.tasks[0]
    assert restored.dependency_graph.tasks["task-b"] is restored.tasks[1]
    assert restored.dependency_graph.has_dependency(restored.tasks[1], restored.tasks[0])
    assert restored.current_plan is not None
    assert restored.observations[0].scheduled_block is restored.current_plan.schedule_blocks[0]
    assert restored.observations[0].task is restored.tasks[0]
    assert restored.calendar_events[0].id == "event-1"
    assert restored.constraints[0].description == "Available window"


def test_snapshot_rejects_references_outside_the_aggregate():
    snapshot = to_persisted_planner_state(make_state(), "state-1")

    with pytest.raises(ValueError, match="goal IDs do not match"):
        replace(snapshot, goals={})


def test_snapshot_requires_nonempty_state_id_and_positive_version():
    snapshot = to_persisted_planner_state(make_state(), "state-1")

    with pytest.raises(ValueError, match="non-empty string"):
        replace(snapshot, state_id="")
    with pytest.raises(ValueError, match="positive integer"):
        replace(snapshot, version=0)

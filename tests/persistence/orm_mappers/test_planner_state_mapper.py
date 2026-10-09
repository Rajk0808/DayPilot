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
from daypilot.persistence.orm.planner_state import PlannerStateORM
from daypilot.persistence.orm_mappers.planner_state import from_orm, to_orm


def empty_snapshot():
    snapshot = to_persisted_planner_state(
        PlannerState([], [], DependencyGraph(), [], [], None, []),
        "state-empty",
        version=4,
    )
    return snapshot


def full_state():
    start = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
    parent = Task(
        "task-a",
        "Parent",
        status=TaskStatus.COMPLETED,
        estimated_duration=timedelta(hours=1),
    )
    child = Task(
        "task-child",
        "Child",
        scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(minutes=30),
    )
    parent.add_child(child)
    independent = Task(
        "task-b",
        "Independent",
        scheduling_status=SchedulingStatus.SCHEDULED,
        status=TaskStatus.NOT_STARTED,
    )
    graph = DependencyGraph()
    for item in (parent, child, independent):
        graph.register_task(item)
    graph.add_dependency(independent, parent)
    block_a = ScheduleBlock(child, start, start + timedelta(hours=1))
    block_b = ScheduleBlock(independent, start + timedelta(hours=1), start + timedelta(hours=2))
    plan = Plan("plan-1", start, timedelta(hours=3), [block_a, block_b], {"kind": "daily"})
    observation = Observation(
        child,
        block_a,
        start + timedelta(minutes=5),
        start + timedelta(minutes=25),
        ObservationOutcome.PARTIALLY_COMPLETED,
        {"note": "started"},
    )
    goal = Goal("goal-1", "Complete parent", root_tasks=[parent])
    event = CalendarEvent(
        "event-1", "Meeting", start + timedelta(hours=2), start + timedelta(hours=2, minutes=30)
    )
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(start, start + timedelta(hours=3)),
        "Work window",
    )
    return PlannerState(
        goals=[goal],
        tasks=[parent, child, independent],
        dependency_graph=graph,
        calendar_events=[event],
        constraints=[constraint],
        current_plan=plan,
        observations=[observation],
    )


def rows_to_snapshot(rows):
    return from_orm(
        rows["planner_states"][0],
        tasks=rows["tasks"],
        goals=rows["goals"],
        goal_root_tasks=rows["goal_root_tasks"],
        dependencies=rows["dependencies"],
        calendar_events=rows["calendar_events"],
        constraints=rows["constraints"],
        plans=rows["plans"],
        schedule_blocks=rows["schedule_blocks"],
        observations=rows["observations"],
    )


def test_minimal_planner_state_round_trip():
    snapshot = empty_snapshot()

    rows = to_orm(snapshot)
    restored = rows_to_snapshot(rows)

    assert restored.state_id == "state-empty"
    assert restored.version == 4
    assert restored.planner_state_record.current_plan_id is None
    assert not restored.tasks and not restored.goals and not restored.schedule_blocks


def test_full_planner_state_round_trip_preserves_records_and_graph_identity():
    original = full_state()
    snapshot = to_persisted_planner_state(original, "state-full", version=7)

    rows = to_orm(snapshot)
    assert {row.plan_id for row in rows["schedule_blocks"]} == {"plan-1"}
    restored_snapshot = rows_to_snapshot(rows)
    restored = from_persisted_planner_state(restored_snapshot)

    assert restored_snapshot.version == 7
    assert restored_snapshot.planner_state_record.current_plan_id == "plan-1"
    assert restored_snapshot.planner_state_record.task_ids == ["task-a", "task-child", "task-b"]
    assert restored_snapshot.planner_state_record.goal_ids == ["goal-1"]
    assert restored_snapshot.planner_state_record.dependency_ids == snapshot.planner_state_record.dependency_ids
    assert restored_snapshot.planner_state_record.calendar_event_ids == ["event-1"]
    assert restored_snapshot.planner_state_record.constraint_ids == snapshot.planner_state_record.constraint_ids
    assert restored_snapshot.planner_state_record.observation_ids == snapshot.planner_state_record.observation_ids

    task_a = restored.tasks[0]
    assert task_a.children[0] is restored.tasks[1]
    assert restored.goals[0].root_tasks[0] is task_a
    assert restored.dependency_graph.tasks["task-a"] is task_a
    assert restored.dependency_graph.has_dependency(restored.tasks[2], task_a)
    assert restored.current_plan is not None
    observed_block = restored.observations[0].scheduled_block
    assert observed_block is restored.current_plan.schedule_blocks[0]
    assert restored.observations[0].task is restored.tasks[1]
    assert restored.constraints[0].description == "Work window"
    assert restored.calendar_events[0].id == "event-1"


def test_from_orm_rejects_rows_owned_by_another_state():
    rows = to_orm(to_persisted_planner_state(full_state(), "state-full"))
    other = PlannerStateORM(id="state-other", version=1)

    with pytest.raises(ValueError, match="another planner state"):
        from_orm(
            other,
            tasks=rows["tasks"], goals=rows["goals"], goal_root_tasks=rows["goal_root_tasks"],
            dependencies=rows["dependencies"], calendar_events=rows["calendar_events"],
            constraints=rows["constraints"], plans=rows["plans"],
            schedule_blocks=rows["schedule_blocks"], observations=rows["observations"],
        )


def test_malformed_missing_block_reference_fails_loudly():
    snapshot = to_persisted_planner_state(full_state(), "state-full")
    rows = to_orm(snapshot)
    rows["schedule_blocks"].clear()

    with pytest.raises(ValueError, match="Schedule block records do not match"):
        rows_to_snapshot(rows)


def test_mapper_does_not_import_application_modules():
    from pathlib import Path

    source = Path(__file__).parents[3] / "src/daypilot/persistence/orm_mappers/planner_state.py"
    contents = source.read_text(encoding="utf-8")
    assert "daypilot.application" not in contents

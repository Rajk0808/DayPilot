from datetime import datetime, timedelta, timezone

import pytest

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import (
    ConstraintType,
    ObservationOutcome,
    SchedulingStatus,
)
from daypilot.domain.goal import Goal
from daypilot.domain.observation import Observation
from daypilot.domain.planner import PlannerState
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task
from daypilot.domain.times import CalendarEvent, Constraint, TimeWindow


@pytest.fixture
def complete_planner_state():
    start = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
    task_one = Task("T1", "Prepare", estimated_duration=timedelta(hours=1))
    task_two = Task(
        "T2",
        "Draft",
        scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1),
    )
    task_three = Task(
        "T3",
        "Review",
        scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1),
    )
    task_one.add_child(task_two)

    dependencies = DependencyGraph()
    for task in (task_one, task_two, task_three):
        dependencies.register_task(task)
    # DependencyGraph disallows dependencies within the same task tree, so
    # this edge connects T3 to T2 while T2 remains a child of T1.
    dependencies.add_dependency(task_three, task_two)

    goal = Goal("G1", "Finish the report", root_tasks=[task_one, task_three])
    block_one = ScheduleBlock(task_two, start, start + timedelta(hours=1))
    block_two = ScheduleBlock(
        task_three,
        start + timedelta(hours=1),
        start + timedelta(hours=2),
    )
    plan = Plan("P1", start, timedelta(hours=3), [block_one, block_two], {"source": "test"})
    observation = Observation(
        task=task_two,
        scheduled_block=block_one,
        actual_start=start + timedelta(minutes=5),
        actual_end=start + timedelta(minutes=25),
        outcome=ObservationOutcome.PARTIALLY_COMPLETED,
        metadata={"note": "first draft"},
    )
    event = CalendarEvent(
        "E1",
        "Team meeting",
        start + timedelta(hours=2),
        start + timedelta(hours=2, minutes=30),
        {"calendar": "work"},
    )
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(start, start + timedelta(hours=3)),
        "Available work window",
    )
    return PlannerState(
        goals=[goal],
        tasks=[task_one, task_two, task_three],
        dependency_graph=dependencies,
        calendar_events=[event],
        constraints=[constraint],
        current_plan=plan,
        observations=[observation],
    )

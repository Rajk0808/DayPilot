from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from daypilot.domain.enums import ConstraintType, Priority, SchedulingStatus, TaskStatus
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.schedule import (
    Plan,
    ScheduleBlock,
    SchedulingCandidate,
    SchedulingRunResult,
    evaluate_soft_constraints,
    schedule_tasks,
)
from daypilot.domain.task import Task
from daypilot.domain.times import Constraint, TimeWindow


UTC = timezone.utc
TEST_DATE = (2026, 9, 28)


def dt(hour: int, minute: int = 0) -> datetime:
    """Create a timezone-aware datetime on the fixed test date."""
    return datetime(*TEST_DATE, hour, minute, tzinfo=UTC)


def make_task(
    task_id: str,
    title: str | None = None,
    *,
    duration_minutes: int,
    priority: Priority = Priority.MEDIUM,
    status: TaskStatus = TaskStatus.NOT_STARTED,
) -> Task:
    """Create the minimum valid task needed by the scheduler."""
    return Task(
        id=task_id,
        title=title or task_id,
        status=status,
        priority=priority,
        estimated_duration=timedelta(minutes=duration_minutes),
    )


def blocks_for(result: SchedulingRunResult) -> list[tuple[str, datetime, datetime]]:
    """Return a compact representation useful for assertions."""
    return [
        (block.task.id, block.start, block.end)
        for block in result.scheduled_blocks
    ]


# ---------------------------------------------------------------------------
# Basic scheduling
# ---------------------------------------------------------------------------

def test_empty_tasks_produces_no_schedule_blocks():
    windows = [TimeWindow(dt(9), dt(10))]

    assert schedule_tasks([], windows) == []


def test_empty_windows_produces_no_schedule_blocks():
    task = make_task(
        "A",
        "Study Graphs",
        duration_minutes=60,
        priority=Priority.HIGH,
    )

    assert schedule_tasks([task], []) == []


def test_task_exactly_fits_window():
    task = make_task(
        "A",
        "Study Graphs",
        duration_minutes=60,
        priority=Priority.HIGH,
    )
    window = TimeWindow(dt(9), dt(10))

    result = schedule_tasks([task], [window])

    assert len(result) == 1

    block = result[0]
    assert block.task is task
    assert block.start == dt(9)
    assert block.end == dt(10)


def test_task_shorter_than_window_occupies_only_required_duration():
    task = make_task(
        "A",
        "Study Graphs",
        duration_minutes=45,
        priority=Priority.HIGH,
    )
    window = TimeWindow(dt(9), dt(10))

    result = schedule_tasks([task], [window])

    assert len(result) == 1
    assert result[0].start == dt(9)
    assert result[0].end == dt(9, 45)


def test_task_that_does_not_fit_is_left_unscheduled():
    task = make_task(
        "A",
        "Deep Work",
        duration_minutes=90,
        priority=Priority.HIGH,
    )
    window = TimeWindow(dt(9), dt(10))

    result = schedule_tasks([task], [window])

    assert result == []


def test_every_unscheduled_task_is_reported_exactly_once():
    tasks = [
        make_task("A", duration_minutes=60),
        make_task("B", duration_minutes=60),
        make_task("C", duration_minutes=60),
    ]

    result = schedule_tasks(tasks, [TimeWindow(dt(9), dt(10))])

    assert len(result.scheduled_blocks) == 1
    assert result.scheduled_blocks[0].task is tasks[0]
    assert [item.task for item in result.unresolved_task_results] == tasks[1:]
    assert len(result.unresolved_task_results) == len(tasks[1:])


# ---------------------------------------------------------------------------
# Priority and tie-breaking
# ---------------------------------------------------------------------------

def test_higher_priority_task_beats_lower_priority_task():
    low = make_task(
        "A",
        "Low Task",
        duration_minutes=30,
        priority=Priority.LOW,
    )
    high = make_task(
        "B",
        "High Task",
        duration_minutes=30,
        priority=Priority.HIGH,
    )
    window = TimeWindow(dt(9), dt(10))

    result = schedule_tasks([low, high], [window])

    assert len(result) == 2
    assert result[0].task is high
    assert result[1].task is low


def test_critical_priority_beats_high_priority():
    high = make_task(
        "A",
        "High Task",
        duration_minutes=30,
        priority=Priority.HIGH,
    )
    critical = make_task(
        "B",
        "Critical Task",
        duration_minutes=30,
        priority=Priority.CRITICAL,
    )
    window = TimeWindow(dt(9), dt(10))

    result = schedule_tasks([high, critical], [window])

    assert len(result) == 2
    assert result[0].task is critical
    assert result[1].task is high


def test_priority_is_considered_before_duration():
    high_long = make_task(
        "A",
        "High Long",
        duration_minutes=50,
        priority=Priority.HIGH,
    )
    medium_short = make_task(
        "B",
        "Medium Short",
        duration_minutes=20,
        priority=Priority.MEDIUM,
    )
    window = TimeWindow(dt(9), dt(10))

    result = schedule_tasks([medium_short, high_long], [window])

    assert len(result) == 1
    assert result[0].task is high_long


def test_shorter_duration_breaks_equal_priority_tie():
    high_long = make_task(
        "A",
        "High Long",
        duration_minutes=45,
        priority=Priority.HIGH,
    )
    high_short = make_task(
        "B",
        "High Short",
        duration_minutes=30,
        priority=Priority.HIGH,
    )
    window = TimeWindow(dt(9), dt(10))

    result = schedule_tasks([high_long, high_short], [window])

    assert len(result) == 1
    assert result[0].task is high_short


def test_equal_priority_and_duration_preserves_input_order():
    first = make_task(
        "A",
        "First",
        duration_minutes=30,
        priority=Priority.HIGH,
    )
    second = make_task(
        "B",
        "Second",
        duration_minutes=30,
        priority=Priority.HIGH,
    )
    window = TimeWindow(dt(9), dt(10))

    result = schedule_tasks([first, second], [window])

    assert len(result) == 2
    assert result[0].task is first
    assert result[1].task is second


# ---------------------------------------------------------------------------
# Multiple tasks in one window
# ---------------------------------------------------------------------------

def test_multiple_tasks_fill_one_window_sequentially():
    first = make_task(
        "A",
        "First",
        duration_minutes=60,
        priority=Priority.HIGH,
    )
    second = make_task(
        "B",
        "Second",
        duration_minutes=30,
        priority=Priority.MEDIUM,
    )
    window = TimeWindow(dt(9), dt(11))

    result = schedule_tasks([first, second], [window])

    assert blocks_for(result) == [
        ("A", dt(9), dt(10)),
        ("B", dt(10), dt(10, 30)),
    ]


def test_multiple_blocks_in_same_window_do_not_overlap():
    first = make_task(
        "A",
        "First",
        duration_minutes=60,
        priority=Priority.HIGH,
    )
    second = make_task(
        "B",
        "Second",
        duration_minutes=30,
        priority=Priority.MEDIUM,
    )
    third = make_task(
        "C",
        "Third",
        duration_minutes=20,
        priority=Priority.LOW,
    )
    window = TimeWindow(dt(9), dt(11))

    result = schedule_tasks([first, second, third], [window])

    assert len(result) == 3

    for previous, current in zip(result, result[1:]):
        assert previous.end <= current.start


def test_remaining_time_is_used_for_another_task():
    first = make_task(
        "A",
        "High Task",
        duration_minutes=75,
        priority=Priority.HIGH,
    )
    second = make_task(
        "B",
        "Small Task",
        duration_minutes=15,
        priority=Priority.LOW,
    )
    window = TimeWindow(dt(9), dt(10, 30))

    result = schedule_tasks([first, second], [window])

    assert blocks_for(result) == [
        ("A", dt(9), dt(10, 15)),
        ("B", dt(10, 15), dt(10, 30)),
    ]


def test_task_is_scheduled_at_most_once():
    task = make_task(
        "A",
        "Only Once",
        duration_minutes=30,
        priority=Priority.HIGH,
    )

    windows = [
        TimeWindow(dt(9), dt(10)),
        TimeWindow(dt(11), dt(12)),
    ]

    result = schedule_tasks([task], windows)

    assert len(result) == 1
    assert result[0].task is task


# ---------------------------------------------------------------------------
# Multiple windows
# ---------------------------------------------------------------------------

def test_tasks_are_scheduled_across_multiple_windows():
    first = make_task(
        "A",
        "First",
        duration_minutes=60,
        priority=Priority.HIGH,
    )
    second = make_task(
        "B",
        "Second",
        duration_minutes=30,
        priority=Priority.MEDIUM,
    )
    third = make_task(
        "C",
        "Third",
        duration_minutes=45,
        priority=Priority.LOW,
    )

    windows = [
        TimeWindow(dt(9), dt(10)),
        TimeWindow(dt(11), dt(12)),
    ]

    result = schedule_tasks([first, second, third], windows)

    assert blocks_for(result) == [
        ("A", dt(9), dt(10)),
        ("B", dt(11), dt(11, 30)),
    ]

    assert third not in [block.task for block in result]


def test_task_is_not_placed_outside_a_later_window():
    first = make_task(
        "A",
        "First",
        duration_minutes=60,
        priority=Priority.HIGH,
    )
    second = make_task(
        "B",
        "Second",
        duration_minutes=45,
        priority=Priority.MEDIUM,
    )

    windows = [
        TimeWindow(dt(9), dt(10)),
        TimeWindow(dt(11), dt(11, 30)),
    ]

    result = schedule_tasks([first, second], windows)

    assert blocks_for(result) == [
        ("A", dt(9), dt(10)),
    ]


# ---------------------------------------------------------------------------
# ScheduleBlock invariants
# ---------------------------------------------------------------------------

def test_schedule_block_contains_atomic_task():
    task = make_task(
        "A",
        "Study",
        duration_minutes=30,
        priority=Priority.HIGH,
    )

    block = ScheduleBlock(
        task=task,
        start=dt(9),
        end=dt(9, 30),
    )

    assert block.task is task


def test_schedule_block_rejects_naive_datetimes():
    task = make_task("A", duration_minutes=30)

    with pytest.raises(ValueError, match="timezone-aware"):
        ScheduleBlock(task, datetime(2026, 9, 28, 9), dt(9, 30))


def test_schedule_block_matches_task_duration():
    task = make_task(
        "A",
        "Study",
        duration_minutes=45,
        priority=Priority.HIGH,
    )

    result = schedule_tasks(
        [task],
        [TimeWindow(dt(9), dt(10))],
    )

    assert len(result) == 1
    assert result[0].end - result[0].start == task.estimated_duration


def test_schedule_block_stays_inside_time_window():
    task = make_task(
        "A",
        "Study",
        duration_minutes=45,
        priority=Priority.HIGH,
    )
    window = TimeWindow(dt(9), dt(10))

    result = schedule_tasks([task], [window])

    assert len(result) == 1
    block = result[0]

    assert window.start <= block.start
    assert block.end <= window.end


def test_scheduler_respects_transitive_dependencies_without_mutating_tasks():
    first, second, third = [
        make_task(task_id, duration_minutes=30, priority=Priority.MEDIUM)
        for task_id in ("A", "B", "C")
    ]
    graph = DependencyGraph()
    for task in (first, second, third):
        graph.register_task(task)
    graph.add_dependency(second, first)
    graph.add_dependency(third, second)

    result = schedule_tasks(
        [third, second, first],
        [TimeWindow(dt(9), dt(11))],
        [],
        graph,
    )
    assert [block.task for block in result] == [first, second, third]
    assert all(task.scheduling_status is SchedulingStatus.UNSCHEDULED
               for task in (first, second, third))


@pytest.mark.parametrize("metadata", [None, [], {1: "value"}, {"key": 1}])
def test_plan_rejects_invalid_metadata(metadata):
    with pytest.raises(ValueError, match="metadata"):
        Plan("plan", dt(9), timedelta(hours=2), [], metadata)


@pytest.mark.parametrize(
    ("plan_id", "horizon"),
    [(None, timedelta(hours=1)), ("", timedelta(hours=1)), ("plan", None)],
)
def test_plan_rejects_invalid_identity_or_horizon(plan_id, horizon):
    with pytest.raises(ValueError):
        Plan(plan_id, dt(9), horizon, [], {})


def test_scheduling_candidate_duration_controls_placement_length():
    task = make_task("A", duration_minutes=120)
    graph = DependencyGraph()
    graph.register_task(task)

    result = schedule_tasks(
        [SchedulingCandidate(task, timedelta(minutes=45))],
        [TimeWindow(dt(9), dt(10))],
        [],
        graph,
    )

    assert result[0].end - result[0].start == timedelta(minutes=45)


@pytest.mark.parametrize("duration", [timedelta(0), timedelta(minutes=-1)])
def test_scheduling_candidate_rejects_non_positive_duration(duration):
    task = make_task("A", duration_minutes=30)

    with pytest.raises(ValueError, match="positive"):
        SchedulingCandidate(task, duration)


def test_soft_constraint_preference_can_move_task_later_within_window():
    task = make_task("A", duration_minutes=60)
    graph = DependencyGraph()
    graph.register_task(task)
    preference = Constraint(
        ConstraintType.SOFT_CONSTRAINT,
        TimeWindow(dt(11), dt(12)),
    )

    result = schedule_tasks(
        [task], [TimeWindow(dt(9), dt(13))], [preference], graph
    )

    assert result[0].start == dt(11)


def test_dependency_earliest_start_interacts_with_soft_preference():
    prerequisite = make_task("A", duration_minutes=60)
    dependent = make_task("B", duration_minutes=60)
    graph = DependencyGraph()
    graph.register_task(prerequisite)
    graph.register_task(dependent)
    graph.add_dependency(dependent, prerequisite)
    prerequisite_block = ScheduleBlock(prerequisite, dt(9), dt(10))
    preference = Constraint(
        ConstraintType.SOFT_CONSTRAINT,
        TimeWindow(dt(9), dt(12)),
    )

    result = schedule_tasks(
        [dependent],
        [TimeWindow(dt(9), dt(12))],
        [preference],
        graph,
        [prerequisite_block],
    )

    assert len(result.scheduled_blocks) == 1
    assert result.scheduled_blocks[0].task is dependent
    assert result.scheduled_blocks[0].start == dt(10)
    assert evaluate_soft_constraints(
        result.scheduled_blocks[0].start,
        result.scheduled_blocks[0].end,
        [preference],
    ) == 1


def test_dependent_can_start_exactly_at_prerequisite_end():
    prerequisite = make_task("A", duration_minutes=60)
    dependent = make_task("B", duration_minutes=60)
    graph = DependencyGraph()
    graph.register_task(prerequisite)
    graph.register_task(dependent)
    graph.add_dependency(dependent, prerequisite)

    result = schedule_tasks(
        [dependent],
        [TimeWindow(dt(9), dt(12))],
        [],
        graph,
        [ScheduleBlock(prerequisite, dt(9), dt(10))],
    )

    assert result.scheduled_blocks[0].start == dt(10)
    assert result.scheduled_blocks[0].end == dt(11)


def test_short_soft_preference_does_not_block_scheduling():
    task = make_task("A", duration_minutes=60)
    graph = DependencyGraph()
    graph.register_task(task)
    preference = Constraint(
        ConstraintType.SOFT_CONSTRAINT,
        TimeWindow(dt(10), dt(10, 30)),
    )

    result = schedule_tasks(
        [task],
        [TimeWindow(dt(9), dt(12))],
        [preference],
        graph,
    )

    assert len(result.scheduled_blocks) == 1
    assert result.scheduled_blocks[0].end - result.scheduled_blocks[0].start == timedelta(hours=1)


def test_scheduler_avoids_overlap_with_supplied_scheduled_blocks():
    task = make_task("A", duration_minutes=60)
    existing = make_task("existing", duration_minutes=60)
    graph = DependencyGraph()
    graph.register_task(task)
    graph.register_task(existing)
    existing_block = ScheduleBlock(existing, dt(9), dt(10))

    result = schedule_tasks(
        [task],
        [TimeWindow(dt(9), dt(12))],
        [],
        graph,
        [existing_block],
    )

    assert len(result.scheduled_blocks) == 1
    assert result.scheduled_blocks[0].start == dt(10)
    assert result.scheduled_blocks[0].end == dt(11)


def test_scheduler_rejects_none_window_and_soft_constraint_entries():
    with pytest.raises(ValueError, match="Time windows cannot contain None"):
        schedule_tasks([], cast(list[TimeWindow], [None]))
    with pytest.raises(ValueError, match="Soft constraints cannot contain None"):
        schedule_tasks([], [], cast(list[Constraint], [None]))



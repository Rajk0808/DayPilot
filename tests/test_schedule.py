from datetime import datetime, timedelta, timezone

import pytest

from daypilot.domain.enums import Priority, TaskStatus
from daypilot.domain.schedule import ScheduleBlock, schedule_tasks
from daypilot.domain.task import Task
from daypilot.domain.times import TimeWindow


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


def blocks_for(result: list[ScheduleBlock]) -> list[tuple[str, datetime, datetime]]:
    """Return a compact representation useful for assertions."""
    return [(block.task.id, block.start, block.end) for block in result]


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
    assert block.status == task.status


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
        status=TaskStatus.NOT_STARTED,
    )

    assert block.task is task


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



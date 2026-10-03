from datetime import datetime, timedelta, timezone

import pytest

from daypilot.domain.enums import ConstraintType, Priority
from daypilot.domain.schedule import ScheduleBlock, consume_timewindow
from daypilot.domain.task import Task
from daypilot.domain.times import (
    CalendarEvent,
    Constraint,
    TimeWindow,
    generate_time_windows,
)


DATE = datetime(2026, 9, 28, tzinfo=timezone.utc)


def block(start: datetime, end: datetime) -> ScheduleBlock:
    task = Task("A", "A", priority=Priority.MEDIUM, estimated_duration=end - start)
    return ScheduleBlock(task, start, end)


def test_generate_windows_subtracts_and_merges_busy_intervals():
    windows = generate_time_windows(
        DATE,
        DATE + timedelta(hours=5),
        [
            CalendarEvent("a", "a", DATE + timedelta(hours=1), DATE + timedelta(hours=2)),
            CalendarEvent("b", "b", DATE + timedelta(hours=2), DATE + timedelta(hours=3)),
        ],
        [Constraint(ConstraintType.HARD_CONSTRAINT, TimeWindow(
            DATE + timedelta(hours=4), DATE + timedelta(hours=5)
        ))],
    )

    assert [(window.start, window.end) for window in windows] == [
        (DATE, DATE + timedelta(hours=1)),
        (DATE + timedelta(hours=3), DATE + timedelta(hours=4)),
    ]


@pytest.mark.parametrize(
    ("start_hour", "end_hour", "expected"),
    [
        (9, 10, []),
        (9, 9.5, [(9.5, 10)]),
        (9.5, 10, [(9, 9.5)]),
        (9.25, 9.75, [(9, 9.25), (9.75, 10)]),
    ],
)
def test_consume_timewindow_preserves_unused_parts(start_hour, end_hour, expected):
    window = TimeWindow(DATE + timedelta(hours=9), DATE + timedelta(hours=10))
    consumed = consume_timewindow(
        window,
        block(DATE + timedelta(hours=start_hour), DATE + timedelta(hours=end_hour)),
    )
    assert [(item.start.hour + item.start.minute / 60,
             item.end.hour + item.end.minute / 60) for item in consumed] == expected


def test_consume_timewindow_rejects_block_outside_window():
    window = TimeWindow(DATE + timedelta(hours=9), DATE + timedelta(hours=10))
    with pytest.raises(ValueError, match="within the time window"):
        consume_timewindow(
            window,
            block(DATE + timedelta(hours=8), DATE + timedelta(hours=9, minutes=30)),
        )


def test_time_window_timestamps_must_be_aware_and_non_null():
    with pytest.raises(ValueError):
        TimeWindow(None, DATE + timedelta(hours=1))
    with pytest.raises(ValueError):
        TimeWindow(datetime(2026, 9, 28), DATE + timedelta(hours=1))

from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from daypilot.domain.enums import ObservationOutcome, TaskStatus
from daypilot.domain.observation import (
    Observation,
    ObservationHistorySummary,
    calculate_observation_history,
    calculate_observation_history_summary,
    validate_observation_history,
)
from daypilot.domain.schedule import ScheduleBlock
from daypilot.domain.task import Task


START = datetime(2026, 10, 2, 9, tzinfo=timezone.utc)
_DEFAULT_METADATA = object()


def make_observation(
    task, offset_minutes, outcome, duration_minutes=30, metadata=_DEFAULT_METADATA
):
    block = ScheduleBlock(task, START, START + timedelta(hours=2))
    start = START + timedelta(minutes=offset_minutes)
    return Observation(
        task,
        block,
        start,
        start + timedelta(minutes=duration_minutes),
        outcome,
        metadata=(
            {}
            if metadata is _DEFAULT_METADATA
            else cast(dict[str, Any], metadata)
        ),
    )


def test_observation_rejects_none_metadata():
    task = Task("task", "Task", estimated_duration=timedelta(hours=2))
    with pytest.raises(ValueError, match="metadata"):
        make_observation(task, 0, ObservationOutcome.NOT_STARTED, metadata=None)


def test_calculate_observation_history_validates_terminal_order_standalone():
    task = Task("task", "Task", estimated_duration=timedelta(hours=2))
    history = [
        make_observation(task, 0, ObservationOutcome.PARTIALLY_COMPLETED),
        make_observation(task, 30, ObservationOutcome.COMPLETED),
        make_observation(task, 60, ObservationOutcome.PARTIALLY_COMPLETED),
    ]

    with pytest.raises(ValueError, match="after a completed or cancelled"):
        calculate_observation_history(task, history)


def test_not_started_observation_cannot_follow_execution():
    task = Task("task", "Task", estimated_duration=timedelta(hours=2))
    history = [
        make_observation(task, 0, ObservationOutcome.PARTIALLY_COMPLETED),
        make_observation(task, 30, ObservationOutcome.NOT_STARTED),
    ]

    with pytest.raises(ValueError, match="after execution has begun"):
        validate_observation_history(task, history)


def test_completed_observation_sets_terminal_status_and_zero_remaining_work():
    task = Task("task", "Task", estimated_duration=timedelta(hours=2))
    observation = make_observation(task, 0, ObservationOutcome.COMPLETED)

    from daypilot.domain.observation import process_observation

    process_observation(task, observation)

    assert task.status is TaskStatus.COMPLETED
    assert observation.remaining_duration == timedelta(0)


def test_multiple_partial_observations_reduce_remaining_duration():
    task = Task("task", "Task", estimated_duration=timedelta(hours=2))
    first = make_observation(task, 0, ObservationOutcome.PARTIALLY_COMPLETED, 30)
    second = make_observation(task, 30, ObservationOutcome.PARTIALLY_COMPLETED, 45)

    summary = calculate_observation_history(task, [first, second])

    assert summary == (timedelta(minutes=75), timedelta(minutes=45))


def test_repeated_partial_observations_followed_by_completion_have_zero_remaining():
    task = Task("task", "Task", estimated_duration=timedelta(hours=2))
    first = make_observation(task, 0, ObservationOutcome.PARTIALLY_COMPLETED, 30)
    second = make_observation(task, 30, ObservationOutcome.PARTIALLY_COMPLETED, 45)
    completed = make_observation(task, 75, ObservationOutcome.COMPLETED, 15)

    summary = calculate_observation_history_summary(task, [first, second, completed])

    assert summary.total_actual_duration == timedelta(minutes=90)
    assert summary.remaining_duration == timedelta(0)
    assert summary.final_outcome is ObservationOutcome.COMPLETED


def test_not_started_observation_preserves_estimated_remaining_duration():
    task = Task("task", "Task", estimated_duration=timedelta(hours=2))
    observation = make_observation(task, 0, ObservationOutcome.NOT_STARTED, 30)

    total, remaining = calculate_observation_history(task, [observation])

    assert total == timedelta(minutes=30)
    assert remaining == timedelta(hours=2)


def test_terminal_task_rejects_later_observation_even_without_history():
    task = Task(
        "task",
        "Task",
        status=TaskStatus.COMPLETED,
        estimated_duration=timedelta(hours=2),
    )
    observation = make_observation(task, 0, ObservationOutcome.PARTIALLY_COMPLETED)

    from daypilot.domain.observation import process_observation

    with pytest.raises(ValueError, match="terminal"):
        process_observation(task, observation)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"total_actual_duration": timedelta(minutes=-1), "remaining_duration": timedelta(0), "final_outcome": ObservationOutcome.NOT_STARTED},
        {"total_actual_duration": timedelta(0), "remaining_duration": timedelta(minutes=-1), "final_outcome": ObservationOutcome.NOT_STARTED},
        {"total_actual_duration": timedelta(0), "remaining_duration": timedelta(0), "final_outcome": None},
    ],
)
def test_observation_history_summary_rejects_invalid_values(kwargs):
    with pytest.raises(ValueError):
        ObservationHistorySummary(**kwargs)

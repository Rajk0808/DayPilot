from typing import Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from daypilot.domain.enums import ObservationOutcome, SchedulingStatus, TaskStatus
from daypilot.domain.schedule import ScheduleBlock
from daypilot.domain.task import Task

@dataclass
class Observation:
    task: Task
    scheduled_block: ScheduleBlock
    actual_start: datetime
    actual_end: datetime
    outcome: ObservationOutcome
    metadata: dict[str, Any] = field(default_factory=dict)

    
    def __post_init__(self) -> None:
        if self.task is None:
            raise ValueError(
                "Task provided is None."
            )
        if self.scheduled_block is None:
            raise ValueError(
                "Scheduled block provided is None."
            )
        if self.task is not self.scheduled_block.task:
            raise ValueError(
                "Scheduled Block doesn't belongs to the task provided."
            )
        if self.metadata is None:
            raise ValueError("Observation metadata cannot be None.")
        for name in ("actual_start", "actual_end"):
            timestamp = getattr(self, name)
            if timestamp is None:
                raise ValueError(f"{name.replace('_', ' ').capitalize()} cannot be None.")
            if timestamp.utcoffset() is None:
                raise ValueError(f"{name.replace('_', ' ').capitalize()} must be timezone-aware.")
            setattr(self, name, timestamp.astimezone(timezone.utc))
        if not isinstance(self.outcome, ObservationOutcome):
            raise ValueError("Observation outcome must be valid.")
        if self.actual_start >= self.actual_end:
            raise ValueError(
                "Provided start and end are not valid."
            )

    @property
    def start_delay(self) -> timedelta:
        return self.actual_start - self.scheduled_block.start

    @property
    def actual_duration(self) -> timedelta:
        return self.actual_end - self.actual_start

    @property
    def duration_difference(self) -> timedelta:
        return self.actual_duration - (self.scheduled_block.end - self.scheduled_block.start)

    @property
    def execution_deviation(self) -> "ExecutionDeviation":
        return ExecutionDeviation(
            start_delay=self.start_delay,
            duration_difference=self.duration_difference
        )

    @property
    def remaining_duration(self) -> timedelta:
        if self.outcome == ObservationOutcome.COMPLETED:
            return timedelta(0)
        elif self.outcome == ObservationOutcome.PARTIALLY_COMPLETED:
            planned_duration = self.scheduled_block.end - self.scheduled_block.start
            return max(timedelta(0), planned_duration - self.actual_duration)
        elif self.outcome == ObservationOutcome.CANCELLED:
            return timedelta(0)
        else:  # NOT_STARTED
            return max(timedelta(0), self.scheduled_block.end - self.scheduled_block.start)

@dataclass(frozen=True)
class ExecutionDeviation:
    start_delay: timedelta
    duration_difference: timedelta

    def __post_init__(self):
        if not isinstance(self.start_delay, timedelta):
            raise TypeError("start_delay must be a timedelta.")
        if not isinstance(self.duration_difference, timedelta):
            raise TypeError("duration_difference must be a timedelta.")

    @property
    def is_delay(self) -> bool:
        return self.start_delay > timedelta(0)

    @property
    def is_early(self) -> bool:
        return self.start_delay < timedelta(0)

    @property
    def overran(self) -> bool:
        return self.duration_difference > timedelta(0)

    @property
    def underran(self) -> bool:
        return self.duration_difference < timedelta(0)

@dataclass(frozen=True)
class ObservationHistorySummary:
    total_actual_duration: timedelta
    remaining_duration: timedelta
    final_outcome: ObservationOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.total_actual_duration, timedelta):
            raise ValueError("Total actual duration must be a timedelta.")
        if self.total_actual_duration < timedelta(0):
            raise ValueError("Total actual duration cannot be negative.")
        if not isinstance(self.remaining_duration, timedelta):
            raise ValueError("Remaining duration must be a timedelta.")
        if self.remaining_duration < timedelta(0):
            raise ValueError("Remaining duration cannot be negative.")
        if not isinstance(self.final_outcome, ObservationOutcome):
            raise ValueError("Final outcome must be valid.")

def apply_observation(task, observation) -> None:
    if task is None or observation is None:
        raise ValueError("Task and Observation cannot be None.")
    if not task is observation.task:
        raise ValueError("Observation does not belong to the provided task.")
    if observation.outcome == ObservationOutcome.COMPLETED:
        task.status = TaskStatus.COMPLETED
    elif observation.outcome == ObservationOutcome.PARTIALLY_COMPLETED:
        task.status = TaskStatus.IN_PROGRESS
    elif observation.outcome == ObservationOutcome.CANCELLED:
        task.status = TaskStatus.CANCELLED
    else:
        task.status = TaskStatus.NOT_STARTED


def validate_observation_transition(task: Task, observation: Observation) -> None:
    if task is None or observation is None:
        raise ValueError("Task and Observation cannot be None.")
    if task is not observation.task:
        raise ValueError("Observation does not belong to the provided task.")
    if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        raise ValueError("A terminal task cannot receive another observation.")
    if task.status is TaskStatus.IN_PROGRESS and observation.outcome is ObservationOutcome.NOT_STARTED:
        raise ValueError("NOT_STARTED observation cannot regress an in-progress task.")

def resolve_scheduling_status(task, observation) -> None:
    if task is None or observation is None:
        raise ValueError("Task and Observation cannot be None.")
    if task is not observation.task:
        raise ValueError("Observation does not belong to the provided task.")
    task.scheduling_status = SchedulingStatus.UNSCHEDULED



def process_observation(task: Task, observation: Observation) -> None:
    if task is None or observation is None:
        raise ValueError("Task and Observation cannot be None.")
    if task is not observation.task:
        raise ValueError("Observation does not belong to the provided task.")
    validate_observation_transition(task, observation)
    apply_observation(task, observation)
    resolve_scheduling_status(task, observation)


def calculate_observation_history(
    task: Task,
    observations: list[Observation],
) -> tuple[timedelta, timedelta]:
    """Return (total actual time, remaining estimate) for a task's history."""
    if task is None:
        raise ValueError("Task cannot be None.")
    if observations is None:
        raise ValueError("Observations cannot be None.")
    validate_observation_history(task, observations)

    total_actual_duration = timedelta(0)
    completed = False
    cancelled = False
    work_done_duration = timedelta(0)

    for observation in observations:
        if observation is None:
            raise ValueError("Observations cannot contain None.")
        if observation.task is not task:
            raise ValueError("Observation does not belong to the provided task.")
        total_actual_duration += observation.actual_duration
        if observation.outcome == ObservationOutcome.COMPLETED:
            completed = True
        elif observation.outcome == ObservationOutcome.CANCELLED:
            cancelled = True
        elif observation.outcome == ObservationOutcome.PARTIALLY_COMPLETED:
            work_done_duration += observation.actual_duration

    if completed or cancelled:
        remaining_duration = timedelta(0)
    else:
        remaining_duration = max(
            timedelta(0), task.estimated_duration - work_done_duration
        )
    return total_actual_duration, remaining_duration


def validate_observation_history(
    task: Task,
    observations: list[Observation]
) -> None:
    if task is None:
        raise ValueError("Task cannot be None.")
    if observations is None:
        raise ValueError("Observations cannot be None.")
    if len(observations) == 0:
        raise ValueError("Observations cannot be empty.")
    for observation in observations:
        if observation is None:
            raise ValueError("Observations cannot contain None.")
        if observation.task is not task:
            raise ValueError("Observation does not belong to the provided task.")
    for previous, current in zip(observations, observations[1:]):
        if previous.actual_start > current.actual_start:
            raise ValueError("Observations must be in chronological order.")
        if previous.actual_end > current.actual_start:
            raise ValueError("Observations must be chronological and non-overlapping.")

    seen_execution = False
    for index, observation in enumerate(observations):
        if observation.outcome is ObservationOutcome.NOT_STARTED and seen_execution:
            raise ValueError("NOT_STARTED observation cannot occur after execution has begun.")
        if observation.outcome is not ObservationOutcome.NOT_STARTED:
            seen_execution = True
        if index < len(observations) - 1 and observation.outcome in (
            ObservationOutcome.COMPLETED,
            ObservationOutcome.CANCELLED,
        ):
            raise ValueError("Observations after a completed or cancelled observation are not allowed.")


def  calculate_observation_history_summary(
    task: Task,
    observations: list[Observation],
) -> ObservationHistorySummary:
    total_actual_duration, remaining_duration = calculate_observation_history(task, observations)
    final_outcome = observations[-1].outcome
    if final_outcome is ObservationOutcome.COMPLETED:
        remaining_duration = timedelta(0)
    return ObservationHistorySummary(
        total_actual_duration=total_actual_duration,
        remaining_duration=remaining_duration,
        final_outcome=final_outcome
    )

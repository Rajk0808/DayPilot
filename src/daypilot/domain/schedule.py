from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from daypilot.domain.times import TimeWindow

from .enums import Priority, TaskStatus
from .task import Task


_PRIORITY_ORDER = {
    Priority.CRITICAL: 0,
    Priority.HIGH: 1,
    Priority.MEDIUM: 2,
    Priority.LOW: 3,
}


def _normalize_timestamp(value: datetime) -> datetime:
    if value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


@dataclass
class ScheduleBlock:
    task: Task
    start: datetime
    end: datetime
    status: TaskStatus | None = None

    def __post_init__(self) -> None:
        if self.task is None:
            raise ValueError("Schedule block must have a task.")
        if not self.task.is_atomic:
            raise ValueError("Schedule block must have an atomic task.")
        self.start = _normalize_timestamp(self.start)
        self.end = _normalize_timestamp(self.end)
        if self.start >= self.end:
            raise ValueError("Schedule block start must be before end.")


@dataclass
class Plan:
    id: str
    date: datetime
    planning_horizon: timedelta
    schedule_blocks: list[ScheduleBlock]
    metadata: dict[str, str]

    def __post_init__(self) -> None:
        self.date = _normalize_timestamp(self.date)
        ordered_blocks = sorted(self.schedule_blocks, key=lambda block: block.start)
        for previous, current in zip(ordered_blocks, ordered_blocks[1:]):
            if current.start < previous.end:
                raise ValueError(
                    f"Schedule blocks for tasks {previous.task.id!r} and "
                    f"{current.task.id!r} overlap."
                )


def schedule_tasks(tasks: list[Task], timewindows: list[TimeWindow]) -> list[ScheduleBlock]:
    res: list[ScheduleBlock] = []

    # Track assigned tasks so we don't schedule the same task into multiple windows
    assigned_task_ids: set[str] = set()

    for window in timewindows:
        cursor = window.start
        while cursor < window.end:
            remaining_duration = window.end - cursor
            fitted_tasks: list[Task] = []

            for task in tasks:
                if task.id in assigned_task_ids:
                    continue
                if (timedelta(0) < task.estimated_duration <= remaining_duration):
                    fitted_tasks.append(task)

            if not fitted_tasks:
                break

            # Higher priority wins; duration breaks ties between equal priorities.
            sorted_tasks = sorted(
                fitted_tasks,
                key=lambda t: (
                    (
                        _PRIORITY_ORDER.get(t.priority, float("inf"))
                        if t.priority is not None
                        else float("inf")
                    ),
                    t.deadline if t.deadline is not None else datetime.max.replace(tzinfo=timezone.utc),
                    t.estimated_duration,
                )
            )

            # 3. Schedule the best-fitting task (e.g., the first task from our sorted list)
            best_task = sorted_tasks[0]

            block_start = cursor
            block_end = block_start + best_task.estimated_duration

            # Create and append the block
            res.append(
                ScheduleBlock(
                    task=best_task,
                    start=block_start,
                    end=block_end,
                    status=best_task.status
                )
            )

            # Mark as scheduled
            assigned_task_ids.add(best_task.id)
            cursor = block_end

    return res

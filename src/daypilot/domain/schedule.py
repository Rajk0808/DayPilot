from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.times import Constraint, TimeWindow

from .enums import (
    ConstraintType,
    Priority,
    SchedulingFailureReason,
    TaskStatus,
    SchedulingStatus,
)
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


@dataclass(frozen=True)
class PlacementResult:
    """Outcome of attempting to place one task."""

    task: Task
    block: ScheduleBlock | None = None
    reason: SchedulingFailureReason | None = None

    def __post_init__(self) -> None:
        if self.task is None:
            raise ValueError("Placement result must have a task.")
        if (self.block is None) == (self.reason is None):
            raise ValueError("Provide exactly one of block or failure reason.")
        if self.block is not None and self.block.task is not self.task:
            raise ValueError("Placement block must belong to the result task.")


@dataclass(frozen=True)
class SchedulingDecision:
    """Outcome of evaluating all tasks in one scheduling iteration."""

    selected_block: ScheduleBlock | None
    failed_task_results: tuple[PlacementResult, ...] = ()

    def __post_init__(self) -> None:
        if any(result.block is not None for result in self.failed_task_results):
            raise ValueError("Failed task results cannot contain placement blocks.")


@dataclass(frozen=True)
class SchedulingRunResult:
    """Final outcome of a scheduling run."""

    scheduled_blocks: tuple[ScheduleBlock, ...]
    unresolved_task_results: tuple[PlacementResult, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not self.unresolved_task_results


@dataclass
class Plan:
    id: str
    date: datetime
    planning_horizon: timedelta
    schedule_blocks: list[ScheduleBlock]
    metadata: dict[str, str]

    def __post_init__(self) -> None:
        self.date = _normalize_timestamp(self.date)
        if self.planning_horizon <= timedelta(0):
            raise ValueError("Planning horizon must be positive.")
        if self.schedule_blocks is None:
            raise ValueError("Schedule blocks must be provided.")

        horizon_end = self.date + self.planning_horizon
        seen_task_ids: set[str] = set()
        for block in self.schedule_blocks:
            if block is None:
                raise ValueError("Schedule blocks cannot contain None.")
            if block.task is None or not block.task.is_atomic:
                raise ValueError("Scheduled task must be atomic.")
            if block.start >= block.end:
                raise ValueError(
                    f"Schedule block for task {block.task.id!r} must have start before end."
                )
            if block.start < self.date or block.end > horizon_end:
                raise ValueError(
                    f"Schedule block for task {block.task.id!r} must lie within the planning horizon."
                )
            if block.task.id in seen_task_ids:
                raise ValueError(f"Task {block.task.id!r} has multiple schedule blocks.")
            seen_task_ids.add(block.task.id)

        ordered_blocks = sorted(self.schedule_blocks, key=lambda block: block.start)
        for previous, current in zip(ordered_blocks, ordered_blocks[1:]):
            if current.start < previous.end:
                raise ValueError(
                    f"Schedule blocks for tasks {previous.task.id!r} and "
                    f"{current.task.id!r} overlap."
                )
def schedule_tasks(
        tasks: list[Task], 
        timewindows: list[TimeWindow], 
        soft_constraints: list[Constraint], 
        dependency_graph: DependencyGraph
        ) -> SchedulingRunResult:
    """
    Schedule tasks within the provided time windows.

    Returns scheduled blocks and failure details for tasks left unscheduled.
    """
    if tasks is None:
        raise ValueError("Tasks must be provided.")
    if timewindows is None:
        raise ValueError("Time windows must be provided.")
    if dependency_graph is None:
        raise ValueError("Dependency graph must be provided.")

    remaining_tasks = list(tasks)
    remaining_windows = list(timewindows)
    scheduled: list[ScheduleBlock] = []
    if soft_constraints is None:
        raise ValueError("Soft constraints must be provided.")

    unresolved_results: tuple[PlacementResult, ...] = ()
    while remaining_tasks:
        decision = select_best_task_placement(
            remaining_tasks,
            remaining_windows,
            soft_constraints,
            dependency_graph,
            scheduled,
        )
        block = decision.selected_block
        if block is None:
            unresolved_results = decision.failed_task_results
            break

        for index, window in enumerate(remaining_windows):
            if window.start <= block.start and block.end <= window.end:
                remaining_windows[index:index + 1] = consume_timewindow(window, block)
                block.task.scheduling_status = SchedulingStatus.SCHEDULED
                scheduled.append(block)
                remaining_tasks.remove(block.task)
                break

    if remaining_tasks:
        reported_tasks = {result.task for result in unresolved_results}
        unresolved_results += tuple(
            evaluate_task_placement(
                task,
                remaining_windows,
                soft_constraints,
                dependency_graph,
                scheduled,
            )
            for task in remaining_tasks
            if task not in reported_tasks
        )

    return SchedulingRunResult(tuple(scheduled), unresolved_results)




def evaluate_soft_constraints(
    block_start: datetime,
    block_end: datetime,
    soft_constraints: list[Constraint],
) -> int:
    """
    Evaluate soft constraints for a scheduled task block.

    Returns a score based on how well the block satisfies the task's soft constraints.
    Higher scores indicate better satisfaction of constraints.
    """
    score = 0
    for constraint in soft_constraints:
        if (
            constraint.type is ConstraintType.SOFT_CONSTRAINT
            and constraint.rule_information.start <= block_start
            and block_end <= constraint.rule_information.end
        ):
            score += 1
    return score


def evaluate_task_placement(
    task: Task,
    timewindows: list[TimeWindow],
    soft_constraints: list[Constraint],
    dependency_graph: DependencyGraph,
    scheduled_blocks: list[ScheduleBlock],
) -> PlacementResult:
    """Evaluate one task and return its best placement or a failure reason."""
    if task is None:
        raise ValueError("Task must be provided.")
    if timewindows is None:
        raise ValueError("Time windows must be provided.")
    if soft_constraints is None:
        raise ValueError("Soft constraints must be provided.")
    if dependency_graph is None:
        raise ValueError("Dependency graph must be provided.")
    if scheduled_blocks is None:
        raise ValueError("Scheduled blocks must be provided.")
    if any(block is None for block in scheduled_blocks):
        raise ValueError("Scheduled blocks cannot contain None.")

    if task.scheduling_status is SchedulingStatus.SCHEDULED:
        return PlacementResult(task, reason=SchedulingFailureReason.ALREADY_SCHEDULED)
    if (
        task.status is not TaskStatus.NOT_STARTED
        or task.scheduling_status is not SchedulingStatus.UNSCHEDULED
        or not task.is_atomic
        or task.estimated_duration <= timedelta(0)
    ):
        return PlacementResult(task, reason=SchedulingFailureReason.INVALID_STATE)
    if not timewindows:
        return PlacementResult(task, reason=SchedulingFailureReason.NO_AVAILABLE_WINDOW)

    fitting_windows = [
        window for window in timewindows
        if task.estimated_duration <= window.end - window.start
    ]
    if not fitting_windows:
        return PlacementResult(task, reason=SchedulingFailureReason.INSUFFICIENT_TIME)

    best_block: ScheduleBlock | None = None
    best_rank: tuple[int, datetime] | None = None
    for window in fitting_windows:
        if not can_schedule_with_dependencies(
            task, window.start, dependency_graph, scheduled_blocks
        ):
            continue
        candidate = ScheduleBlock(
            task=task,
            start=window.start,
            end=window.start + task.estimated_duration,
            status=task.status,
        )
        rank = (
            -evaluate_soft_constraints(candidate.start, candidate.end, soft_constraints),
            candidate.start,
        )
        if best_rank is None or rank < best_rank:
            best_block, best_rank = candidate, rank

    if best_block is None:
        return PlacementResult(task, reason=SchedulingFailureReason.DEPENDENCY_BLOCKED)
    return PlacementResult(task, block=best_block)


def select_best_task_placement(
    tasks: list[Task],
    timewindows: list[TimeWindow],
    soft_constraints: list[Constraint],
    dependency_graph: DependencyGraph,
    scheduled_blocks: list[ScheduleBlock],
) -> SchedulingDecision:
    """Choose a placement and preserve failure details for this iteration."""
    if tasks is None:
        raise ValueError("Tasks must be provided.")
    if timewindows is None:
        raise ValueError("Time windows must be provided.")
    if dependency_graph is None:
        raise ValueError("Dependency graph must be provided.")
    if scheduled_blocks is None:
        raise ValueError("Scheduled blocks must be provided.")

    best_block: ScheduleBlock | None = None
    best_rank: tuple[int, int, datetime, datetime, timedelta] | None = None
    failed_results: list[PlacementResult] = []
    latest_deadline = datetime.max.replace(tzinfo=timezone.utc)

    for task in tasks:
        if task is None:
            raise ValueError("Tasks cannot contain None.")
        result = evaluate_task_placement(
            task, timewindows, soft_constraints, dependency_graph, scheduled_blocks
        )
        if result.block is None:
            failed_results.append(result)
            continue
        priority_rank = (
            _PRIORITY_ORDER.get(task.priority, len(_PRIORITY_ORDER))
            if task.priority is not None
            else len(_PRIORITY_ORDER)
        )
        deadline_rank = (
            _normalize_timestamp(task.deadline)
            if task.deadline is not None
            else latest_deadline
        )

        candidate = result.block
        score = evaluate_soft_constraints(candidate.start, candidate.end, soft_constraints)
        # Lower priority/deadline ranks are better; the score is maximized.
        rank = (
            -score,
            priority_rank,
            deadline_rank,
            candidate.start,
            task.estimated_duration,
        )
        if best_rank is None or rank < best_rank:
            best_block = candidate
            best_rank = rank
    return SchedulingDecision(best_block, tuple(failed_results))

def consume_timewindow(
        window,
        scheduled_block
    ) -> list[TimeWindow]:
    """
    Consume a time window by removing the time occupied by a scheduled block.
    Returns a list of remaining time windows after the block has been scheduled.
    """
    if scheduled_block.start < window.start or scheduled_block.end > window.end:
        raise ValueError("Scheduled block must be within the time window.")
    if scheduled_block.start == window.start and scheduled_block.end == window.end:
        return [] 
    elif scheduled_block.start == window.start:
        return [TimeWindow(start=scheduled_block.end, end=window.end)]
    elif scheduled_block.end == window.end:
        return [TimeWindow(start=window.start, end=scheduled_block.start)]
    else:
        return [
            TimeWindow(start=window.start, end=scheduled_block.start),
            TimeWindow(start=scheduled_block.end, end=window.end),
        ]


def can_schedule(task: Task) -> bool:
    """Return whether the task is generally eligible to be planned."""
    if task is None:
        return False
    return (
        task.status is TaskStatus.NOT_STARTED
        and task.scheduling_status is SchedulingStatus.UNSCHEDULED
    )


def can_schedule_with_dependencies(
    task: Task,
    candidate_start: datetime,
    dependency_graph: DependencyGraph,
    scheduled_blocks: list[ScheduleBlock],
) -> bool:
    """
    Check whether all prerequisites are completed or finish by candidate_start.
    """
    if task is None:
        return False
    if candidate_start is None:
        raise ValueError("Candidate start must be provided.")
    if dependency_graph is None:
        raise ValueError("Dependency graph must be provided.")
    if scheduled_blocks is None:
        raise ValueError("Scheduled blocks must be provided.")
    if any(block is None for block in scheduled_blocks):
        raise ValueError("Scheduled blocks cannot contain None.")
    candidate_start = _normalize_timestamp(candidate_start)
    prerequisites = dependency_graph.get_prerequisites(task)
    scheduled_ends = {
        block.task: block.end
        for block in scheduled_blocks
    }
    return all( 
        prerequisite.status is TaskStatus.COMPLETED
        or (
            prerequisite in scheduled_ends
            and scheduled_ends[prerequisite] <= candidate_start
        )
        for prerequisite in prerequisites
    )

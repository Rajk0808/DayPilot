from collections.abc import Sequence
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
    if value is None:
        raise ValueError("Timestamp cannot be None.")
    if value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class SchedulingCandidate:
    task: Task
    duration: timedelta

    def __post_init__(self) -> None:
        if self.task is None:
            raise ValueError("Task cannot be None.")
        if self.duration is None:
            raise ValueError("Duration cannot be None.")
        if self.duration <= timedelta(0):
            raise ValueError("Duration must be positive.")

@dataclass
class ScheduleBlock:
    task: Task
    start: datetime
    end: datetime

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


@dataclass(frozen=True, eq=False)
class SchedulingRunResult:
    """Final outcome of a scheduling run."""

    scheduled_blocks: tuple[ScheduleBlock, ...]
    unresolved_task_results: tuple[PlacementResult, ...] = ()

    @property
    def is_complete(self) -> bool:
        return not self.unresolved_task_results

    def __iter__(self):
        return iter(self.scheduled_blocks)

    def __len__(self) -> int:
        return len(self.scheduled_blocks)

    def __getitem__(self, index):
        return self.scheduled_blocks[index]

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SchedulingRunResult):
            return (
                self.scheduled_blocks == other.scheduled_blocks
                and self.unresolved_task_results == other.unresolved_task_results
            )
        if isinstance(other, (list, tuple)):
            return list(self.scheduled_blocks) == list(other)
        return NotImplemented


@dataclass
class Plan:
    id: str
    date: datetime
    planning_horizon: timedelta
    schedule_blocks: list[ScheduleBlock]
    metadata: dict[str, str]

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not self.id:
            raise ValueError("Plan ID must be a non-empty string.")
        self.date = _normalize_timestamp(self.date)
        if self.planning_horizon is None:
            raise ValueError("Planning horizon cannot be None.")
        if not isinstance(self.planning_horizon, timedelta):
            raise ValueError("Planning horizon must be a timedelta.")
        if self.planning_horizon <= timedelta(0):
            raise ValueError("Planning horizon must be positive.")
        if self.schedule_blocks is None:
            raise ValueError("Schedule blocks must be provided.")
        if self.metadata is None:
            raise ValueError("Plan metadata cannot be None.")
        if not isinstance(self.metadata, dict) or any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in self.metadata.items()
        ):
            raise ValueError("Plan metadata must be a dictionary of strings.")

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
    tasks: Sequence[Task | SchedulingCandidate],
        timewindows: list[TimeWindow], 
        soft_constraints: list[Constraint] | None = None,
        dependency_graph: DependencyGraph | None = None,
        scheduled_blocks: list[ScheduleBlock] | None = None,
        ) -> SchedulingRunResult:
    """
    Schedule tasks within the provided time windows.

    Returns scheduled blocks and failure details for tasks left unscheduled.
    """
    if tasks is None:
        raise ValueError("Tasks must be provided.")
    if timewindows is None:
        raise ValueError("Time windows must be provided.")
    if any(window is None for window in timewindows):
        raise ValueError("Time windows cannot contain None.")
    if soft_constraints is None:
        soft_constraints = []
    if any(constraint is None for constraint in soft_constraints):
        raise ValueError("Soft constraints cannot contain None.")
    if dependency_graph is None:
        dependency_graph = DependencyGraph()
        for item in tasks:
            if item is None:
                raise ValueError("Tasks cannot contain None.")
            task = item.task if isinstance(item, SchedulingCandidate) else item
            dependency_graph.register_task(task)
    if scheduled_blocks is None:
        scheduled_blocks = []
    if any(block is None for block in scheduled_blocks):
        raise ValueError("Scheduled blocks cannot contain None.")

    remaining_tasks = list(tasks)
    remaining_windows = list(timewindows)
    scheduled: list[ScheduleBlock] = list(scheduled_blocks)
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
                scheduled.append(block)
                remaining_tasks = [
                    item
                    for item in remaining_tasks
                    if (item.task if isinstance(item, SchedulingCandidate) else item)
                    is not block.task
                ]
                break

    if remaining_tasks:
        reported_tasks = {id(result.task) for result in unresolved_results}
        unresolved_results += tuple(
            evaluate_task_placement(
                item,
                remaining_windows,
                soft_constraints,
                dependency_graph,
                scheduled,
            )
            for item in remaining_tasks
            if id(item.task if isinstance(item, SchedulingCandidate) else item)
            not in reported_tasks
        )

    return SchedulingRunResult(tuple(scheduled[len(scheduled_blocks):]), unresolved_results)




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
        if constraint is None:
            raise ValueError("Soft constraints cannot contain None.")
        if (
            constraint.type is ConstraintType.SOFT_CONSTRAINT
            and constraint.rule_information.start <= block_start
            and block_end <= constraint.rule_information.end
        ):
            score += 1
    return score


def evaluate_task_placement(
    task: Task | SchedulingCandidate,
    timewindows: list[TimeWindow],
    soft_constraints: list[Constraint],
    dependency_graph: DependencyGraph,
    scheduled_blocks: list[ScheduleBlock],
) -> PlacementResult:
    """Evaluate one task and return its best placement or a failure reason.

    Task deadlines rank otherwise valid candidates; they are not hard
    placement boundaries in the current domain contract.
    """
    if task is None:
        raise ValueError("Task must be provided.")
    is_recovered_candidate = isinstance(task, SchedulingCandidate)
    scheduling_candidate = (
        task if is_recovered_candidate
        else SchedulingCandidate(task=task, duration=task.estimated_duration)
    )
    task = scheduling_candidate.task
    duration = scheduling_candidate.duration
    if timewindows is None:
        raise ValueError("Time windows must be provided.")
    if any(window is None for window in timewindows):
        raise ValueError("Time windows cannot contain None.")
    if soft_constraints is None:
        raise ValueError("Soft constraints must be provided.")
    if any(constraint is None for constraint in soft_constraints):
        raise ValueError("Soft constraints cannot contain None.")
    if dependency_graph is None:
        raise ValueError("Dependency graph must be provided.")
    if scheduled_blocks is None:
        raise ValueError("Scheduled blocks must be provided.")
    if any(block is None for block in scheduled_blocks):
        raise ValueError("Scheduled blocks cannot contain None.")

    if task.scheduling_status is SchedulingStatus.SCHEDULED and not is_recovered_candidate:
        return PlacementResult(task, reason=SchedulingFailureReason.ALREADY_SCHEDULED)
    if (
        (task.status is not TaskStatus.NOT_STARTED
         and not (is_recovered_candidate and task.status is TaskStatus.IN_PROGRESS))
        or (task.scheduling_status is not SchedulingStatus.UNSCHEDULED and not is_recovered_candidate)
        or not task.is_atomic
        or duration <= timedelta(0)
    ):
        return PlacementResult(task, reason=SchedulingFailureReason.INVALID_STATE)
    if not timewindows:
        return PlacementResult(task, reason=SchedulingFailureReason.NO_AVAILABLE_WINDOW)

    fitting_windows = [
        window for window in timewindows
        if duration <= window.end - window.start
    ]
    if not fitting_windows:
        return PlacementResult(task, reason=SchedulingFailureReason.INSUFFICIENT_TIME)

    best_block: ScheduleBlock | None = None
    best_rank: tuple[int, datetime] | None = None
    prerequisites = dependency_graph.get_prerequisites(task)
    scheduled_ends = {id(block.task): block.end for block in scheduled_blocks}
    for window in fitting_windows:
        candidate_starts = {window.start}
        for scheduled_block in scheduled_blocks:
            if (scheduled_block.start < window.end
                    and window.start < scheduled_block.end
                    and scheduled_block.end <= window.end):
                candidate_starts.add(scheduled_block.end)
        dependency_start = window.start
        dependencies_scheduled = True
        for prerequisite in prerequisites:
            if prerequisite.status is TaskStatus.COMPLETED:
                continue
            prerequisite_end = scheduled_ends.get(id(prerequisite))
            if prerequisite_end is None:
                dependencies_scheduled = False
                break
            dependency_start = max(dependency_start, prerequisite_end)
        if dependencies_scheduled:
            candidate_starts.add(dependency_start)
        for constraint in soft_constraints:
            if constraint.type is not ConstraintType.SOFT_CONSTRAINT:
                continue
            soft_window = constraint.rule_information
            latest_start = min(window.end, soft_window.end) - duration
            preferred_start = max(window.start, soft_window.start)
            if preferred_start <= latest_start:
                candidate_starts.add(preferred_start)

        for candidate_start in sorted(candidate_starts):
            candidate_end = candidate_start + duration
            if candidate_end > window.end:
                continue
            if not can_schedule_with_dependencies(
                task, candidate_start, dependency_graph, scheduled_blocks
            ):
                continue
            if any(
                scheduled_block.start < candidate_end
                and candidate_start < scheduled_block.end
                for scheduled_block in scheduled_blocks
            ):
                continue
            candidate = ScheduleBlock(
                task=task,
                start=candidate_start,
                end=candidate_end,
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
    tasks: Sequence[Task | SchedulingCandidate],
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
    if any(window is None for window in timewindows):
        raise ValueError("Time windows cannot contain None.")
    if soft_constraints is None:
        raise ValueError("Soft constraints must be provided.")
    if any(constraint is None for constraint in soft_constraints):
        raise ValueError("Soft constraints cannot contain None.")
    if dependency_graph is None:
        raise ValueError("Dependency graph must be provided.")
    if scheduled_blocks is None:
        raise ValueError("Scheduled blocks must be provided.")

    best_block: ScheduleBlock | None = None
    best_rank: tuple[int, int, datetime, datetime, timedelta] | None = None
    failed_results: list[PlacementResult] = []
    latest_deadline = datetime.max.replace(tzinfo=timezone.utc)
    for item in tasks:
        if item is None:
            raise ValueError("Tasks cannot contain None.")

        scheduling_candidate = (
            item
            if isinstance(item, SchedulingCandidate)
            else SchedulingCandidate(task=item, duration=item.estimated_duration)
        )
        task = scheduling_candidate.task
        result = evaluate_task_placement(
            item,
            timewindows,
            soft_constraints,
            dependency_graph,
            scheduled_blocks,
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
        block = result.block
        score = evaluate_soft_constraints(block.start, block.end, soft_constraints)
        # Lower priority/deadline ranks are better; the score is maximized.
        rank = (
            -score,
            priority_rank,
            deadline_rank,
            block.start,
            scheduling_candidate.duration,
        )
        if best_rank is None or rank < best_rank:
            best_block = block
            best_rank = rank
    return SchedulingDecision(best_block, tuple(failed_results))

def consume_timewindow(
    window: TimeWindow,
    scheduled_block: ScheduleBlock,
) -> list[TimeWindow]:
    """
    Consume a time window by removing the time occupied by a scheduled block.
    Returns a list of remaining time windows after the block has been scheduled.
    """
    if window is None or scheduled_block is None:
        raise ValueError("Window and scheduled block must be provided.")
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
    if dependency_graph.tasks.get(task.id) is not task:
        return False
    candidate_start = _normalize_timestamp(candidate_start)
    prerequisites = dependency_graph.get_prerequisites(task)
    scheduled_ends = {
        id(block.task): block.end
        for block in scheduled_blocks
    }
    return all( 
        prerequisite.status is TaskStatus.COMPLETED
        or (
            id(prerequisite) in scheduled_ends
            and scheduled_ends[id(prerequisite)] <= candidate_start
        )
        for prerequisite in prerequisites
    )

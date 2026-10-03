from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.observation import Observation, calculate_observation_history_summary, validate_observation_history
from daypilot.domain.schedule import Plan, ScheduleBlock, SchedulingCandidate, SchedulingRunResult, schedule_tasks
from daypilot.domain.task import Task
from daypilot.domain.times import TimeWindow, generate_time_windows, Constraint
from .enums import ConstraintType, PlanningChangeType, SchedulingStatus, TaskStatus
from .planner import PlannerState

@dataclass(frozen=True)
class PlanningChange:
    """Describe a planning input change.

    The associated ``PlannerState`` must already reflect the change before
    ``replan`` is called, except that task removal remains staged until the
    returned result is applied.

    Task changes identify the task in ``task``. Calendar event and constraint
    changes leave ``task`` unset and put the changed resource in ``metadata``
    under ``event`` or ``constraint`` respectively. Dependency changes carry
    ``dependent`` and ``prerequisite`` tasks in metadata. For resource updates,
    the value describes the resource after the change; its ID identifies the
    prior resource as well.
    """

    change_type: PlanningChangeType
    task: Task | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.change_type is None:
            raise ValueError("Planning change type cannot be None.")
        if self.metadata is None:
            raise ValueError("Planning change metadata cannot be None.")
        if not isinstance(self.metadata, dict):
            raise ValueError("Planning change metadata must be a dictionary.")
        if "changed_fields" in self.metadata:
            changed_fields = self.metadata["changed_fields"]
            if not isinstance(changed_fields, (list, tuple, set, frozenset)):
                raise ValueError("Task changed_fields must be a collection of field names.")
            if any(not isinstance(field_name, str) for field_name in changed_fields):
                raise ValueError("Task changed_fields must contain only strings.")

        if self.change_type in {
            PlanningChangeType.TASK_ADDED,
            PlanningChangeType.TASK_UPDATED,
            PlanningChangeType.TASK_REMOVED,
        }:
            if self.task is None:
                raise ValueError("Task changes must identify a task.")
        elif self.change_type in {
            PlanningChangeType.CALENDAR_EVENT_ADDED,
            PlanningChangeType.CALENDAR_EVENT_UPDATED,
            PlanningChangeType.CALENDAR_EVENT_REMOVED,
        }:
            if self.task is not None:
                raise ValueError("Calendar event changes cannot identify a task.")
            if "event" not in self.metadata:
                raise ValueError("Calendar event changes must include an event in metadata.")
        elif self.change_type in {
            PlanningChangeType.CONSTRAINT_ADDED,
            PlanningChangeType.CONSTRAINT_UPDATED,
            PlanningChangeType.CONSTRAINT_REMOVED,
        }:
            if self.task is not None:
                raise ValueError("Constraint changes cannot identify a task.")
            if "constraint" not in self.metadata:
                raise ValueError("Constraint changes must include a constraint in metadata.")
        elif self.change_type in {
            PlanningChangeType.DEPENDENCY_ADDED,
            PlanningChangeType.DEPENDENCY_REMOVED,
        }:
            if self.task is not None:
                raise ValueError("Dependency changes cannot identify a task.")
            if not isinstance(self.metadata.get("dependent"), Task):
                raise ValueError("Dependency changes must include a dependent task in metadata.")
            if not isinstance(self.metadata.get("prerequisite"), Task):
                raise ValueError("Dependency changes must include a prerequisite task in metadata.")
        elif self.change_type is PlanningChangeType.OBSERVATION_RECORDED:
            if self.task is not None:
                raise ValueError("Observation changes should not identify a task directly.")
            if not isinstance(self.metadata.get("observation"), Observation):
                raise ValueError("Observation changes must include an observation in metadata.")
        elif self.change_type is PlanningChangeType.PLAN_REPLACED and self.task is not None:
            raise ValueError("Plan replacement changes cannot identify a task.")

@dataclass(frozen=True)
class RemainingWork:
    task : Task
    duration : timedelta

    def __post_init__(self) -> None:
        if self.task is None:
            raise ValueError("Remaining work task cannot be None.")
        if not isinstance(self.duration, timedelta):
            raise ValueError("Remaining work duration must be a timedelta.")
        if self.duration <= timedelta(0):
            raise ValueError("Remaining work duration must be positive.")

@dataclass(frozen=True)
class ReplanningResult:
    new_plan : Plan
    preserved_blocks : list[ScheduleBlock]
    invalidated_blocks : list[ScheduleBlock]
    rescheduled_blocks : list[ScheduleBlock]
    unresolved_work : list[RemainingWork]
    removed_tasks: list[Task] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.new_plan is None:
            raise ValueError("New plan cannot be None.")
    
        if self.preserved_blocks is None:
            raise ValueError("Preserved blocks cannot be None.")
    
        if self.invalidated_blocks is None:
            raise ValueError("Invalidated blocks cannot be None.")
    
        if self.rescheduled_blocks is None:
            raise ValueError("Rescheduled blocks cannot be None.")
    
        if self.unresolved_work is None:
            raise ValueError("Unresolved work cannot be None.")
        if self.removed_tasks is None:
            raise ValueError("Removed tasks cannot be None.")
        collections = (
            self.preserved_blocks,
            self.invalidated_blocks,
            self.rescheduled_blocks,
            self.unresolved_work,
            self.removed_tasks,
        )
        if any(item is None for collection in collections for item in collection):
            raise ValueError("Replanning result collections cannot contain None.")
        if len({id(task) for task in self.removed_tasks}) != len(self.removed_tasks):
            raise ValueError("Removed tasks cannot contain duplicates.")
        blocks = self.preserved_blocks + self.invalidated_blocks + self.rescheduled_blocks
        if len({id(block) for block in blocks}) != len(blocks):
            raise ValueError("Replanning result cannot contain duplicate blocks.")
        new_plan_blocks = self.new_plan.schedule_blocks
        if any(not any(block is scheduled for scheduled in new_plan_blocks)
               for block in self.preserved_blocks):
            raise ValueError("Preserved blocks must appear in the new plan.")
        if any(any(block is scheduled for scheduled in new_plan_blocks)
               for block in self.invalidated_blocks):
            raise ValueError("Invalidated blocks cannot remain in the new plan.")
        if any(not any(block is scheduled for scheduled in self.new_plan.schedule_blocks)
               for block in self.rescheduled_blocks):
            raise ValueError("Rescheduled blocks must appear in the new plan.")
        if any(block.task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
               for block in new_plan_blocks):
            raise ValueError("Completed or cancelled tasks cannot be scheduled.")
        if any(any(block.task is task for block in self.new_plan.schedule_blocks)
               for task in self.removed_tasks):
            raise ValueError("Removed tasks cannot appear in the new plan.")
        if len({id(work.task) for work in self.unresolved_work}) != len(self.unresolved_work):
            raise ValueError("Unresolved work cannot contain duplicate tasks.")
        if any(work.duration is None or work.duration <= timedelta(0)
               for work in self.unresolved_work):
            raise ValueError("Unresolved work durations must be positive.")
        if any(work.task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
               for work in self.unresolved_work):
            raise ValueError("Completed or cancelled tasks cannot remain unresolved.")
        if any(any(block.task is work.task for block in self.new_plan.schedule_blocks)
               for work in self.unresolved_work):
            raise ValueError("Unresolved work cannot also be scheduled in the new plan.")

        
def create_scheduling_candidate(
    remaining_work: RemainingWork,
) -> SchedulingCandidate:
    if remaining_work is None:
        raise ValueError("Remaining work cannot be None.")
    if remaining_work.duration <= timedelta(0):
        raise ValueError("Remaining work duration must be positive.")

    return SchedulingCandidate(
        task=remaining_work.task,
        duration=remaining_work.duration,
    )

def create_scheduling_candidates(remaining_work: list[RemainingWork]) -> list[SchedulingCandidate]:
    """Wrap recovered work for the scheduler without changing its task."""
    if remaining_work is None:
        raise ValueError("Remaining work cannot be None.")
    if not remaining_work:
        return []
    res = []
    for work in remaining_work:
        if work is None:
            raise ValueError("Remaining work cannot contain None.")
        if work.duration <= timedelta(0):
            raise ValueError("Remaining work duration must be positive.")
        res.append(create_scheduling_candidate(work))
    return res



def change_affects_plan(change: PlanningChange) -> bool:
    if change is None:
        raise ValueError("Planning change cannot be None.")
    if change.change_type is PlanningChangeType.PLAN_REPLACED:
        return False
    if change.change_type is PlanningChangeType.TASK_UPDATED and "changed_fields" in change.metadata:
        fields = change.metadata["changed_fields"]
        if not isinstance(fields, (list, tuple, set, frozenset)):
            raise ValueError("Task changed_fields must be a collection of field names.")
        return bool(set(fields) & {
            "priority", "estimated_duration", "deadline", "status", "scheduling_status"
        })
    return True

def affected_tasks(
    change: PlanningChange,
    dependency_graph: DependencyGraph,
) -> set[Task]:

    if change is None:
        raise ValueError("Planning change cannot be None.")
    if dependency_graph is None:
        raise ValueError("Dependency graph cannot be None.")

    affected: set[Task] = set()

    if change.change_type in {
        PlanningChangeType.TASK_ADDED,
        PlanningChangeType.TASK_UPDATED,
        PlanningChangeType.TASK_REMOVED,
    }:
        if change.task is None:
            raise ValueError("Task changes must identify a task.")
        if change.change_type is PlanningChangeType.TASK_UPDATED and not change_affects_plan(change):
            return affected

        if dependency_graph.tasks.get(change.task.id) is change.task:
            affected.add(change.task)
            pending = [change.task]
            while pending:
                current = pending.pop()
                for dependent in dependency_graph.get_dependents(current):
                    if dependent not in affected:
                        affected.add(dependent)
                        pending.append(dependent)
        else:
            # Removed tasks may already have been detached from the graph;
            # their old scheduled block still needs to be invalidated.
            affected.add(change.task)
    elif change.change_type is PlanningChangeType.OBSERVATION_RECORDED:
        observation = change.metadata["observation"]
        task = observation.task
        if dependency_graph.tasks.get(task.id) is not task:
            raise ValueError("Observation task must belong to the dependency graph.")
        affected.add(task)
        pending = [task]
        while pending:
            current = pending.pop()
            for dependent in dependency_graph.get_dependents(current):
                if dependent not in affected:
                    affected.add(dependent)
                    pending.append(dependent)

    return affected


def affected_tasks_for_dependency_change(
    change: PlanningChange,
    dependency_graph: DependencyGraph,
) -> set[Task]:
    """Return added dependency impact; removed edges preserve valid placements.

    The graph must represent the post-change state: added edges are present
    and removed edges are absent.
    """
    if change is None:
        raise ValueError("Planning change cannot be None.")
    if dependency_graph is None:
        raise ValueError("Dependency graph cannot be None.")
    if change.change_type not in {
        PlanningChangeType.DEPENDENCY_ADDED,
        PlanningChangeType.DEPENDENCY_REMOVED,
    }:
        return set()

    dependent = change.metadata["dependent"]
    prerequisite = change.metadata["prerequisite"]
    if (dependency_graph.tasks.get(dependent.id) is not dependent
            or dependency_graph.tasks.get(prerequisite.id) is not prerequisite):
        raise ValueError("Dependency change tasks must belong to the dependency graph.")
    is_present = dependency_graph.has_dependency(dependent, prerequisite)
    if change.change_type is PlanningChangeType.DEPENDENCY_ADDED and not is_present:
        raise ValueError("Added dependency is not present in the dependency graph.")
    if change.change_type is PlanningChangeType.DEPENDENCY_REMOVED and is_present:
        raise ValueError("Removed dependency is still present in the dependency graph.")
    if change.change_type is PlanningChangeType.DEPENDENCY_REMOVED:
        return set()

    affected = {dependent}
    pending = [dependent]
    while pending:
        current = pending.pop()
        for task in dependency_graph.get_dependents(current):
            if task not in affected:
                affected.add(task)
                pending.append(task)
    return affected


def invalidated_blocks(
            plan: Plan | None,
            affected_tasks: set[Task],
        ) -> list[ScheduleBlock]:
    if plan is None:
        return []
    if affected_tasks is None:
        raise ValueError("Affected tasks cannot be None.")
    if plan.schedule_blocks is None:
        raise ValueError("Plan blocks cannot be None.")
    invalidated_blocks: list[ScheduleBlock] = []
    for block in plan.schedule_blocks:
        if block.task in affected_tasks:
            invalidated_blocks.append(block)
    return invalidated_blocks


def preserve_blocks(
        plan: Plan | None,
        invalidated_blocks: list[ScheduleBlock],
    ) -> list[ScheduleBlock]:
    if invalidated_blocks is None:
        raise ValueError("Invalidated blocks cannot be None.")
    if plan is None:
        return []
    if plan.schedule_blocks is None:
        raise ValueError("Plan blocks cannot be None.")
    for block in invalidated_blocks:
        if block not in plan.schedule_blocks:
            raise ValueError("Invalidated block is not part of the plan.")
    preserved_blocks: list[ScheduleBlock] = []
    for block in plan.schedule_blocks:
        if block not in invalidated_blocks:
            preserved_blocks.append(block)  
    return preserved_blocks


def recover_remaining_work(
        task: Task,
        observations: list[Observation],
    ) -> RemainingWork | None:
    if task is None:
        raise ValueError("Task cannot be None.")
    if observations is None:
        raise ValueError("Observations cannot be None.")
    if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
        return None
    if not observations:
        return RemainingWork(task=task, duration=task.estimated_duration)
    validate_observation_history(task, observations)
    res = calculate_observation_history_summary(task, observations)
    if res.remaining_duration <= timedelta(0):
        return None
    return RemainingWork(task=task, duration=res.remaining_duration)


def recover_remaining_work_for_tasks(
    tasks: set[Task],
    observations: list[Observation],
) -> list[RemainingWork]:
    """Recover remaining work for a set of tasks based on their observations."""
    if tasks is None:
        raise ValueError("Tasks cannot be None.")
    if observations is None:
        raise ValueError("Observations cannot be None.")
    remaining_work_list: list[RemainingWork] = []
    for task in sorted(tasks, key=lambda item: item.id):
        if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED):
            continue
        task_observations = [obs for obs in observations if obs.task is task]
        if not task_observations:
            remaining_work = RemainingWork(task=task, duration=task.estimated_duration)
        else:
            remaining_work = recover_remaining_work(task, task_observations)
        if remaining_work is not None:
            remaining_work_list.append(remaining_work)
    return remaining_work_list


def subtract_preserved_blocks(
    windows: list[TimeWindow],
    preserved_blocks: list[ScheduleBlock],
) -> list[TimeWindow]:
    if windows is None:
        raise ValueError("Windows cannot be None.")
    if preserved_blocks is None:
        raise ValueError("Preserved blocks cannot be None.")

    if any(block is None for block in preserved_blocks):
        raise ValueError("Preserved blocks cannot contain None.")
    blocks = sorted(preserved_blocks, key=lambda block: block.start)
    available_windows: list[TimeWindow] = []
    for window in windows:
        if window is None:
            raise ValueError("Windows cannot contain None.")
        cursor = window.start
        for block in blocks:
            if block.end <= cursor:
                continue
            if block.start >= window.end:
                break
            if block.start > cursor:
                available_windows.append(TimeWindow(start=cursor, end=min(block.start, window.end)))
            cursor = max(cursor, block.end)
            if cursor >= window.end:
                break
        if cursor < window.end:
            available_windows.append(TimeWindow(start=cursor, end=window.end))

    return available_windows


def rebuild_available_windows(
    planner_state: PlannerState,
    preserved_blocks: list[ScheduleBlock],
    planning_start: datetime,
    planning_end: datetime,
) -> list[TimeWindow]:
    if planner_state is None:
        raise ValueError("Planner state cannot be None.")
    if preserved_blocks is None:
        raise ValueError("Preserved blocks cannot be None.")
    if planning_start is None or planning_end is None:
        raise ValueError("Planning start and end times cannot be None.")
    if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
        raise ValueError("Planning times must be timezone-aware.")
    if planning_start >= planning_end:
        raise ValueError("Planning start time must be before planning end time.")

    hard_constraints = [
        constraint
        for constraint in planner_state.constraints
        if constraint.type is ConstraintType.HARD_CONSTRAINT
    ]
    base_windows = generate_time_windows(
        planning_start,
        planning_end,
        planner_state.calendar_events,
        hard_constraints,
    )
    return subtract_preserved_blocks(base_windows, preserved_blocks)

def schedule_remaining_work(
    remaining_work: list[RemainingWork],
    timewindows: list[TimeWindow],
    soft_constraints: list[Constraint],
    dependency_graph: DependencyGraph,
    preserved_blocks: list[ScheduleBlock] | None = None,
) -> SchedulingRunResult:
    candidates = create_scheduling_candidates(remaining_work)
    return schedule_tasks(
        candidates,
        timewindows,
        soft_constraints,
        dependency_graph,
        preserved_blocks,
    )

def merge_schedule_blocks(
    preserved_blocks: list[ScheduleBlock],
    new_blocks: list[ScheduleBlock],
) -> list[ScheduleBlock]:
    if preserved_blocks is None:
        raise ValueError("Preserved blocks cannot be None.")
    if new_blocks is None:
        raise ValueError("New blocks cannot be None.")
    if any(block is None for block in preserved_blocks):
        raise ValueError("Preserved blocks cannot contain None.")
    if any(block is None for block in new_blocks):
        raise ValueError("New blocks cannot contain None.")

    merged_blocks = preserved_blocks + new_blocks
    merged_blocks.sort(key=lambda block: block.start)

    for current, next_block in zip(merged_blocks, merged_blocks[1:]):
        if current.end > next_block.start:
            raise ValueError(
                f"Schedule blocks {current.task.id!r} and "
                f"{next_block.task.id!r} overlap."
            )

    return merged_blocks


def build_replanned_plan(
    old_plan: Plan | None,
    merged_blocks: list[ScheduleBlock],
    plan_date: datetime,
    planning_horizon: timedelta,
) -> Plan:
    if merged_blocks is None:
        raise ValueError("Merged blocks cannot be None.")
    if any(block is None for block in merged_blocks):
        raise ValueError("Merged blocks cannot contain None.")
    if plan_date is None:
        raise ValueError("Plan date cannot be None.")
    if planning_horizon is None:
        raise ValueError("Planning horizon cannot be None.")
    if planning_horizon <= timedelta(0):
        raise ValueError("Planning horizon must be positive.")

    # Ensure that the merged blocks are sorted and do not overlap
    ordered_blocks = sorted(
        merged_blocks,
        key=lambda block: block.start,
    )
    for current, next_block in zip(ordered_blocks, ordered_blocks[1:]):
        if current.end > next_block.start:
            raise ValueError(
                f"Schedule blocks {current.task.id!r} and "
                f"{next_block.task.id!r} overlap."
            )

    return Plan(
        id=old_plan.id if old_plan is not None else "daypilot-plan",
        date=plan_date,
        schedule_blocks=ordered_blocks,
        planning_horizon=planning_horizon,
        metadata=dict(old_plan.metadata) if old_plan is not None else {},
    )

def build_replanning_result(
    new_plan: Plan,
    preserved_blocks: list[ScheduleBlock],
    invalidated_blocks: list[ScheduleBlock],
    rescheduled_blocks: list[ScheduleBlock],
    unresolved_work: list[RemainingWork],
    removed_tasks: list[Task] | None = None,
) -> ReplanningResult:
    if new_plan is None:
        raise ValueError("New plan cannot be None.")
    if preserved_blocks is None:
        raise ValueError("Preserved blocks cannot be None.")
    if invalidated_blocks is None:
        raise ValueError("Invalidated blocks cannot be None.")
    if rescheduled_blocks is None:
        raise ValueError("Rescheduled blocks cannot be None.")
    if unresolved_work is None:
        raise ValueError("Unresolved work cannot be None.")
    if removed_tasks is None:
        removed_tasks = []

    return ReplanningResult(
        new_plan=new_plan,
        preserved_blocks=preserved_blocks,
        invalidated_blocks=invalidated_blocks,
        rescheduled_blocks=rescheduled_blocks,
        unresolved_work=unresolved_work,
        removed_tasks=removed_tasks,
    )

def apply_replanning_result(
    planner_state: PlannerState,
    result: ReplanningResult,
) -> None:
    if planner_state is None:
        raise ValueError("Planner state cannot be None.")
    if result is None:
        raise ValueError("Replanning result cannot be None.")

    planner_state.commit_replanned_plan(result.new_plan, result.removed_tasks)


def _validate_change_reflected_in_state(
    planner_state: PlannerState,
    change: PlanningChange,
) -> None:
    kind = change.change_type
    if kind in (PlanningChangeType.TASK_ADDED, PlanningChangeType.TASK_UPDATED):
        task = change.task
        if task is None:
            raise ValueError("Task changes must identify a task.")
        if not planner_state._contains_task(task):
            raise ValueError("Changed task must belong to the planner state.")
    elif kind is PlanningChangeType.TASK_REMOVED:
        task = change.task
        if task is None:
            raise ValueError("Task changes must identify a task.")
        planner_state.validate_task_removal(task, allow_scheduled=True)
    elif kind in (
        PlanningChangeType.CALENDAR_EVENT_ADDED,
        PlanningChangeType.CALENDAR_EVENT_UPDATED,
    ):
        if not any(event is change.metadata["event"] for event in planner_state.calendar_events):
            raise ValueError("Changed calendar event must already be in the planner state.")
    elif kind is PlanningChangeType.CALENDAR_EVENT_REMOVED:
        if any(event is change.metadata["event"] for event in planner_state.calendar_events):
            raise ValueError("Removed calendar event is still in the planner state.")
    elif kind in (PlanningChangeType.CONSTRAINT_ADDED, PlanningChangeType.CONSTRAINT_UPDATED):
        if not any(item is change.metadata["constraint"] for item in planner_state.constraints):
            raise ValueError("Changed constraint must already be in the planner state.")
    elif kind is PlanningChangeType.CONSTRAINT_REMOVED:
        if any(item is change.metadata["constraint"] for item in planner_state.constraints):
            raise ValueError("Removed constraint is still in the planner state.")
    elif kind is PlanningChangeType.OBSERVATION_RECORDED:
        observation = change.metadata["observation"]
        if not any(item is observation for item in planner_state.observations):
            raise ValueError("Recorded observation must already be in the planner state.")
    elif kind in (PlanningChangeType.DEPENDENCY_ADDED, PlanningChangeType.DEPENDENCY_REMOVED):
        affected_tasks_for_dependency_change(change, planner_state.dependency_graph)


def replan(
    planner_state: PlannerState,
    change: PlanningChange,
    planning_start: datetime,
    planning_end: datetime,
) -> ReplanningResult:
    """Compute a proposed plan from state that already reflects ``change``.

    This function does not mutate ``planner_state``. Call
    :func:`apply_replanning_result` separately to commit the proposal. A
    ``TASK_REMOVED`` change is staged against the current state and committed
    together with the replacement plan.
    """
    if planner_state is None:
        raise ValueError("Planner state cannot be None.")
    if change is None:
        raise ValueError("Planning change cannot be None.")
    if planning_start is None or planning_end is None:
        raise ValueError("Planning start and end times cannot be None.")
    if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
        raise ValueError("Planning times must be timezone-aware.")
    if planning_start >= planning_end:
        raise ValueError("Planning start time must be before planning end time.")

    old_plan = planner_state.current_plan
    if change.change_type is not PlanningChangeType.PLAN_REPLACED:
        _validate_change_reflected_in_state(planner_state, change)
    removed_tasks: list[Task] = []
    if change.change_type is PlanningChangeType.TASK_REMOVED:
        if change.task is None:
            raise ValueError("Task changes must identify a task.")
        removed_tasks.append(change.task)
    if not change_affects_plan(change):
        if old_plan is not None:
            return build_replanning_result(
                old_plan,
                list(old_plan.schedule_blocks),
                [],
                [],
                [],
            )
        empty_plan = Plan(
            id="daypilot-plan",
            date=planning_start,
            planning_horizon=planning_end - planning_start,
            schedule_blocks=[],
            metadata={},
        )
        return build_replanning_result(empty_plan, [], [], [], [])

    if old_plan is None:
        invalidated: list[ScheduleBlock] = []
        preserved: list[ScheduleBlock] = []
        tasks = {
            task for task in planner_state.tasks
            if task.is_atomic
            and task.status in (TaskStatus.NOT_STARTED, TaskStatus.IN_PROGRESS)
            and all(task is not removed for removed in removed_tasks)
        }
        remaining = recover_remaining_work_for_tasks(tasks, planner_state.observations)
    else:
        invalidated = calculate_invalidated_blocks(planner_state, change)
        preserved = preserve_blocks(old_plan, invalidated)
        state_task_ids = {id(task) for task in planner_state.tasks}
        tasks = {
            block.task for block in invalidated
            if id(block.task) in state_task_ids
            and all(block.task is not removed for removed in removed_tasks)
        }
        remaining = recover_remaining_work_for_tasks(tasks, planner_state.observations)

        # A newly added task has no old block to invalidate, so include it directly.
        if (change.change_type is PlanningChangeType.TASK_ADDED
                and change.task is not None
                and change.task.is_atomic
                and change.task.status in (TaskStatus.NOT_STARTED, TaskStatus.IN_PROGRESS)
                and all(work.task is not change.task for work in remaining)):
            remaining.append(RemainingWork(change.task, change.task.estimated_duration))

        may_schedule_other_work = change.change_type in {
            PlanningChangeType.CALENDAR_EVENT_UPDATED,
            PlanningChangeType.CALENDAR_EVENT_REMOVED,
            PlanningChangeType.CONSTRAINT_ADDED,
            PlanningChangeType.CONSTRAINT_UPDATED,
            PlanningChangeType.CONSTRAINT_REMOVED,
            PlanningChangeType.DEPENDENCY_REMOVED,
        }
        if may_schedule_other_work:
            planned_ids = {id(block.task) for block in preserved + invalidated}
            included_ids = {id(work.task) for work in remaining}
            other_tasks = {
                task for task in planner_state.tasks
                if task.is_atomic
                and task.status in (TaskStatus.NOT_STARTED, TaskStatus.IN_PROGRESS)
                and task.scheduling_status is SchedulingStatus.UNSCHEDULED
                and id(task) not in planned_ids
                and id(task) not in included_ids
                and all(task is not removed for removed in removed_tasks)
            }
            remaining.extend(
                recover_remaining_work_for_tasks(other_tasks, planner_state.observations)
            )

    available = rebuild_available_windows(
        planner_state, preserved, planning_start, planning_end
    )
    soft_constraints = [
        constraint for constraint in planner_state.constraints
        if constraint.type is ConstraintType.SOFT_CONSTRAINT
    ]
    run = schedule_remaining_work(
        remaining,
        available,
        soft_constraints,
        planner_state.dependency_graph,
        preserved,
    )
    rescheduled = list(run.scheduled_blocks)
    durations = {work.task: work.duration for work in remaining}
    unresolved = [RemainingWork(result.task, durations[result.task])
                  for result in run.unresolved_task_results]
    merged = merge_schedule_blocks(preserved, rescheduled)

    new_plan = build_replanned_plan(
        old_plan,
        merged,
        planning_start,
        planning_end - planning_start,
    )
    return build_replanning_result(
        new_plan, preserved, invalidated, rescheduled, unresolved, removed_tasks
    )

def resource_invalidated_blocks(
    plan: Plan | None,
    change: PlanningChange,
) -> list[ScheduleBlock]:
    if plan is None:
        return []

    if change is None:
        raise ValueError("Planning change cannot be None.")

    if change.change_type in {
        PlanningChangeType.CALENDAR_EVENT_ADDED,
        PlanningChangeType.CALENDAR_EVENT_UPDATED,
    }:
        event = change.metadata["event"]

        return [
            block
            for block in plan.schedule_blocks
            if block.start < event.end
            and event.start < block.end
        ]

    if change.change_type is PlanningChangeType.CALENDAR_EVENT_REMOVED:
        return []

    if change.change_type in {
        PlanningChangeType.CONSTRAINT_ADDED,
        PlanningChangeType.CONSTRAINT_UPDATED,
    }:
        constraint = change.metadata["constraint"]

        if constraint.type is not ConstraintType.HARD_CONSTRAINT:
            return []

        window = constraint.rule_information

        return [
            block
            for block in plan.schedule_blocks
            if block.start < window.end
            and window.start < block.end
        ]

    if change.change_type is PlanningChangeType.CONSTRAINT_REMOVED:
        return []

    return []


def calculate_invalidated_blocks(
    planner_state: PlannerState,
    change: PlanningChange,
) -> list[ScheduleBlock]:
    """Return scheduled blocks invalidated by a planning environment change."""
    if planner_state is None:
        raise ValueError("Planner state cannot be None.")
    if change is None:
        raise ValueError("Planning change cannot be None.")

    plan = planner_state.current_plan
    if plan is None or not change_affects_plan(change):
        return []

    affected = invalidated_blocks(
        plan,
        affected_tasks(change, planner_state.dependency_graph),
    )
    dependency_tasks = affected_tasks_for_dependency_change(
        change,
        planner_state.dependency_graph,
    )
    affected.extend(invalidated_blocks(plan, dependency_tasks))
    affected.extend(resource_invalidated_blocks(plan, change))

    # A prerequisite block that is invalidated by a resource change can make
    # every scheduled dependent block chronologically invalid as well.
    impacted_tasks = {block.task for block in affected}
    pending_tasks = list(impacted_tasks)
    while pending_tasks:
        task = pending_tasks.pop()
        if planner_state.dependency_graph.tasks.get(task.id) is not task:
            continue
        for dependent in planner_state.dependency_graph.get_dependents(task):
            if dependent not in impacted_tasks:
                impacted_tasks.add(dependent)
                pending_tasks.append(dependent)
    affected.extend(invalidated_blocks(plan, impacted_tasks))
    affected.extend(
        block for block in plan.schedule_blocks
        if block.task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)
    )
    affected_ids = {id(block) for block in affected}
    return sorted(
        (block for block in plan.schedule_blocks if id(block) in affected_ids),
        key=lambda block: block.start,
    )

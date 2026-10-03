from datetime import datetime, timedelta, timezone
from typing import Any, cast

import pytest

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import (
    ConstraintType,
    ObservationOutcome,
    PlanningChangeType,
    Priority,
    SchedulingStatus,
    TaskStatus,
)
from daypilot.domain.observation import Observation, calculate_observation_history_summary
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import (
    RemainingWork,
    ReplanningResult,
    apply_replanning_result,
    recover_remaining_work,
    replan,
    PlanningChange,
    calculate_invalidated_blocks,
)
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task
from daypilot.domain.times import CalendarEvent, Constraint, TimeWindow


DATE = datetime(2026, 9, 28, tzinfo=timezone.utc)
HORIZON = timedelta(hours=8)


def make_task(task_id: str) -> Task:
    return Task(
        id=task_id,
        title=task_id,
        status=TaskStatus.NOT_STARTED,
        priority=Priority.MEDIUM,
        estimated_duration=timedelta(hours=1),
    )


def make_plan(plan_id: str, *tasks: Task) -> Plan:
    return Plan(
        id=plan_id,
        date=DATE,
        planning_horizon=HORIZON,
        schedule_blocks=[
            ScheduleBlock(task, DATE + timedelta(hours=index), DATE + timedelta(hours=index + 1))
            for index, task in enumerate(tasks)
        ],
        metadata={},
    )


def make_result(plan: Plan) -> ReplanningResult:
    return ReplanningResult(plan, [], [], [], [])


def make_state(tasks: list[Task], current_plan: Plan | None) -> PlannerState:
    graph = DependencyGraph()
    for task in tasks:
        graph.register_task(task)
    return PlannerState([], tasks, graph, [], [], current_plan, [])


def test_apply_replanning_result_replaces_plan_and_scheduling_statuses():
    task_a, task_b = make_task("A"), make_task("B")
    old_plan = make_plan("old", task_b)
    # Keep the initial statuses consistent with the old plan.
    task_b.scheduling_status = SchedulingStatus.SCHEDULED
    state = make_state([task_a, task_b], old_plan)
    new_plan = make_plan("new", task_a)

    apply_replanning_result(state, make_result(new_plan))

    assert state.current_plan is new_plan
    assert task_a.scheduling_status is SchedulingStatus.SCHEDULED
    assert task_b.scheduling_status is SchedulingStatus.UNSCHEDULED


def test_invalid_replanning_result_leaves_state_unchanged():
    task_a, task_b, outside_task = make_task("A"), make_task("B"), make_task("outside")
    old_plan = make_plan("old", task_a)
    task_a.scheduling_status = SchedulingStatus.SCHEDULED
    state = make_state([task_a, task_b], old_plan)
    statuses_before = [task.scheduling_status for task in state.tasks]

    with pytest.raises(ValueError):
        apply_replanning_result(state, make_result(make_plan("invalid", outside_task)))

    assert state.current_plan is old_plan
    assert [task.scheduling_status for task in state.tasks] == statuses_before


def test_invalid_dependency_plan_with_staged_removal_is_atomic():
    removed, prerequisite, dependent = make_task("removed"), make_task("A"), make_task("B")
    block_removed = ScheduleBlock(removed, DATE, DATE + timedelta(hours=1))
    block_prerequisite = ScheduleBlock(
        prerequisite,
        DATE + timedelta(hours=1),
        DATE + timedelta(hours=2),
    )
    block_dependent = ScheduleBlock(
        dependent,
        DATE + timedelta(hours=2),
        DATE + timedelta(hours=3),
    )
    for task in (removed, prerequisite, dependent):
        task.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = Plan(
        "old",
        DATE,
        HORIZON,
        [block_removed, block_prerequisite, block_dependent],
        {},
    )
    state = make_state([removed, prerequisite, dependent], old_plan)
    state.add_dependency(dependent, prerequisite)
    invalid_plan = Plan(
        "invalid",
        DATE,
        HORIZON,
        [
            ScheduleBlock(dependent, DATE, DATE + timedelta(hours=1)),
            ScheduleBlock(prerequisite, DATE + timedelta(hours=1), DATE + timedelta(hours=2)),
        ],
        {},
    )
    statuses_before = [task.scheduling_status for task in state.tasks]
    tasks_before = list(state.tasks)
    graph_before = {
        task_id: set(prerequisites)
        for task_id, prerequisites in state.dependency_graph.prerequisites.items()
    }

    with pytest.raises(ValueError, match="dependency chronology"):
        apply_replanning_result(
            state,
            ReplanningResult(invalid_plan, [], [], [], [], [removed]),
        )

    assert state.current_plan is old_plan
    assert state.current_plan is not None
    assert state.current_plan.schedule_blocks == [
        block_removed,
        block_prerequisite,
        block_dependent,
    ]
    assert state.tasks == tasks_before
    assert state.dependency_graph.prerequisites == graph_before
    assert [task.scheduling_status for task in state.tasks] == statuses_before


def test_invalid_dependency_chronology_commit_is_atomic():
    prerequisite, dependent = make_task("A"), make_task("B")
    state = make_state([prerequisite, dependent], None)
    state.add_dependency(dependent, prerequisite)
    invalid_plan = Plan(
        "invalid",
        DATE,
        HORIZON,
        [
            ScheduleBlock(dependent, DATE, DATE + timedelta(hours=1)),
            ScheduleBlock(prerequisite, DATE + timedelta(hours=1), DATE + timedelta(hours=2)),
        ],
        {},
    )
    statuses_before = [task.scheduling_status for task in state.tasks]
    graph_before = {
        task_id: set(prerequisites)
        for task_id, prerequisites in state.dependency_graph.prerequisites.items()
    }

    with pytest.raises(ValueError, match="dependency chronology"):
        apply_replanning_result(state, ReplanningResult(invalid_plan, [], [], [], []))

    assert state.current_plan is None
    assert state.tasks == [prerequisite, dependent]
    assert state.dependency_graph.prerequisites == graph_before
    assert [task.scheduling_status for task in state.tasks] == statuses_before


def test_replanning_result_rejects_completed_work_and_missing_preserved_block():
    completed = make_task("done")
    completed.status = TaskStatus.COMPLETED
    completed_block = ScheduleBlock(completed, DATE, DATE + timedelta(hours=1))
    invalid_plan = Plan("invalid", DATE, HORIZON, [completed_block], {})
    with pytest.raises(ValueError, match="Completed or cancelled"):
        ReplanningResult(invalid_plan, [], [], [], [])

    task = make_task("A")
    preserved = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    empty_plan = Plan("empty", DATE, HORIZON, [], {})
    with pytest.raises(ValueError, match="Preserved blocks"):
        ReplanningResult(empty_plan, [preserved], [], [], [])


def test_replanning_result_rejects_duplicate_blocks_across_collections():
    task = make_task("A")
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    plan = Plan("plan", DATE, HORIZON, [block], {})

    with pytest.raises(ValueError, match="duplicate blocks"):
        ReplanningResult(plan, [block], [], [block], [])


def test_replanning_result_rejects_invalidated_block_left_in_new_plan():
    task = make_task("A")
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    plan = Plan("plan", DATE, HORIZON, [block], {})

    with pytest.raises(ValueError, match="Invalidated blocks"):
        ReplanningResult(plan, [], [block], [], [])


def test_replanning_result_rejects_unresolved_work_that_is_scheduled():
    task = make_task("A")
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    plan = Plan("plan", DATE, HORIZON, [block], {})

    with pytest.raises(ValueError, match="also be scheduled"):
        ReplanningResult(
            plan,
            [],
            [],
            [block],
            [RemainingWork(task, timedelta(hours=1))],
        )


def test_remaining_work_requires_valid_task_and_duration():
    with pytest.raises(ValueError):
        RemainingWork(cast(Task, None), timedelta(hours=1))
    with pytest.raises(ValueError):
        RemainingWork(make_task("invalid-duration"), cast(timedelta, "1 hour"))
    with pytest.raises(ValueError):
        RemainingWork(make_task("zero-duration"), timedelta(0))


def test_replanning_result_rejects_duplicate_removed_tasks():
    task = make_task("A")
    plan = Plan("plan", DATE, HORIZON, [], {})

    with pytest.raises(ValueError, match="Removed tasks"):
        ReplanningResult(plan, [], [], [], [], [task, task])


def test_planning_change_rejects_invalid_metadata_and_changed_fields():
    task = make_task("A")
    with pytest.raises(ValueError, match="metadata"):
        PlanningChange(
            PlanningChangeType.TASK_UPDATED,
            task=task,
            metadata=cast(dict[str, Any], []),
        )
    with pytest.raises(ValueError, match="only strings"):
        PlanningChange(
            PlanningChangeType.TASK_UPDATED,
            task=task,
            metadata={"changed_fields": {"priority", 1}},
        )


def test_apply_rejects_corrupt_task_tree_before_mutating_plan_or_statuses():
    parent, child = make_task("parent"), make_task("child")
    parent.children.append(child)
    child.parent = parent
    old_plan = Plan("old", DATE, HORIZON, [], {})
    state = make_state([parent, child], old_plan)
    # Simulate an out-of-band mutation after valid aggregate construction.
    parent.children.clear()
    statuses_before = [task.scheduling_status for task in state.tasks]

    with pytest.raises(ValueError, match="missing from its parent's children"):
        apply_replanning_result(state, make_result(Plan("new", DATE, HORIZON, [], {})))

    assert state.current_plan is old_plan
    assert [task.scheduling_status for task in state.tasks] == statuses_before


def test_apply_replanning_result_succeeds_when_existing_plan_is_none():
    task = make_task("A")
    state = make_state([task], None)
    new_plan = make_plan("new", task)

    apply_replanning_result(state, make_result(new_plan))

    assert state.current_plan is new_plan
    assert task.scheduling_status is SchedulingStatus.SCHEDULED


def test_replan_invalidates_calendar_overlap_and_preserves_other_blocks():
    task_a, task_b = make_task("A"), make_task("B")
    old_plan = make_plan("old", task_a, task_b)
    task_a.scheduling_status = task_b.scheduling_status = SchedulingStatus.SCHEDULED
    state = make_state([task_a, task_b], old_plan)
    event = CalendarEvent(
        "event", "Busy", DATE + timedelta(hours=1, minutes=30),
        DATE + timedelta(hours=2, minutes=30),
    )
    state.calendar_events.append(event)

    result = replan(
        state,
        PlanningChange(PlanningChangeType.CALENDAR_EVENT_ADDED, metadata={"event": event}),
        DATE,
        DATE + HORIZON,
    )

    assert result.preserved_blocks == [old_plan.schedule_blocks[0]]
    assert result.invalidated_blocks == [old_plan.schedule_blocks[1]]
    assert result.rescheduled_blocks[0].task is task_b
    assert result.rescheduled_blocks[0].start == DATE + timedelta(hours=2, minutes=30)
    assert state.current_plan is old_plan
    assert task_a.scheduling_status is SchedulingStatus.SCHEDULED
    apply_replanning_result(state, result)
    assert state.current_plan is result.new_plan


def test_replan_uses_remaining_duration_from_partial_observation():
    task = make_task("A")
    task.estimated_duration = timedelta(hours=2)
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=2))
    task.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = Plan("old", DATE, HORIZON, [block], {})
    observation = Observation(
        task, block, DATE, DATE + timedelta(minutes=45),
        ObservationOutcome.PARTIALLY_COMPLETED,
    )
    task.status = TaskStatus.IN_PROGRESS
    state = make_state([task], old_plan)
    state.record_observation(observation)
    assert task.scheduling_status is SchedulingStatus.SCHEDULED

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.OBSERVATION_RECORDED,
            metadata={"observation": observation},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert result.rescheduled_blocks[0].end - result.rescheduled_blocks[0].start == timedelta(hours=1, minutes=15)
    assert old_plan.schedule_blocks == [block]
    assert task.scheduling_status is SchedulingStatus.SCHEDULED
    assert state.current_plan is old_plan
    apply_replanning_result(state, result)
    assert state.current_plan is result.new_plan


@pytest.mark.parametrize(
    "outcome",
    [ObservationOutcome.COMPLETED, ObservationOutcome.CANCELLED],
)
def test_terminal_observation_removes_work_without_rescheduling(outcome):
    task = make_task("A")
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    task.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = Plan("old", DATE, HORIZON, [block], {})
    observation = Observation(
        task,
        block,
        DATE,
        DATE + timedelta(minutes=30),
        outcome,
    )
    state = make_state([task], old_plan)
    state.record_observation(observation)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.OBSERVATION_RECORDED,
            metadata={"observation": observation},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert result.invalidated_blocks == [block]
    assert result.rescheduled_blocks == []
    assert result.unresolved_work == []
    assert state.current_plan is old_plan
    apply_replanning_result(state, result)
    assert task.scheduling_status is SchedulingStatus.UNSCHEDULED
    assert state.current_plan is result.new_plan


def test_task_priority_update_invalidates_and_reschedules_only_updated_task():
    task_a, task_b = make_task("A"), make_task("B")

    block_a = ScheduleBlock(task_a, DATE, DATE + timedelta(hours=1))
    block_b = ScheduleBlock(
        task_b,
        DATE + timedelta(hours=1),
        DATE + timedelta(hours=2),
    )

    task_a.scheduling_status = SchedulingStatus.SCHEDULED
    task_b.scheduling_status = SchedulingStatus.SCHEDULED

    old_plan = Plan("old", DATE, HORIZON, [block_a, block_b], {})
    state = make_state([task_a, task_b], old_plan)

    task_a.priority = Priority.CRITICAL

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.TASK_UPDATED,
            task=task_a,
            metadata={"changed_fields": {"priority"}},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert result.invalidated_blocks == [block_a]
    assert result.preserved_blocks == [block_b]
    assert len(result.rescheduled_blocks) == 1
    assert result.rescheduled_blocks[0].task is task_a
    assert result.rescheduled_blocks[0].start == DATE
    assert state.current_plan is old_plan
    assert old_plan.schedule_blocks == [block_a, block_b]


def test_task_deadline_update_invalidates_and_reconsiders_task():
    task = make_task("A")
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    task.scheduling_status = SchedulingStatus.SCHEDULED

    old_plan = Plan("old", DATE, HORIZON, [block], {})
    state = make_state([task], old_plan)

    task.deadline = DATE + timedelta(hours=2)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.TASK_UPDATED,
            task=task,
            metadata={"changed_fields": {"deadline"}},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert result.invalidated_blocks == [block]
    assert result.preserved_blocks == []
    assert len(result.rescheduled_blocks) == 1
    assert result.rescheduled_blocks[0].task is task
    assert result.rescheduled_blocks[0].end <= task.deadline
    assert result.unresolved_work == []
    assert state.current_plan is old_plan


def test_soft_constraint_too_small_does_not_block_task():
    task = make_task("A")
    state = make_state([task], None)

    preference = Constraint(
        ConstraintType.SOFT_CONSTRAINT,
        TimeWindow(
            DATE + timedelta(hours=2),
            DATE + timedelta(hours=2, minutes=30),
        ),
    )
    state.add_constraint(preference)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.CONSTRAINT_ADDED,
            metadata={"constraint": preference},
        ),
        DATE,
        DATE + timedelta(hours=4),
    )

    assert result.unresolved_work == []
    assert len(result.rescheduled_blocks) == 1
    block = result.rescheduled_blocks[0]
    assert block.task is task
    assert block.end - block.start == timedelta(hours=1)
    assert not (
        block.start >= preference.rule_information.start
        and block.end <= preference.rule_information.end
    )


@pytest.mark.parametrize(
    ("outcome", "elapsed", "expected"),
    [
        (ObservationOutcome.COMPLETED, 30, timedelta(0)),
        (ObservationOutcome.PARTIALLY_COMPLETED, 30, timedelta(minutes=30)),
        (ObservationOutcome.PARTIALLY_COMPLETED, 90, timedelta(0)),
        (ObservationOutcome.CANCELLED, 30, timedelta(0)),
        (ObservationOutcome.NOT_STARTED, 30, timedelta(hours=1)),
    ],
)
def test_observation_history_recovers_expected_remaining_work(outcome, elapsed, expected):
    task = make_task("A")
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    observation = Observation(
        task, block, DATE, DATE + timedelta(minutes=elapsed), outcome
    )

    summary = calculate_observation_history_summary(task, [observation])

    assert summary.remaining_duration == expected


def test_recover_remaining_work_without_history_uses_full_estimate():
    task = make_task("A")

    remaining = recover_remaining_work(task, [])

    assert remaining is not None
    assert remaining.duration == task.estimated_duration


def test_replan_without_an_old_plan_schedules_registered_work_without_mutating_state():
    task = make_task("A")
    state = make_state([task], None)

    result = replan(
        state,
        PlanningChange(PlanningChangeType.TASK_ADDED, task=task),
        DATE,
        DATE + HORIZON,
    )

    assert len(result.rescheduled_blocks) == 1
    assert result.new_plan.schedule_blocks == result.rescheduled_blocks
    assert state.current_plan is None
    assert task.scheduling_status is SchedulingStatus.UNSCHEDULED
    apply_replanning_result(state, result)
    assert state.current_plan is result.new_plan


def test_dependency_addition_reschedules_dependent_after_prerequisite():
    task_a, task_b = make_task("A"), make_task("B")
    block_b = ScheduleBlock(task_b, DATE, DATE + timedelta(hours=1))
    block_a = ScheduleBlock(
        task_a,
        DATE + timedelta(hours=1),
        DATE + timedelta(hours=2),
    )
    task_a.scheduling_status = task_b.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = Plan("old", DATE, HORIZON, [block_b, block_a], {})
    state = make_state([task_a, task_b], old_plan)
    state.add_dependency(task_b, task_a)
    old_blocks = list(old_plan.schedule_blocks)
    old_tasks = list(state.tasks)
    old_statuses = [task.scheduling_status for task in state.tasks]
    old_task_statuses = [task.status for task in state.tasks]
    old_graph = {
        task_id: set(prerequisites)
        for task_id, prerequisites in state.dependency_graph.prerequisites.items()
    }

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.DEPENDENCY_ADDED,
            metadata={"dependent": task_b, "prerequisite": task_a},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert result.invalidated_blocks == [block_b]
    assert result.preserved_blocks == [block_a]
    assert len(result.rescheduled_blocks) == 1
    assert result.rescheduled_blocks[0].task is task_b
    assert result.rescheduled_blocks[0].start == DATE + timedelta(hours=2)
    assert result.rescheduled_blocks[0].end == DATE + timedelta(hours=3)
    assert result.unresolved_work == []
    assert old_plan.schedule_blocks == old_blocks
    assert state.tasks == old_tasks
    assert [task.scheduling_status for task in state.tasks] == old_statuses
    assert [task.status for task in state.tasks] == old_task_statuses
    assert state.dependency_graph.prerequisites == old_graph
    assert state.current_plan is old_plan

    apply_replanning_result(state, result)
    assert state.current_plan is result.new_plan
    assert state.current_plan is not None
    assert state.current_plan.schedule_blocks == [block_a, result.rescheduled_blocks[0]]


def test_dependency_addition_only_invalidates_direct_dependent():
    task_a, task_b, task_c = make_task("A"), make_task("B"), make_task("C")
    block_c = ScheduleBlock(task_c, DATE, DATE + timedelta(hours=1))
    block_b = ScheduleBlock(
        task_b,
        DATE + timedelta(hours=1),
        DATE + timedelta(hours=2),
    )
    block_a = ScheduleBlock(
        task_a,
        DATE + timedelta(hours=2),
        DATE + timedelta(hours=3),
    )
    for task in (task_a, task_b, task_c):
        task.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = Plan("old", DATE, HORIZON, [block_c, block_b, block_a], {})
    state = make_state([task_a, task_b, task_c], old_plan)
    state.add_dependency(task_b, task_a)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.DEPENDENCY_ADDED,
            metadata={"dependent": task_b, "prerequisite": task_a},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert result.preserved_blocks == [block_c, block_a]
    assert result.invalidated_blocks == [block_b]
    assert len(result.rescheduled_blocks) == 1
    assert result.rescheduled_blocks[0].task is task_b
    assert result.rescheduled_blocks[0].start == DATE + timedelta(hours=3)
    assert result.rescheduled_blocks[0].end == DATE + timedelta(hours=4)


def test_dependency_addition_invalidates_transitive_dependents():
    task_a, task_b, task_c, task_x = (
        make_task("A"), make_task("B"), make_task("C"), make_task("X")
    )
    block_a = ScheduleBlock(task_a, DATE, DATE + timedelta(hours=1))
    block_b = ScheduleBlock(
        task_b,
        DATE + timedelta(hours=1),
        DATE + timedelta(hours=2),
    )
    block_c = ScheduleBlock(
        task_c,
        DATE + timedelta(hours=2),
        DATE + timedelta(hours=3),
    )
    block_x = ScheduleBlock(
        task_x,
        DATE + timedelta(hours=3),
        DATE + timedelta(hours=4),
    )
    for task in (task_a, task_b, task_c, task_x):
        task.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = Plan("old", DATE, HORIZON, [block_a, block_b, block_c, block_x], {})
    state = make_state([task_a, task_b, task_c, task_x], old_plan)
    state.add_dependency(task_b, task_a)
    state.add_dependency(task_c, task_b)
    state.add_dependency(task_a, task_x)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.DEPENDENCY_ADDED,
            metadata={"dependent": task_a, "prerequisite": task_x},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert {block.task for block in result.invalidated_blocks} == {
        task_a,
        task_b,
        task_c,
    }
    assert result.preserved_blocks == [block_x]
    assert [block.task for block in result.rescheduled_blocks] == [
        task_a,
        task_b,
        task_c,
    ]
    assert all(
        previous.end <= current.start
        for previous, current in zip(
            result.rescheduled_blocks, result.rescheduled_blocks[1:]
        )
    )
    assert result.rescheduled_blocks[0].start >= block_x.end


def test_dependency_removal_preserves_valid_schedule():
    task_a, task_b = make_task("A"), make_task("B")
    block_a = ScheduleBlock(task_a, DATE, DATE + timedelta(hours=1))
    block_b = ScheduleBlock(
        task_b,
        DATE + timedelta(hours=1),
        DATE + timedelta(hours=2),
    )
    task_a.scheduling_status = task_b.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = Plan("old", DATE, HORIZON, [block_a, block_b], {})
    state = make_state([task_a, task_b], old_plan)
    state.add_dependency(task_b, task_a)
    state.remove_dependency(task_b, task_a)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.DEPENDENCY_REMOVED,
            metadata={"dependent": task_b, "prerequisite": task_a},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert result.invalidated_blocks == []
    assert result.preserved_blocks == old_plan.schedule_blocks
    assert result.rescheduled_blocks == []


def test_dependency_addition_reports_unresolved_work_when_no_valid_slot_exists():
    task_a, task_b = make_task("A"), make_task("B")
    task_a.estimated_duration = timedelta(hours=2)
    block_b = ScheduleBlock(task_b, DATE, DATE + timedelta(hours=1))
    block_a = ScheduleBlock(
        task_a,
        DATE + timedelta(hours=1),
        DATE + timedelta(hours=3),
    )
    task_a.scheduling_status = task_b.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = Plan("old", DATE, timedelta(hours=3), [block_b, block_a], {})
    state = make_state([task_a, task_b], old_plan)
    state.add_dependency(task_b, task_a)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.DEPENDENCY_ADDED,
            metadata={"dependent": task_b, "prerequisite": task_a},
        ),
        DATE,
        DATE + timedelta(hours=3),
    )

    assert result.invalidated_blocks == [block_b]
    assert result.rescheduled_blocks == []
    assert len(result.unresolved_work) == 1
    assert result.unresolved_work[0].task is task_b
    assert result.unresolved_work[0].duration == timedelta(hours=1)


def test_dependency_addition_with_completed_prerequisite_does_not_delay_task():
    task_a, task_b = make_task("A"), make_task("B")
    task_a.status = TaskStatus.COMPLETED
    block_b = ScheduleBlock(task_b, DATE, DATE + timedelta(hours=1))
    task_b.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = Plan("old", DATE, HORIZON, [block_b], {})
    state = make_state([task_a, task_b], old_plan)
    state.add_dependency(task_b, task_a)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.DEPENDENCY_ADDED,
            metadata={"dependent": task_b, "prerequisite": task_a},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert len(result.rescheduled_blocks) == 1
    assert result.rescheduled_blocks[0].task is task_b
    assert result.rescheduled_blocks[0].start == DATE


def test_dependency_addition_rejects_cycle_without_mutating_graph():
    task_a, task_b, task_c = make_task("A"), make_task("B"), make_task("C")
    state = make_state([task_a, task_b, task_c], None)
    state.add_dependency(task_b, task_a)
    state.add_dependency(task_c, task_b)
    before = {
        task_id: set(prerequisites)
        for task_id, prerequisites in state.dependency_graph.prerequisites.items()
    }

    with pytest.raises(ValueError):
        state.add_dependency(task_a, task_c)

    assert state.dependency_graph.prerequisites == before
    assert not state.dependency_graph.has_dependency(task_a, task_c)


def test_dependency_chain_never_violates_order_when_prerequisite_window_is_blocked():
    task_a, task_b, task_c = make_task("A"), make_task("B"), make_task("C")
    task_a.scheduling_status = SchedulingStatus.SCHEDULED
    task_b.scheduling_status = SchedulingStatus.SCHEDULED
    task_c.scheduling_status = SchedulingStatus.SCHEDULED
    block_a = ScheduleBlock(task_a, DATE, DATE + timedelta(hours=1))
    block_b = ScheduleBlock(
        task_b,
        DATE + timedelta(hours=1),
        DATE + timedelta(hours=2),
    )
    block_c = ScheduleBlock(
        task_c,
        DATE + timedelta(hours=2),
        DATE + timedelta(hours=3),
    )
    old_plan = Plan("old", DATE, HORIZON, [block_a, block_b, block_c], {})
    state = make_state([task_a, task_b, task_c], old_plan)
    state.add_dependency(task_b, task_a)
    state.add_dependency(task_c, task_b)
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(DATE, DATE + timedelta(hours=1)),
    )
    state.add_constraint(constraint)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.CONSTRAINT_ADDED,
            metadata={"constraint": constraint},
        ),
        DATE,
        DATE + HORIZON,
    )

    assert all(
        prerequisite.status is TaskStatus.COMPLETED
        or any(
            block.task is prerequisite and block.end <= candidate.start
            for block in result.new_plan.schedule_blocks
        )
        for candidate in result.new_plan.schedule_blocks
        for prerequisite in state.dependency_graph.get_prerequisites(candidate.task)
    )


def test_removing_scheduled_task_is_staged_until_replanning_result_applies():
    task, survivor = make_task("A"), make_task("B")
    old_plan = make_plan("old", task, survivor)
    removed_block, survivor_block = old_plan.schedule_blocks
    task.scheduling_status = survivor.scheduling_status = SchedulingStatus.SCHEDULED
    state = make_state([task, survivor], old_plan)

    assert state.current_plan is old_plan
    result = replan(
        state,
        PlanningChange(PlanningChangeType.TASK_REMOVED, task=task),
        DATE,
        DATE + HORIZON,
    )
    assert result.invalidated_blocks == [removed_block]
    assert result.preserved_blocks == [survivor_block]
    assert result.rescheduled_blocks == []
    assert result.unresolved_work == []
    assert result.removed_tasks == [task]
    assert all(block.task is not task for block in result.new_plan.schedule_blocks)
    assert [block.task for block in result.new_plan.schedule_blocks] == [survivor]
    assert state.current_plan is old_plan
    assert old_plan.schedule_blocks == [removed_block, survivor_block]
    assert state.tasks == [task, survivor]
    apply_replanning_result(state, result)
    assert state.current_plan is result.new_plan
    assert state.tasks == [survivor]
    assert state.dependency_graph.tasks.get(task.id) is None


def test_commit_rejects_replacement_plan_containing_removed_task_atomically():
    task = make_task("A")
    old_plan = make_plan("old", task)
    task.scheduling_status = SchedulingStatus.SCHEDULED
    state = make_state([task], old_plan)
    statuses_before = [item.scheduling_status for item in state.tasks]

    with pytest.raises(ValueError, match="Removed tasks cannot appear"):
        state.commit_replanned_plan(make_plan("invalid", task), [task])

    assert state.current_plan is old_plan
    assert state.tasks == [task]
    assert state.dependency_graph.tasks.get(task.id) is task
    assert [item.scheduling_status for item in state.tasks] == statuses_before


def test_unscheduled_task_can_be_removed_directly():
    task = make_task("A")
    state = make_state([task], None)

    state.remove_task(task)

    assert state.tasks == []
    assert state.dependency_graph.tasks.get(task.id) is None


def test_task_with_dependency_cannot_be_removed():
    prerequisite, dependent = make_task("A"), make_task("B")
    state = make_state([prerequisite, dependent], None)
    state.add_dependency(dependent, prerequisite)

    with pytest.raises(ValueError, match="dependents"):
        state.remove_task(prerequisite)

    assert state._contains_task(prerequisite)
    assert state.dependency_graph.tasks.get(prerequisite.id) is prerequisite


def test_task_update_metadata_does_not_invalidate_schedule_but_duration_does():
    task = make_task("A")
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    task.scheduling_status = SchedulingStatus.SCHEDULED
    plan = Plan("old", DATE, HORIZON, [block], {})
    state = make_state([task], plan)

    metadata_result = replan(
        state,
        PlanningChange(
            PlanningChangeType.TASK_UPDATED,
            task=task,
            metadata={"changed_fields": ["title", "description"]},
        ),
        DATE,
        DATE + HORIZON,
    )
    assert metadata_result.invalidated_blocks == []
    assert metadata_result.preserved_blocks == [block]
    assert state.current_plan is plan

    task.estimated_duration += timedelta(minutes=30)
    duration_result = replan(
        state,
        PlanningChange(
            PlanningChangeType.TASK_UPDATED,
            task=task,
            metadata={"changed_fields": ["estimated_duration"]},
        ),
        DATE,
        DATE + HORIZON,
    )
    assert duration_result.invalidated_blocks == [block]
    assert duration_result.rescheduled_blocks[0].end - duration_result.rescheduled_blocks[0].start == timedelta(hours=1, minutes=30)
    assert state.current_plan is plan


def test_task_duration_update_invalidates_and_reschedules_task():
    planning_start = DATE + timedelta(hours=9)
    planning_end = DATE + timedelta(hours=14)
    task_a = make_task("A")
    task_a.scheduling_status = SchedulingStatus.SCHEDULED
    old_block = ScheduleBlock(
        task_a, planning_start, planning_start + timedelta(hours=1)
    )
    old_plan = Plan(
        "old", planning_start, planning_end - planning_start, [old_block], {}
    )
    state = make_state([task_a], old_plan)

    task_a.estimated_duration = timedelta(hours=2)
    assert task_a.estimated_duration == timedelta(hours=2)

    result = replan(
        state,
        PlanningChange(
            PlanningChangeType.TASK_UPDATED,
            task=task_a,
            metadata={"changed_fields": {"estimated_duration"}},
        ),
        planning_start,
        planning_end,
    )

    assert state.current_plan is old_plan
    assert result.invalidated_blocks == [old_block]
    assert result.preserved_blocks == []
    assert len(result.rescheduled_blocks) == 1
    assert result.rescheduled_blocks[0].task is task_a
    assert result.rescheduled_blocks[0].start == planning_start
    assert result.rescheduled_blocks[0].end == planning_start + timedelta(hours=2)
    assert old_plan.schedule_blocks == [old_block]
    assert result.rescheduled_blocks[0].end - result.rescheduled_blocks[0].start == timedelta(hours=2)

    apply_replanning_result(state, result)
    assert state.current_plan is result.new_plan


def test_removed_calendar_event_frees_time_for_unscheduled_work():
    scheduled, waiting = make_task("A"), make_task("B")
    scheduled.scheduling_status = SchedulingStatus.SCHEDULED
    block = ScheduleBlock(scheduled, DATE, DATE + timedelta(hours=1))
    old_plan = Plan("old", DATE, timedelta(hours=4), [block], {})
    state = make_state([scheduled, waiting], old_plan)
    event = CalendarEvent(
        "busy", "Busy", DATE + timedelta(hours=1), DATE + timedelta(hours=3)
    )
    state.add_calendar_event(event)
    state.remove_calendar_event(event)

    result = replan(
        state,
        PlanningChange(PlanningChangeType.CALENDAR_EVENT_REMOVED, metadata={"event": event}),
        DATE,
        DATE + timedelta(hours=4),
    )

    assert result.preserved_blocks == [block]
    assert result.invalidated_blocks == []
    assert result.rescheduled_blocks[0].task is waiting
    assert result.rescheduled_blocks[0].start == DATE + timedelta(hours=1)
    assert state.current_plan is old_plan


def test_updated_calendar_event_uses_post_change_interval_for_invalidation():
    first, second = make_task("A"), make_task("B")
    first.scheduling_status = second.scheduling_status = SchedulingStatus.SCHEDULED
    old_plan = make_plan("old", first, second)
    state = make_state([first, second], old_plan)
    event = CalendarEvent("event", "Busy", DATE + timedelta(hours=3), DATE + timedelta(hours=4))
    state.add_calendar_event(event)
    # The update is reflected in the event object before replan is called.
    event.start = DATE + timedelta(minutes=30)
    event.end = DATE + timedelta(hours=1, minutes=30)

    result = replan(
        state,
        PlanningChange(PlanningChangeType.CALENDAR_EVENT_UPDATED, metadata={"event": event}),
        DATE,
        DATE + timedelta(hours=4),
    )

    assert result.invalidated_blocks == old_plan.schedule_blocks
    assert result.preserved_blocks == []
    assert {block.task for block in result.rescheduled_blocks} == {first, second}
    assert all(block.start >= event.end for block in result.rescheduled_blocks)
    assert state.current_plan is old_plan


def test_removed_hard_constraint_frees_time_for_unscheduled_work():
    scheduled, waiting = make_task("A"), make_task("B")
    scheduled.scheduling_status = SchedulingStatus.SCHEDULED
    block = ScheduleBlock(scheduled, DATE, DATE + timedelta(hours=1))
    old_plan = Plan("old", DATE, timedelta(hours=4), [block], {})
    state = make_state([scheduled, waiting], old_plan)
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(DATE + timedelta(hours=1), DATE + timedelta(hours=3)),
    )
    state.add_constraint(constraint)
    state.remove_constraint(constraint)

    result = replan(
        state,
        PlanningChange(PlanningChangeType.CONSTRAINT_REMOVED, metadata={"constraint": constraint}),
        DATE,
        DATE + timedelta(hours=4),
    )

    assert result.invalidated_blocks == []
    assert result.preserved_blocks == [block]
    assert result.rescheduled_blocks[0].task is waiting
    assert result.rescheduled_blocks[0].start == DATE + timedelta(hours=1)


def test_hard_constraint_addition_invalidates_and_moves_overlapping_task():
    task = make_task("A")
    task.scheduling_status = SchedulingStatus.SCHEDULED
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    plan = Plan("old", DATE, HORIZON, [block], {})
    state = make_state([task], plan)
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(DATE, DATE + timedelta(hours=1)),
    )
    state.add_constraint(constraint)

    result = replan(
        state,
        PlanningChange(PlanningChangeType.CONSTRAINT_ADDED, metadata={"constraint": constraint}),
        DATE,
        DATE + HORIZON,
    )

    assert result.invalidated_blocks == [block]
    assert result.rescheduled_blocks[0].start == DATE + timedelta(hours=1)
    assert state.current_plan is plan


def test_soft_constraint_never_blocks_work_and_guides_placement():
    task = make_task("A")
    state = make_state([task], None)
    preference = Constraint(
        ConstraintType.SOFT_CONSTRAINT,
        TimeWindow(DATE + timedelta(hours=2), DATE + timedelta(hours=3)),
    )
    state.add_constraint(preference)

    result = replan(
        state,
        PlanningChange(PlanningChangeType.CONSTRAINT_ADDED, metadata={"constraint": preference}),
        DATE,
        DATE + timedelta(hours=4),
    )

    assert result.rescheduled_blocks[0].start == DATE + timedelta(hours=2)
    assert result.unresolved_work == []


def test_calendar_event_replanning_preserves_computation_until_atomic_apply():
    task_a, task_b = make_task("A"), make_task("B")
    task_a.scheduling_status = task_b.scheduling_status = SchedulingStatus.SCHEDULED
    block_a = ScheduleBlock(task_a, DATE, DATE + timedelta(hours=1))
    block_b = ScheduleBlock(
        task_b, DATE + timedelta(hours=1), DATE + timedelta(hours=2)
    )
    old_plan = Plan(
        "old",
        DATE,
        timedelta(hours=4),
        [block_a, block_b],
        {},
    )
    state = make_state([task_a, task_b], old_plan)
    event = CalendarEvent(
        "doctor-appointment",
        "Doctor Appointment",
        DATE + timedelta(hours=1, minutes=30),
        DATE + timedelta(hours=3),
    )
    state.add_calendar_event(event)
    change = PlanningChange(
        PlanningChangeType.CALENDAR_EVENT_ADDED,
        metadata={"event": event},
    )

    result = replan(state, change, DATE, DATE + timedelta(hours=4))

    assert result.preserved_blocks == [block_a]
    assert result.invalidated_blocks == [block_b]
    assert len(result.rescheduled_blocks) == 1
    assert result.rescheduled_blocks[0].task is task_b
    assert result.rescheduled_blocks[0].start == DATE + timedelta(hours=3)
    assert result.rescheduled_blocks[0].end == DATE + timedelta(hours=4)
    assert result.unresolved_work == []
    assert state.current_plan is old_plan

    apply_replanning_result(state, result)

    assert state.current_plan is result.new_plan
    assert state.current_plan is not None
    assert [
        (block.task, block.start, block.end)
        for block in state.current_plan.schedule_blocks
    ] == [
        (task_a, DATE, DATE + timedelta(hours=1)),
        (task_b, DATE + timedelta(hours=3), DATE + timedelta(hours=4)),
    ]

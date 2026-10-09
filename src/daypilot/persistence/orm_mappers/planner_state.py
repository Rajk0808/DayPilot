"""Map a complete persistence snapshot to and from its ORM rows."""

import json
from collections.abc import Iterable
from uuid import UUID

from daypilot.persistence.aggregate.planner_state import PersistedPlannerState
from daypilot.persistence.models.constraint import ConstraintRecord
from daypilot.persistence.models.dependency import DependencyRecord
from daypilot.persistence.models.planner import PlannerStateRecord
from daypilot.persistence.models.schedule import ScheduleBlockRecord
from daypilot.persistence.orm.calendar_event import CalendarEventORM
from daypilot.persistence.orm.constraint import ConstraintORM
from daypilot.persistence.orm.dependency import DependencyORM
from daypilot.persistence.orm.goal import GoalORM
from daypilot.persistence.orm.goal_root_task import GoalRootTaskORM
from daypilot.persistence.orm.observation import ObservationORM
from daypilot.persistence.orm.plan import PlanORM
from daypilot.persistence.orm.planner_state import PlannerStateORM
from daypilot.persistence.orm.schedule_block import ScheduleBlockORM
from daypilot.persistence.orm.task import TaskORM
from daypilot.persistence.orm_mappers import (
    calendar_event,
    constraint,
    dependency,
    goal,
    goal_root_task,
    observation,
    plan,
    schedule_block,
    task,
)


def to_orm(snapshot: PersistedPlannerState) -> dict[str, list[object]]:
    """Convert a validated snapshot to table-keyed ORM row collections.

    The returned mapping keys are table names. Association/ownership fields
    absent from records (state IDs, goal-root joins, and block plan membership)
    are supplied from the containing snapshot and its ID relationships.
    """
    if not isinstance(snapshot, PersistedPlannerState):
        raise TypeError("snapshot must be a PersistedPlannerState")
    snapshot.validate()
    state_id = snapshot.state_id
    plan_ids_by_block: dict[str, str] = {}
    for plan_record in snapshot.plans.values():
        for block_id in plan_record.schedule_block_ids:
            if block_id in plan_ids_by_block:
                raise ValueError(f"Schedule block {block_id!r} belongs to multiple plans.")
            plan_ids_by_block[block_id] = plan_record.id

    return {
        "planner_states": [PlannerStateORM(id=state_id, version=snapshot.version)],
        "tasks": [task.to_orm(item, state_id) for item in snapshot.tasks.values()],
        "goals": [goal.to_orm(item, state_id) for item in snapshot.goals.values()],
        "goal_root_tasks": [
            goal_root_task.to_orm(state_id, goal_record.id, task_id)
            for goal_record in snapshot.goals.values()
            for task_id in goal_record.root_task_ids
        ],
        "dependencies": [
            dependency.to_orm(state_id, item.dependent_task_id, item.prerequisite_task_id)
            for item in snapshot.dependencies.values()
        ],
        "calendar_events": [
            calendar_event.to_orm(item, state_id)
            for item in snapshot.calendar_events.values()
        ],
        "constraints": [constraint.to_orm(item, state_id) for item in snapshot.constraints.values()],
        "plans": [plan.to_orm(item, state_id) for item in snapshot.plans.values()],
        "schedule_blocks": [
            schedule_block.to_orm(
                item,
                state_id,
                plan_id=plan_ids_by_block.get(item.id),
            )
            for item in snapshot.schedule_blocks.values()
        ],
        "observations": [
            observation.to_orm(item, state_id)
            for item in snapshot.observations.values()
        ],
    }


def from_orm(
    planner_state_orm: PlannerStateORM,
    *,
    tasks: Iterable[TaskORM],
    goals: Iterable[GoalORM],
    goal_root_tasks: Iterable[GoalRootTaskORM],
    dependencies: Iterable[DependencyORM],
    calendar_events: Iterable[CalendarEventORM],
    constraints: Iterable[ConstraintORM],
    plans: Iterable[PlanORM],
    schedule_blocks: Iterable[ScheduleBlockORM],
    observations: Iterable[ObservationORM],
) -> PersistedPlannerState:
    """Rebuild and validate a database-neutral snapshot from rows for one state."""
    if not isinstance(planner_state_orm, PlannerStateORM):
        raise TypeError("planner_state_orm must be a PlannerStateORM")
    state_id = planner_state_orm.id

    row_groups = {
        "tasks": list(tasks),
        "goals": list(goals),
        "goal_root_tasks": list(goal_root_tasks),
        "dependencies": list(dependencies),
        "calendar_events": list(calendar_events),
        "constraints": list(constraints),
        "plans": list(plans),
        "schedule_blocks": list(schedule_blocks),
        "observations": list(observations),
    }
    expected_types = {
        "tasks": TaskORM,
        "goals": GoalORM,
        "goal_root_tasks": GoalRootTaskORM,
        "dependencies": DependencyORM,
        "calendar_events": CalendarEventORM,
        "constraints": ConstraintORM,
        "plans": PlanORM,
        "schedule_blocks": ScheduleBlockORM,
        "observations": ObservationORM,
    }
    for label, rows in row_groups.items():
        for row in rows:
            if not isinstance(row, expected_types[label]):
                raise TypeError(f"{label} contains a row of the wrong ORM type")
            if row.state_id != state_id:
                raise ValueError(f"{label} contains a row from another planner state")

    task_rows = _unique(row_groups["tasks"], lambda row: row.id, "task")
    children_by_parent: dict[str, list[str]] = {task_id: [] for task_id in task_rows}
    for row in task_rows.values():
        if row.parent_task_id is not None:
            children = children_by_parent.get(row.parent_task_id)
            if children is None:
                raise ValueError(f"Task references missing parent {row.parent_task_id!r}.")
            children.append(row.id)
    task_records = {
        key: task.from_orm(row, children_ids=children_by_parent[key])
        for key, row in task_rows.items()
    }

    goal_rows = _unique(row_groups["goals"], lambda row: row.id, "goal")
    roots_by_goal = {key: [] for key in goal_rows}
    for association in row_groups["goal_root_tasks"]:
        if association.goal_id not in roots_by_goal:
            raise ValueError(f"Goal-root association references missing goal {association.goal_id!r}.")
        roots_by_goal[association.goal_id].append(association.task_id)
    goal_records = {
        key: goal.from_orm(row, root_task_ids=roots_by_goal[key])
        for key, row in goal_rows.items()
    }

    dependency_records: dict[str, DependencyRecord] = {}
    for row in row_groups["dependencies"]:
        dependent_id, prerequisite_id = dependency.from_orm(row)
        record = DependencyRecord(dependent_id, prerequisite_id)
        key = _dependency_id(record)
        if key in dependency_records:
            raise ValueError(f"Duplicate dependency edge {key!r}.")
        dependency_records[key] = record

    event_rows = _unique(row_groups["calendar_events"], lambda row: row.id, "calendar event")
    event_records = {key: calendar_event.from_orm(row) for key, row in event_rows.items()}
    constraint_records = {}
    for row in row_groups["constraints"]:
        record = constraint.from_orm(row)
        key = _constraint_id(record)
        if key in constraint_records:
            raise ValueError(f"Duplicate constraint ID {key!r}.")
        constraint_records[key] = record

    plan_rows = _unique(row_groups["plans"], lambda row: row.id, "plan")
    blocks_by_plan: dict[str, list[str]] = {key: [] for key in plan_rows}
    block_rows = _unique(row_groups["schedule_blocks"], lambda row: row.id, "schedule block")
    for row in block_rows.values():
        if row.plan_id is not None:
            if row.plan_id not in blocks_by_plan:
                raise ValueError(f"Schedule block references missing plan {row.plan_id!r}.")
            blocks_by_plan[row.plan_id].append(row.id)
    plan_records = {
        key: plan.from_orm(row, schedule_block_ids=blocks_by_plan[key])
        for key, row in plan_rows.items()
    }
    block_records: dict[str, ScheduleBlockRecord] = {
        key: schedule_block.from_orm(row) for key, row in block_rows.items()
    }

    observation_rows = _unique(row_groups["observations"], lambda row: row.id, "observation")
    observation_records = {
        key: observation.from_orm(row) for key, row in observation_rows.items()
    }
    state_record = PlannerStateRecord(
        goal_ids=list(goal_records),
        task_ids=list(task_records),
        dependency_ids=list(dependency_records),
        calendar_event_ids=list(event_records),
        constraint_ids=list(constraint_records),
        current_plan_id=next(iter(plan_records), None),
        observation_ids=list(observation_records),
    )
    return PersistedPlannerState(
        state_id=state_id,
        version=planner_state_orm.version,
        planner_state_record=state_record,
        tasks=task_records,
        goals=goal_records,
        dependencies=dependency_records,
        calendar_events=event_records,
        constraints=constraint_records,
        plans=plan_records,
        schedule_blocks=block_records,
        observations=observation_records,
    )


def _unique(rows, key_of, label: str) -> dict[str, object]:
    result = {}
    for row in rows:
        key = key_of(row)
        if key in result:
            raise ValueError(f"Duplicate {label} ORM row key {key!r}.")
        result[key] = row
    return result


def _dependency_id(record: DependencyRecord) -> str:
    return json.dumps(
        [record.dependent_task_id, record.prerequisite_task_id],
        separators=(",", ":"),
    )


def _constraint_id(record: ConstraintRecord) -> str:
    if not isinstance(record.constraint_id, UUID):
        raise ValueError("Constraint record ID must be a UUID.")
    return str(record.constraint_id)

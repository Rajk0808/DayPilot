import json
from collections.abc import Mapping
from uuid import UUID

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.planner import PlannerState
from daypilot.persistence.mappers.constraint import from_record as constraint_from_record
from daypilot.persistence.mappers.dependency import from_record as dependency_from_record
from daypilot.persistence.mappers.dependency import to_record as dependency_to_record
from daypilot.persistence.mappers.goal import from_record as goal_from_record
from daypilot.persistence.mappers.observation import from_record as observation_from_record
from daypilot.persistence.mappers.observation import observation_id
from daypilot.persistence.mappers.plan import from_record as plan_from_record
from daypilot.persistence.mappers.schedule_block import (
    ScheduleBlockMappingContext,
    schedule_block_id,
)
from daypilot.persistence.mappers.task import TaskMappingContext
from daypilot.persistence.mappers.times import from_record as event_from_record
from daypilot.persistence.models.constraint import ConstraintRecord
from daypilot.persistence.models.dependency import DependencyRecord
from daypilot.persistence.models.goal import GoalRecord
from daypilot.persistence.models.observation import ObservationRecord
from daypilot.persistence.models.plan import PlanRecord
from daypilot.persistence.models.planner import PlannerStateRecord
from daypilot.persistence.models.schedule import ScheduleBlockRecord
from daypilot.persistence.models.times import CalendarEventRecord
from daypilot.persistence.time_utils import datetime_to_timestamp_microseconds


def dependency_id(record: DependencyRecord) -> str:
    return json.dumps(
        [record.dependent_task_id, record.prerequisite_task_id], separators=(",", ":")
    )


def constraint_id(record: ConstraintRecord) -> str:
    if not isinstance(record.constraint_id, UUID):
        raise ValueError("Constraint record ID must be a UUID.")
    return str(record.constraint_id)


def to_record(
    state: PlannerState,
    *,
    constraint_ids: list[str] | None = None,
) -> PlannerStateRecord:
    if constraint_ids is None:
        if state.constraints:
            raise ValueError(
                "Constraint record IDs must be provided when mapping a state with constraints."
            )
        constraint_ids = []
    elif len(constraint_ids) != len(state.constraints):
        raise ValueError("Constraint IDs must match the planner state's constraints.")

    dependencies = [
        dependency_to_record(state.dependency_graph.tasks[dependent_id],
                             state.dependency_graph.tasks[prerequisite_id])
        for dependent_id, prerequisites in state.dependency_graph.prerequisites.items()
        for prerequisite_id in sorted(prerequisites)
    ]
    observation_keys = []
    for observation in state.observations:
        start = datetime_to_timestamp_microseconds(observation.actual_start)
        end = datetime_to_timestamp_microseconds(observation.actual_end)
        block_start = datetime_to_timestamp_microseconds(observation.scheduled_block.start)
        block_end = datetime_to_timestamp_microseconds(observation.scheduled_block.end)
        block_key = schedule_block_id(observation.task.id, block_start, block_end)
        observation_keys.append(observation_id(observation.task.id, block_key, start, end))

    return PlannerStateRecord(
        goal_ids=[goal.id for goal in state.goals],
        task_ids=[task.id for task in state.tasks],
        dependency_ids=[dependency_id(item) for item in dependencies],
        calendar_event_ids=[event.id for event in state.calendar_events],
        constraint_ids=list(constraint_ids),
        current_plan_id=state.current_plan.id if state.current_plan is not None else None,
        observation_ids=observation_keys,
    )


def from_record(
    record: PlannerStateRecord,
    task_mapping_context: TaskMappingContext,
    *,
    goal_records: Mapping[str, GoalRecord],
    dependency_records: Mapping[str, DependencyRecord],
    calendar_event_records: Mapping[str, CalendarEventRecord],
    constraint_records: Mapping[str, ConstraintRecord],
    plan_records: Mapping[str, PlanRecord],
    schedule_block_records: Mapping[str, ScheduleBlockRecord],
    observation_records: Mapping[str, ObservationRecord],
    schedule_block_context: ScheduleBlockMappingContext | None = None,
) -> PlannerState:
    if len(record.task_ids) != len(set(record.task_ids)):
        raise ValueError("Planner state contains duplicate task IDs.")
    if set(record.task_ids) != set(task_mapping_context.tasks):
        raise ValueError("Planner state task IDs do not match its task mapping context.")

    graph = DependencyGraph()
    for task_id in record.task_ids:
        graph.register_task(task_mapping_context.tasks[task_id])
    for dependency_key in record.dependency_ids:
        dependency = _required(dependency_records, dependency_key, "dependency")
        if dependency_id(dependency) != dependency_key:
            raise ValueError("Dependency record key does not match its contents.")
        dependency_from_record(dependency, task_mapping_context, graph)

    goals = [
        goal_from_record(_required(goal_records, goal_id, "goal"), task_mapping_context)
        for goal_id in record.goal_ids
    ]
    events = [
        event_from_record(_required(calendar_event_records, event_id, "calendar event"))
        for event_id in record.calendar_event_ids
    ]
    constraints = [
        constraint_from_record(_required(constraint_records, key, "constraint"))
        for key in record.constraint_ids
    ]
    observations = [
        observation_from_record(
            _required(observation_records, key, "observation"),
            task_mapping_context,
            schedule_block_records,
            schedule_block_context,
        )
        for key in record.observation_ids
    ]
    plan = None
    if record.current_plan_id is not None:
        plan = plan_from_record(
            _required(plan_records, record.current_plan_id, "plan"),
            task_mapping_context,
            schedule_block_records,
            schedule_block_context,
        )

    return PlannerState(
        goals=goals,
        tasks=[task_mapping_context.tasks[task_id] for task_id in record.task_ids],
        dependency_graph=graph,
        calendar_events=events,
        constraints=constraints,
        current_plan=plan,
        observations=observations,
    )


def _required(mapping: Mapping[str, object], key: str, label: str):
    try:
        return mapping[key]
    except KeyError as exc:
        raise ValueError(f"Planner state references missing {label} record {key!r}.") from exc

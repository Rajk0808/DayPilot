"""Database-neutral snapshot of one complete PlannerState aggregate."""

from dataclasses import dataclass

from daypilot.domain.planner import PlannerState
from daypilot.persistence.mappers.constraint import to_record as constraint_to_record
from daypilot.persistence.mappers.dependency import to_record as dependency_to_record
from daypilot.persistence.mappers.goal import to_record as goal_to_record
from daypilot.persistence.mappers.observation import to_record as observation_to_record
from daypilot.persistence.mappers.plan import to_record as plan_to_record
from daypilot.persistence.mappers.planner_state import (
    constraint_id,
    dependency_id,
    from_record as planner_state_from_record,
    observation_id,
    to_record as planner_state_to_record,
)
from daypilot.persistence.mappers.schedule_block import (
    ScheduleBlockMappingContext,
    schedule_block_id,
    to_record as schedule_block_to_record,
)
from daypilot.persistence.mappers.task import TaskMappingContext, to_record as task_to_record
from daypilot.persistence.mappers.times import to_record as calendar_event_to_record
from daypilot.persistence.models.constraint import ConstraintRecord
from daypilot.persistence.models.dependency import DependencyRecord
from daypilot.persistence.models.goal import GoalRecord
from daypilot.persistence.models.observation import ObservationRecord
from daypilot.persistence.models.plan import PlanRecord
from daypilot.persistence.models.planner import PlannerStateRecord
from daypilot.persistence.models.schedule import ScheduleBlockRecord
from daypilot.persistence.models.task import TaskRecord
from daypilot.persistence.models.times import CalendarEventRecord


@dataclass
class PersistedPlannerState:
    """All records needed to store or reconstruct one PlannerState atomically.

    Child records are keyed by their stable persistence keys. The current domain
    supports one current plan, so ``plans`` is empty or contains exactly that plan.
    ``version`` reserves a place for future concurrency control; no locking is
    performed by this value alone.
    """

    state_id: str
    version: int
    planner_state_record: PlannerStateRecord
    tasks: dict[str, TaskRecord]
    goals: dict[str, GoalRecord]
    dependencies: dict[str, DependencyRecord]
    calendar_events: dict[str, CalendarEventRecord]
    constraints: dict[str, ConstraintRecord]
    plans: dict[str, PlanRecord]
    schedule_blocks: dict[str, ScheduleBlockRecord]
    observations: dict[str, ObservationRecord]

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if not isinstance(self.state_id, str) or not self.state_id:
            raise ValueError("Persisted planner state ID must be a non-empty string.")
        if not isinstance(self.version, int) or self.version < 1:
            raise ValueError("Persisted planner state version must be a positive integer.")

        self._validate_keys(self.tasks, lambda item: item.id, "task")
        self._validate_keys(self.goals, lambda item: item.id, "goal")
        self._validate_keys(self.calendar_events, lambda item: item.id, "calendar event")
        self._validate_keys(self.plans, lambda item: item.id, "plan")
        self._validate_keys(self.schedule_blocks, lambda item: item.id, "schedule block")
        self._validate_keys(self.observations, lambda item: item.id, "observation")
        self._validate_keys(self.dependencies, dependency_id, "dependency")
        self._validate_keys(self.constraints, constraint_id, "constraint")

        record = self.planner_state_record
        self._validate_unique(record.goal_ids, "goal")
        self._validate_unique(record.task_ids, "task")
        self._validate_unique(record.dependency_ids, "dependency")
        self._validate_unique(record.calendar_event_ids, "calendar event")
        self._validate_unique(record.constraint_ids, "constraint")
        self._validate_unique(record.observation_ids, "observation")

        expected_sets = (
            (record.task_ids, self.tasks, "task"),
            (record.goal_ids, self.goals, "goal"),
            (record.dependency_ids, self.dependencies, "dependency"),
            (record.calendar_event_ids, self.calendar_events, "calendar event"),
            (record.constraint_ids, self.constraints, "constraint"),
            (record.observation_ids, self.observations, "observation"),
        )
        for ids, records, label in expected_sets:
            if set(ids) != set(records):
                raise ValueError(f"Planner state {label} IDs do not match the persisted records.")

        if record.current_plan_id is None:
            if self.plans:
                raise ValueError("Persisted plans exist when the planner state has no current plan.")
        elif set(self.plans) != {record.current_plan_id}:
            raise ValueError("Persisted plan records must contain exactly the current plan.")

        referenced_block_ids: set[str] = set()
        for plan in self.plans.values():
            referenced_block_ids.update(plan.schedule_block_ids)
        for observation in self.observations.values():
            referenced_block_ids.add(observation.schedule_block_id)
        if referenced_block_ids != set(self.schedule_blocks):
            raise ValueError("Schedule block records do not match plan and observation references.")

        task_ids = set(self.tasks)
        for goal in self.goals.values():
            if not set(goal.root_task_ids) <= task_ids:
                raise ValueError(f"Goal {goal.id!r} references a task outside the aggregate.")
        for task in self.tasks.values():
            references = set(task.children_ids)
            if task.parent_id is not None:
                references.add(task.parent_id)
            if not references <= task_ids:
                raise ValueError(f"Task {task.id!r} references a task outside the aggregate.")
        for dependency in self.dependencies.values():
            if dependency.dependent_task_id not in task_ids or dependency.prerequisite_task_id not in task_ids:
                raise ValueError("Dependency references a task outside the aggregate.")
        for block in self.schedule_blocks.values():
            if block.task_id not in task_ids:
                raise ValueError("Schedule block references a task outside the aggregate.")
        for observation in self.observations.values():
            if observation.task_id not in task_ids:
                raise ValueError("Observation references a task outside the aggregate.")

    @staticmethod
    def _validate_keys(mapping, key_of, label: str) -> None:
        for key, value in mapping.items():
            if key != key_of(value):
                raise ValueError(f"Persisted {label} mapping key {key!r} does not match its record.")

    @staticmethod
    def _validate_unique(ids: list[str], label: str) -> None:
        if len(ids) != len(set(ids)):
            raise ValueError(f"Planner state contains duplicate {label} IDs.")


def to_persisted_planner_state(
    state: PlannerState,
    state_id: str,
    *,
    version: int = 1,
) -> PersistedPlannerState:
    """Validate and map the complete aggregate to a keyed persistence snapshot."""
    if not isinstance(state, PlannerState):
        raise TypeError("State must be a PlannerState.")
    # Re-run domain aggregate validation in case a mutable state was changed
    # after its original construction.
    PlannerState(
        goals=state.goals,
        tasks=state.tasks,
        dependency_graph=state.dependency_graph,
        calendar_events=state.calendar_events,
        constraints=state.constraints,
        current_plan=state.current_plan,
        observations=state.observations,
    )

    tasks = {task.id: task_to_record(task) for task in state.tasks}
    goals = {goal.id: goal_to_record(goal) for goal in state.goals}
    dependencies: dict[str, DependencyRecord] = {}
    for dependent_id, prerequisites in state.dependency_graph.prerequisites.items():
        for prerequisite_id in prerequisites:
            item = dependency_to_record(
                state.dependency_graph.tasks[dependent_id],
                state.dependency_graph.tasks[prerequisite_id],
            )
            dependencies[dependency_id(item)] = item
    events = {event.id: calendar_event_to_record(event) for event in state.calendar_events}
    constraints: dict[str, ConstraintRecord] = {}
    for constraint in state.constraints:
        item = constraint_to_record(constraint)
        constraints[constraint_id(item)] = item
    state_record = planner_state_to_record(state, constraint_ids=list(constraints))

    plans: dict[str, PlanRecord] = {}
    schedule_blocks: dict[str, ScheduleBlockRecord] = {}
    if state.current_plan is not None:
        plan_record = plan_to_record(state.current_plan)
        plans[plan_record.id] = plan_record
        for block in state.current_plan.schedule_blocks:
            item = schedule_block_to_record(block)
            schedule_blocks[item.id] = item
    observations: dict[str, ObservationRecord] = {}
    for observation in state.observations:
        item = observation_to_record(observation)
        observations[item.id] = item
        block = schedule_block_to_record(observation.scheduled_block)
        existing = schedule_blocks.get(block.id)
        if existing is not None and existing != block:
            raise ValueError(f"Conflicting schedule block records use ID {block.id!r}.")
        schedule_blocks[block.id] = block

    return PersistedPlannerState(
        state_id=state_id,
        version=version,
        planner_state_record=state_record,
        tasks=tasks,
        goals=goals,
        dependencies=dependencies,
        calendar_events=events,
        constraints=constraints,
        plans=plans,
        schedule_blocks=schedule_blocks,
        observations=observations,
    )


def from_persisted_planner_state(snapshot: PersistedPlannerState) -> PlannerState:
    """Reconstruct and domain-validate one complete stored planner aggregate."""
    if not isinstance(snapshot, PersistedPlannerState):
        raise TypeError("Snapshot must be a PersistedPlannerState.")
    snapshot.validate()
    task_context = TaskMappingContext()
    task_context.reconstruct(list(snapshot.tasks.values()))
    schedule_block_context = ScheduleBlockMappingContext()
    return planner_state_from_record(
        snapshot.planner_state_record,
        task_context,
        goal_records=snapshot.goals,
        dependency_records=snapshot.dependencies,
        calendar_event_records=snapshot.calendar_events,
        constraint_records=snapshot.constraints,
        plan_records=snapshot.plans,
        schedule_block_records=snapshot.schedule_blocks,
        observation_records=snapshot.observations,
        schedule_block_context=schedule_block_context,
    )

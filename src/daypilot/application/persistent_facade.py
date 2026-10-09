"""Application entry points that wrap use cases in persistence transactions."""

from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from daypilot.application.application_service import DayPilotApplicationService
from daypilot.application.constraint_service import ConstraintUpdateRequest
from daypilot.application.goal_service import GoalCreateRequest, GoalUpdateRequest
from daypilot.application.observation_service import ObservationRequest
from daypilot.application.task_service import TaskCreateRequest, TaskUpdateRequest
from daypilot.application.times_service import CalendarEventUpdateRequest
from daypilot.domain.goal import Goal
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import PlanningChange, ReplanningResult
from daypilot.domain.task import Task
from daypilot.domain.times import CalendarEvent, Constraint
from daypilot.persistence.exceptions import EntityNotFoundError
from daypilot.persistence.unit_of_works.planner_state import PlannerStateUnitOfWork


_ResultT = TypeVar("_ResultT")


class PersistentDayPilotApplicationService:
    """Load, execute, and persist application use cases as one operation.

    The existing application services remain unaware of persistence. Every
    public mutation loads a fresh aggregate in a new unit of work and only
    saves it after the application operation succeeds.
    """

    def __init__(
        self,
        application: DayPilotApplicationService,
        unit_of_work_factory: Callable[[], PlannerStateUnitOfWork],
    ) -> None:
        if application is None:
            raise ValueError("Application service cannot be None.")
        if unit_of_work_factory is None or not callable(unit_of_work_factory):
            raise ValueError("Unit of work factory must be callable.")
        self._application = application
        self._unit_of_work_factory = unit_of_work_factory

    def _mutate(
        self, state_id: str, operation: Callable[[PlannerState], _ResultT]
    ) -> _ResultT:
        with self._unit_of_work_factory() as uow:
            state = uow.planner_states.get(state_id)
            result = operation(state)
            uow.planner_states.save(state, state_id=state_id)
        return result

    @staticmethod
    def _task(state: PlannerState, task: Task | str) -> Task:
        task_id = task.id if isinstance(task, Task) else task
        for candidate in state.tasks:
            if candidate.id == task_id:
                return candidate
        raise EntityNotFoundError(f"Task {task_id!r} does not exist in the planner state.")

    @staticmethod
    def _goal(state: PlannerState, goal: Goal | str) -> Goal:
        goal_id = goal.id if isinstance(goal, Goal) else goal
        for candidate in state.goals:
            if candidate.id == goal_id:
                return candidate
        raise EntityNotFoundError(f"Goal {goal_id!r} does not exist in the planner state.")

    def get_task(self, state_id: str, task_id: str) -> Task:
        """Load a task from the persisted aggregate by its logical ID."""
        with self._unit_of_work_factory() as uow:
            state = uow.planner_states.get(state_id)
            task = self._task(state, task_id)
            uow.rollback()
        return task

    def get_goal(self, state_id: str, goal_id: str) -> Goal:
        """Load a goal from the persisted aggregate by its logical ID."""
        with self._unit_of_work_factory() as uow:
            state = uow.planner_states.get(state_id)
            goal = self._goal(state, goal_id)
            uow.rollback()
        return goal

    @staticmethod
    def _calendar_event(state: PlannerState, event: CalendarEvent | str) -> CalendarEvent:
        event_id = event.id if isinstance(event, CalendarEvent) else event
        for candidate in state.calendar_events:
            if candidate.id == event_id:
                return candidate
        raise ValueError(f"Calendar event {event_id!r} does not exist in the planner state.")

    @staticmethod
    def _constraint(state: PlannerState, constraint: Constraint) -> Constraint:
        matches = [candidate for candidate in state.constraints if candidate == constraint]
        if not matches:
            raise ValueError("Constraint does not exist in the planner state.")
        if len(matches) > 1:
            raise ValueError("Constraint is ambiguous in the planner state.")
        return matches[0]

    def create_task(
        self,
        state_id: str,
        request: TaskCreateRequest,
        planning_start: datetime,
        planning_end: datetime,
    ) -> ReplanningResult:
        """Create and replan a task, saving only after the use case succeeds."""
        return self._mutate(
            state_id,
            lambda state: self._application.create_task(
                state=state,
                request=request,
                planning_start=planning_start,
                planning_end=planning_end,
            ),
        )

    def change_task(
        self, state_id: str, task: Task | str, updates: TaskUpdateRequest,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.change_task(
            state, self._task(state, task), updates, planning_start, planning_end
        ))

    def remove_task(
        self, state_id: str, task: Task | str,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.remove_task(
            state, self._task(state, task), planning_start, planning_end
        ))

    def create_goal(self, state_id: str, goal: Goal | GoalCreateRequest) -> Goal:
        def create(state: PlannerState) -> Goal:
            if isinstance(goal, GoalCreateRequest):
                canonical_goal = Goal(
                    id=goal.id,
                    title=goal.title,
                    description=goal.description,
                    deadline=goal.deadline,
                    status=goal.status,
                    root_tasks=[self._task(state, task_id) for task_id in goal.root_task_ids],
                )
                return self._application.create_goal(canonical_goal, state)
            canonical_goal = Goal(
                id=goal.id,
                title=goal.title,
                description=goal.description,
                deadline=goal.deadline,
                status=goal.status,
                root_tasks=[self._task(state, task) for task in goal.root_tasks],
            )
            return self._application.create_goal(canonical_goal, state)

        return self._mutate(state_id, create)

    def change_goal(
        self, state_id: str, goal: Goal | str, change_request: GoalUpdateRequest,
    ) -> Goal:
        return self._mutate(state_id, lambda state: self._application.change_goal(
            self._goal(state, goal), state, change_request
        ))

    def remove_goal(self, state_id: str, goal: Goal | str) -> None:
        self._mutate(state_id, lambda state: self._application.remove_goal(
            self._goal(state, goal), state
        ))

    def add_dependency(
        self, state_id: str, dependent: Task | str, prereq: Task | str,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.add_dependency(
            state, self._task(state, dependent), self._task(state, prereq),
            planning_start, planning_end,
        ))

    def remove_dependency(
        self, state_id: str, dependent: Task | str, prereq: Task | str,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.remove_dependency(
            state, self._task(state, dependent), self._task(state, prereq),
            planning_start, planning_end,
        ))

    def add_calendar_event(
        self, state_id: str, event: CalendarEvent,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.add_calendar_event(
            event, state, planning_start, planning_end
        ))

    def update_calendar_event(
        self, state_id: str, event: CalendarEvent | str,
        change_request: CalendarEventUpdateRequest,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.update_calendar_event(
            self._calendar_event(state, event), state, change_request,
            planning_start, planning_end,
        ))

    def remove_calendar_event(
        self, state_id: str, event: CalendarEvent | str,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.remove_calendar_event(
            self._calendar_event(state, event), state, planning_start, planning_end
        ))

    def add_constraint(
        self, state_id: str, constraint: Constraint,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.add_constraint(
            state, constraint, planning_start, planning_end
        ))

    def update_constraint(
        self, state_id: str, constraint: Constraint,
        changes: ConstraintUpdateRequest,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.update_constraint(
            state, self._constraint(state, constraint), changes,
            planning_start, planning_end,
        ))

    def remove_constraint(
        self, state_id: str, constraint: Constraint,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        return self._mutate(state_id, lambda state: self._application.remove_constraint(
            state, self._constraint(state, constraint), planning_start, planning_end
        ))

    def record_observation(
        self, state_id: str, request: ObservationRequest,
        planning_start: datetime, planning_end: datetime,
    ) -> ReplanningResult:
        def record(state: PlannerState) -> ReplanningResult:
            task = self._task(state, request.task)
            block_key = (request.scheduled_block.start, request.scheduled_block.end)
            candidate_blocks = (
                list(state.current_plan.schedule_blocks) if state.current_plan is not None else []
            ) + [observation.scheduled_block for observation in state.observations]
            block = next((candidate for candidate in candidate_blocks
                          if candidate.task.id == task.id
                          and (candidate.start, candidate.end) == block_key), None)
            if block is None:
                raise ValueError("Observation schedule block does not exist in the planner state.")
            canonical_request = ObservationRequest(
                task=task,
                scheduled_block=block,
                actual_start=request.actual_start,
                actual_end=request.actual_end,
                outcome=request.outcome,
                metadata=dict(request.metadata),
            )
            return self._application.record_observation(
                canonical_request, state, planning_start, planning_end
            )

        return self._mutate(state_id, record)

    def add_child(self, state_id: str, parent: Task | str, child: Task | str) -> None:
        self._mutate(state_id, lambda state: self._application.add_child(
            state, self._task(state, parent), self._task(state, child)
        ))

    def remove_child(self, state_id: str, parent: Task | str, child: Task | str) -> None:
        self._mutate(state_id, lambda state: self._application.remove_child(
            state, self._task(state, parent), self._task(state, child)
        ))

    def preview_replan(
        self,
        state_id: str,
        change_factory: Callable[[PlannerState], PlanningChange],
        planning_start: datetime,
        planning_end: datetime,
    ) -> ReplanningResult:
        """Calculate a replan against loaded state without persisting a change.

        The factory receives the reconstructed state so its PlanningChange can
        refer to that state's canonical task objects.
        """
        if change_factory is None or not callable(change_factory):
            raise ValueError("Planning change factory must be callable.")
        with self._unit_of_work_factory() as uow:
            state = uow.planner_states.get(state_id)
            change = change_factory(state)
            result = self._application.replan(
                state=state,
                change=change,
                planning_start=planning_start,
                planning_end=planning_end,
            )
            uow.rollback()
        return result

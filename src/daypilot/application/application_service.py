from datetime import datetime

from daypilot.application.times_service import (
    CalendarApplicationService,
    CalendarEventUpdateRequest,
)
from daypilot.application.constraint_service import ConstraintApplicationService, ConstraintUpdateRequest 
from daypilot.application.dependency_service import DependencyApplicationService
from daypilot.application.goal_service import GoalApplicationService, GoalUpdateRequest
from daypilot.application.hierarchy_service import TaskHierarchyApplicationService
from daypilot.application.observation_service import (
    ObservationApplicationService,
    ObservationRequest,
)
from daypilot.application.planning_service import PlanningApplicationService
from daypilot.application.task_service import TaskApplicationService, TaskCreateRequest, TaskUpdateRequest
from daypilot.domain.goal import Goal
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import PlanningChange, ReplanningResult
from daypilot.domain.task import Task
from daypilot.domain.times import CalendarEvent, Constraint


class DayPilotApplicationService:
    def __init__(
        self,
        task_service: TaskApplicationService,
        goal_service: GoalApplicationService,
        dependency_service: DependencyApplicationService,
        calendar_service: CalendarApplicationService,
        constraint_service: ConstraintApplicationService,
        observation_service: ObservationApplicationService,
        hierarchy_service: TaskHierarchyApplicationService,
        planning_service: PlanningApplicationService,
    ):
        self._task_service = task_service
        self._goal_service = goal_service
        self._dependency_service = dependency_service
        self._calendar_service = calendar_service
        self._constraint_service = constraint_service
        self._observation_service = observation_service
        self._hierarchy_service = hierarchy_service
        self._planning_service = planning_service

    def create_task(
            self,
            state: PlannerState,
            request: TaskCreateRequest,
            planning_start: datetime,
            planning_end: datetime 
            ) -> ReplanningResult:
                return self._task_service.create_task(
                    state=state,
                    request=request,
                    planning_start=planning_start,
                    planning_end=planning_end
                )

    def remove_task(
            self,
            state: PlannerState,
            task: Task,
            planning_start: datetime,
            planning_end: datetime 
            ) -> ReplanningResult:
                return self._task_service.remove_task(
                    state=state,
                    task=task,
                    planning_start=planning_start,
                    planning_end=planning_end
                )

    def change_task(
            self,
            state: PlannerState,
            task: Task,
            updates: TaskUpdateRequest,
            planning_start: datetime,
            planning_end: datetime 
            ) -> ReplanningResult:
                return self._task_service.change_task(
                    state=state,
                    task=task,  
                    updates=updates,  
                    planning_start=planning_start,
                    planning_end=planning_end
                )
    
    def create_goal(
            self, 
            goal : Goal,
            state: PlannerState
        ) -> Goal:
        return self._goal_service.create_goal(
            goal=goal,
            state=state
        )
    
    def change_goal(
                self,
                goal: Goal,
                state: PlannerState,
                change_request: GoalUpdateRequest
            ) -> Goal:
        return self._goal_service.change_goal(
            goal=goal,
            state=state,
            change_request=change_request
        )   

    def remove_goal(
                self,
                goal: Goal,
                state: PlannerState
            ) -> None:
        self._goal_service.remove_goal(
            goal=goal,
            state=state
        )

    def add_dependency(
            self, 
            state: PlannerState,
            dependent: Task,
            prereq: Task,
            planning_start: datetime,
            planning_end: datetime
        ) -> ReplanningResult:
        return self._dependency_service.add_dependency(
            state=state,
            dependent=dependent,
            prereq=prereq,
            planning_start=planning_start,
            planning_end=planning_end
        )

    def remove_dependency(
            self,
            state: PlannerState,
            dependent: Task,
            prereq: Task,
            planning_start: datetime,
            planning_end: datetime
        ) -> ReplanningResult:
         

        return self._dependency_service.remove_dependency(
            state=state,
            dependent=dependent,
            prereq=prereq,
            planning_start=planning_start,
            planning_end=planning_end
        )

    def add_constraint(
            self, 
            state: PlannerState, 
            constraint: Constraint, 
            planning_start: datetime, 
            planning_end: datetime
        ) -> ReplanningResult:
        return self._constraint_service.add_constraint(
            state=state,
            constraint=constraint,
            planning_start=planning_start,
            planning_end=planning_end
        )

    def update_constraint(
            self,
            state: PlannerState,
            constraint: Constraint,
            changes: ConstraintUpdateRequest,
            planning_start: datetime,
            planning_end: datetime
    ) -> ReplanningResult:
        return self._constraint_service.update_constraint(
            state=state,
            constraint=constraint,
            changes=changes,
            planning_start=planning_start,
            planning_end=planning_end
        )
    
    def remove_constraint(
            self,
            state: PlannerState,
            constraint: Constraint,
            planning_start: datetime,
            planning_end: datetime
    ) -> ReplanningResult:
        return self._constraint_service.remove_constraint(
            state=state,
            constraint=constraint,
            planning_start=planning_start,
            planning_end=planning_end
        )

    def add_calendar_event(
            self,
            event: CalendarEvent,
            state: PlannerState,
            planning_start: datetime,
            planning_end: datetime
    ) -> ReplanningResult:
        return self._calendar_service.add_event(
            event=event,
            state=state,
            planning_start=planning_start,
            planning_end=planning_end
        )

    def remove_calendar_event(
            self,
            event: CalendarEvent,
            state: PlannerState,
            planning_start: datetime,
            planning_end: datetime
    ) -> ReplanningResult:
        return self._calendar_service.remove_event(
            event=event,
            state=state,
            planning_start=planning_start,
            planning_end=planning_end
        )

    def update_calendar_event(
            self,
            event: CalendarEvent,
            state: PlannerState,
            change_request: CalendarEventUpdateRequest,
            planning_start: datetime,
            planning_end: datetime
    ) -> ReplanningResult:
        return self._calendar_service.update_event(
            event=event,
            state=state,
            change_request=change_request,
            planning_start=planning_start,
            planning_end=planning_end
        )

    def record_observation(
            self,
            request: ObservationRequest,
            state: PlannerState,
            planning_start: datetime,
            planning_end: datetime,
    ) -> ReplanningResult:
        return self._observation_service.record_observation(
            request=request,
            state=state,
            planning_start=planning_start,
            planning_end=planning_end
        )

    def add_child(
            self, 
            state: PlannerState, 
            parent: Task, 
            child: Task
        ) -> None:
        return self._hierarchy_service.add_child(
            state=state,
            parent=parent,
            child=child
        )

    def remove_child(
            self, 
            state: PlannerState, 
            parent: Task, 
            child: Task
        ) -> None:
        return self._hierarchy_service.remove_child(
            state=state,
            parent=parent,
            child=child
        )

    def replan( 
            self,
            state: PlannerState,
            change: PlanningChange,
            planning_start: datetime,
            planning_end: datetime
        ) -> ReplanningResult:
        return self._planning_service.replan(
            change=change,
            state=state,
            planning_start=planning_start,
            planning_end=planning_end
        )

    def apply_replanning_result(
            self,
            state: PlannerState,
            result: ReplanningResult
        ):
        return self._planning_service.apply_replanning_result(
            state=state,
            result=result
        )
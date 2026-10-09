from dataclasses import dataclass
from datetime import datetime

from daypilot.domain.goal import Goal
from daypilot.domain.planner import PlannerState

@dataclass(frozen=True)
class GoalCreateRequest:
    id: str
    title: str
    description: str = ""
    deadline: datetime | None = None
    status: object | None = None
    root_task_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoalUpdateRequest:
    title: str | None = None
    description: str | None = None
    deadline: datetime | None = None
    status: object | None = None
    

class GoalApplicationService:
    _UPDATE_FIELDS = ( 
        "title",
        "description",
        "deadline",
        "status",
    )

    def create_goal(
            self,
            goal: Goal,
            state: PlannerState
    ) -> Goal:
        if goal is None:
            raise ValueError("Goal cannot be None")
        if state is None:
            raise ValueError("Planner state cannot be None")
        if any(existing is goal for existing in state.goals):
            raise ValueError("Goal already exists in the planner state")
        state.add_goal(goal)
        return goal

    def remove_goal(
            self,
            goal: Goal,
            state: PlannerState
    ) -> None:
        if goal is None:
            raise ValueError("Goal cannot be None")
        if state is None:
            raise ValueError("Planner state cannot be None")
        if not any(existing is goal for existing in state.goals):
            raise ValueError("Goal does not exist in the planner state")
        state.remove_goal(goal)

    def change_goal(
        self,
        goal: Goal,
        state: PlannerState,
        change_request: GoalUpdateRequest,
    ) -> Goal:
        if goal is None:
            raise ValueError("Goal cannot be None")
        if change_request is None:
            raise ValueError("Change request cannot be None")
        if state is None:
            raise ValueError("Planner state cannot be None")
    
        if not any(existing is goal for existing in state.goals):
            raise ValueError("Goal does not exist in the planner state")
    
        changed_fields = {
            field
            for field in self._UPDATE_FIELDS
            if getattr(change_request, field) is not None
        }
    
        if not changed_fields:
            raise ValueError("Goal update cannot be empty")
    
        requested_values = {
            field: getattr(change_request, field)
            for field in changed_fields
        }
        state.update_goal(goal, **requested_values)
    
        return goal

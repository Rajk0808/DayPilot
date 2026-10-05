
from dataclasses import dataclass

from daypilot.domain.planner import PlannerState
from daypilot.domain.task import Task

@dataclass(frozen=True)
class TaskHierarchyApplicationService:
    def add_child(
            self,
            state: PlannerState,
            parent: Task,
            child: Task,
    ) -> None:
        if parent is None:
            raise ValueError("Parent task cannot be None")
        if child is None:
            raise ValueError("Child task cannot be None")
        if parent is child:
            raise ValueError("A task cannot be a child of itself")
        if state is None:
            raise ValueError("Planner state cannot be None")
        if not any(existing is parent for existing in state.tasks):
            raise ValueError("Parent task is not registered in the planner state")
        
        if not any(existing is child for existing in state.tasks):
            raise ValueError("Child task is not registered in the planner state")
        state.add_child_task(parent, child
                             )

    def remove_child(
            self,
            state: PlannerState,
            parent: Task,
            child: Task,
    ) -> None:
        if parent is None:
            raise ValueError("Parent task cannot be None")
        if child is None:
            raise ValueError("Child task cannot be None")
        if parent is child:
            raise ValueError("A task cannot be a child of itself")
        if state is None:
            raise ValueError("Planner state cannot be None")
        if not any(existing is parent for existing in state.tasks):
            raise ValueError("Parent task is not registered in the planner state")
        if not any(existing is child for existing in state.tasks):
            raise ValueError("Child task is not registered in the planner state")
        state.remove_child_task(parent, child)
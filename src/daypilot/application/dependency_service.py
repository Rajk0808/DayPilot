from datetime import datetime

from daypilot.domain.replan import ReplanningResult, replan, apply_replanning_result
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import PlanningChange
from ..domain.enums import PlanningChangeType
from ..domain.task import Task

class DependencyApplicationService:
    @staticmethod
    def _validate_dependency_request(
            state: PlannerState,
            dependent: Task,
            prereq: Task,
            planning_start: datetime,
            planning_end: datetime,
        ) -> None:
        if state is None:
            raise ValueError("Planner state cannot be None")
        if not isinstance(state, PlannerState):
            raise ValueError("Planner state must be an instance of PlannerState")
        if dependent is None or not any(
            existing is dependent for existing in state.tasks
        ):
            raise ValueError("Dependent task is not registered in the planner state")
        if prereq is None or not any(
            existing is prereq for existing in state.tasks
        ):
            raise ValueError("Prerequisite task is not registered in the planner state")
        if planning_start is None or planning_end is None:
            raise ValueError("Planning start and end cannot be None")
        if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
            raise ValueError("Planning start and end must be timezone-aware")
        if planning_start >= planning_end:
            raise ValueError("Planning end must be after planning start")

    def add_dependency(self, state: PlannerState, dependent: Task, prereq: Task, planning_start: datetime, planning_end: datetime) -> ReplanningResult:
        self._validate_dependency_request(state, dependent, prereq, planning_start, planning_end)
        
        state.add_dependency(dependent, prereq)

        try:
            planning_change = PlanningChange(
                change_type=PlanningChangeType.DEPENDENCY_ADDED,
                metadata={"prerequisite": prereq, "dependent": dependent}
            )
    
            replan_results =  replan(
                planner_state=state,
                change=planning_change,
                planning_start=planning_start,
                planning_end=planning_end
            )

            apply_replanning_result(planner_state=state, result=replan_results)
        except Exception:
            state.remove_dependency(dependent, prereq)
            raise

        return replan_results

    def remove_dependency(self, state: PlannerState, dependent: Task, prereq: Task, planning_start: datetime, planning_end: datetime) -> ReplanningResult:
        self._validate_dependency_request(state, dependent, prereq, planning_start, planning_end)
        if not state.dependency_graph.has_dependency(dependent, prereq):
            raise ValueError("Dependency does not exist in the planner state")
    
        state.remove_dependency(dependent, prereq)

        try:
            planning_change = PlanningChange(
                change_type=PlanningChangeType.DEPENDENCY_REMOVED,
                metadata={"prerequisite": prereq, "dependent": dependent}
            )
    
            replan_results =  replan(
                planner_state=state,
                change=planning_change,
                planning_start=planning_start,
                planning_end=planning_end
            )

            apply_replanning_result(planner_state=state, result=replan_results)
        except Exception:
            state.add_dependency(dependent, prereq)
            raise
        return replan_results
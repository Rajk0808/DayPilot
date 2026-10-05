from dataclasses import dataclass
from datetime import datetime

from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import (
    PlanningChange,
    ReplanningResult,
    apply_replanning_result as commit_replanning_result,
    replan as calculate_replan,
)


@dataclass(frozen=True)
class PlanningApplicationService:
    @staticmethod
    def _validate_planning_request(
            state: PlannerState,
            planning_start: datetime,
            planning_end: datetime,
        ) -> None:
        if state is None:
            raise ValueError("Planner state cannot be None")
        if not isinstance(state, PlannerState):
            raise ValueError("Planner state must be an instance of PlannerState")
        if planning_start is None or planning_end is None:
            raise ValueError("Planning start and end cannot be None")
        if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
            raise ValueError("Planning start and end must be timezone-aware")
        if planning_start >= planning_end:
            raise ValueError("Planning end must be after planning start")

    def replan(
            self,
            state: PlannerState,
            change: PlanningChange,
            planning_start: datetime,
            planning_end: datetime,
        ) -> ReplanningResult:
        self._validate_planning_request(state, planning_start, planning_end)
        if change is None:
            raise ValueError("Planning change cannot be None")
        return calculate_replan(state, change, planning_start, planning_end)

    def apply_replanning_result(
            self,
            state: PlannerState,
            result: ReplanningResult,
        ) -> ReplanningResult:
        if state is None:
            raise ValueError("Planner state cannot be None")
        if not isinstance(state, PlannerState):
            raise ValueError("Planner state must be an instance of PlannerState")
        if result is None:
            raise ValueError("Replanning result cannot be None")
        commit_replanning_result(state, result)
        return result

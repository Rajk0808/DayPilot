from dataclasses import dataclass, field
from typing import Any
from datetime import datetime

from daypilot.domain.enums import ObservationOutcome, PlanningChangeType
from daypilot.domain.observation import Observation
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import (
    PlanningChange,
    ReplanningResult,
    apply_replanning_result,
    replan,
)
from daypilot.domain.schedule import ScheduleBlock
from daypilot.domain.task import Task


@dataclass(frozen=True)
class ObservationRequest:
    task: Task
    scheduled_block: ScheduleBlock
    actual_start: datetime
    actual_end: datetime
    outcome: ObservationOutcome
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class ObservationApplicationService:
    def record_observation(
            self,
            request: ObservationRequest,
            state: PlannerState,
            planning_start: datetime,
            planning_end: datetime
            ) -> ReplanningResult:
        if request is None:
            raise ValueError("Observation request cannot be None")
        if state is None:
            raise ValueError("Planner state cannot be None")
        if planning_start is None or planning_end is None:
            raise ValueError("Planning start and end cannot be None")
        if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
            raise ValueError("Planning start and end must be timezone-aware")
        if planning_start >= planning_end:
            raise ValueError("Planning end must be after planning start")
        if not any(existing is request.task for existing in state.tasks):
            raise ValueError("Task does not exist in the planner state")

        task_states = [
            (task, task.status, task.scheduling_status)
            for task in state.tasks
        ]
        recorded_observation: Observation | None = None
        try:
            recorded_observation = Observation(
                    task=request.task,
                    scheduled_block=request.scheduled_block,
                    actual_start=request.actual_start,
                    actual_end=request.actual_end,
                    outcome=request.outcome,
                    metadata=request.metadata
                )
            state.record_observation(
                observation=recorded_observation
            )

            planning_change = PlanningChange(
                change_type=PlanningChangeType.OBSERVATION_RECORDED,
                metadata={"observation": recorded_observation}
            )

            replan_results = replan(
                planner_state=state,
                change=planning_change,
                planning_start=planning_start,
                planning_end=planning_end
            )
            
            apply_replanning_result(planner_state=state, result=replan_results)

            return replan_results
        except Exception:
            if recorded_observation is not None:
                state.observations[:] = [
                    existing
                    for existing in state.observations
                    if existing is not recorded_observation
                ]
            for task, status, scheduling_status in task_states:
                task.status = status
                task.scheduling_status = scheduling_status
            raise

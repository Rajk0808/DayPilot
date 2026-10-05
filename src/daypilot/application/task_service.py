from dataclasses import dataclass
from datetime import datetime, timedelta

from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import (
    PlanningChange,
    ReplanningResult,
    apply_replanning_result,
    replan,
)
from ..domain.task import Task
from ..domain.enums import PlanningChangeType, Priority, TaskStatus

@dataclass(frozen=True)
class TaskUpdateRequest:
    title: str | None = None
    description: str | None = None
    priority: Priority | None = None
    estimated_duration: timedelta | None = None
    deadline: datetime | None = None
    status: TaskStatus | None = None

@dataclass(frozen=True)
class TaskCreateRequest:
    id: str
    title: str
    description: str = ""
    priority: Priority = Priority.MEDIUM
    estimated_duration: timedelta = timedelta(hours=1)
    deadline: datetime | None = None
    status: TaskStatus = TaskStatus.NOT_STARTED

class TaskApplicationService:
    _UPDATE_FIELDS = (
        "title",
        "description",
        "priority",
        "estimated_duration",
        "deadline",
        "status",
    )

    def change_task(
            self,
            task: Task,
            state: PlannerState,
            updates: TaskUpdateRequest,
            planning_start: datetime,
            planning_end: datetime,
        ) -> ReplanningResult:
        if task is None:
            raise ValueError("Task cannot be None")
        if updates is None:
            raise ValueError("Updates cannot be None")
        if state is None:
            raise ValueError("Planner state cannot be None")
        if planning_start is None or planning_end is None:
            raise ValueError("Planning start and end cannot be None")
        if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
            raise ValueError("Planning start and end must be timezone-aware")
        if planning_end <= planning_start:
            raise ValueError("Planning end must be after planning start")
        if not any(existing is task for existing in state.tasks):
            raise ValueError("Task is not registered in the planner state")

        changed_fields = {
            field_name
            for field_name in self._UPDATE_FIELDS
            if getattr(updates, field_name) is not None
        }
        if not changed_fields:
            raise ValueError("Task update cannot be empty")

        requested_values = {
            field_name: getattr(updates, field_name)
            for field_name in changed_fields
        }
        self._validate_update_values(requested_values)

        original_values = {
            field_name: getattr(task, field_name)
            for field_name in changed_fields
        }
        try:
            state.update_task(task, **requested_values)

            planning_change = PlanningChange(
                change_type=PlanningChangeType.TASK_UPDATED,
                task=task,
                metadata={"changed_fields": changed_fields},
            )
            result = replan(
                planner_state=state,
                change=planning_change,
                planning_start=planning_start,
                planning_end=planning_end,
            )
            apply_replanning_result(planner_state=state, result=result)
        except Exception:
            state.update_task(task, **original_values)
            raise

        return result

    @staticmethod
    def _validate_update_values(values: dict[str, object]) -> None:
        duration = values.get("estimated_duration")
        if duration is not None and (
            not isinstance(duration, timedelta) or duration <= timedelta(0)
        ):
            raise ValueError("Task estimated duration must be a positive timedelta")

        deadline = values.get("deadline")
        if deadline is not None and (
            not isinstance(deadline, datetime) or deadline.utcoffset() is None
        ):
            raise ValueError("Task deadline must be timezone-aware")

        priority = values.get("priority")
        if priority is not None and not isinstance(priority, Priority):
            raise ValueError("Task priority must be a valid Priority")

        status = values.get("status")
        if status is not None and not isinstance(status, TaskStatus):
            raise ValueError("Task status must be a valid TaskStatus")

        for field_name in ("title", "description"):
            value = values.get(field_name)
            if value is not None and not isinstance(value, str):
                raise ValueError(f"Task {field_name} must be a string")

    def create_task(
            self,
            state: PlannerState,
            request: TaskCreateRequest,
            planning_start: datetime,
            planning_end: datetime,
        ) -> ReplanningResult:
        if state is None:
            raise ValueError("Planner state cannot be None")
        if request is None:
            raise ValueError("Task create request cannot be None")
        if planning_start is None or planning_end is None:
            raise ValueError("Planning start and end cannot be None")
        if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
            raise ValueError("Planning start and end must be timezone-aware")
        if planning_start >= planning_end:
            raise ValueError("Planning end must be after planning start")
  
        task = Task(
            id = request.id,
            title = request.title,
            description = request.description,
            priority = request.priority,
            estimated_duration = request.estimated_duration,
            deadline = request.deadline,
            status = request.status
        )
        state.add_task(task=task)

        try:
            planning_change = PlanningChange(
                change_type=PlanningChangeType.TASK_ADDED,
                task=task,
            )
            replan_results =  replan(
                planner_state=state,
                change=planning_change,
                planning_start=planning_start,
                planning_end=planning_end,
            )
            apply_replanning_result(planner_state=state, result=replan_results)
        except Exception as e:
            state.remove_task(task=task)
            raise 
        return replan_results

    def remove_task(
            self,
            state: PlannerState,
            task: Task,
            planning_start: datetime,
            planning_end: datetime,
        ) -> ReplanningResult:
        if state is None:
            raise ValueError("Planner state cannot be None")
        if task is None:
            raise ValueError("Task cannot be None")
        if planning_start is None or planning_end is None:
            raise ValueError("Planning start and end cannot be None")
        if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
            raise ValueError("Planning start and end must be timezone-aware")
        if planning_start >= planning_end:
            raise ValueError("Planning end must be after planning start")
        if not any(existing is task for existing in state.tasks):
            raise ValueError("Task is not registered in the planner state")

        planning_change = PlanningChange(
            change_type=PlanningChangeType.TASK_REMOVED,
            task=task,
        )
        result = replan(
            planner_state=state,
            change=planning_change,
            planning_start=planning_start,
            planning_end=planning_end,
        )
        apply_replanning_result(planner_state=state, result=result)
        return result
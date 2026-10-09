"""Task HTTP endpoints; use cases and planning rules remain in application services."""

from datetime import timedelta

from fastapi import APIRouter, Depends, Response, status

from daypilot.api.dependencies import get_persistent_application, get_planning_window, get_state_id
from daypilot.api.schemas.tasks import TaskCreate, TaskResponse, TaskUpdate
from daypilot.application.persistent_facade import PersistentDayPilotApplicationService
from daypilot.application.task_service import TaskCreateRequest, TaskUpdateRequest
from daypilot.domain.enums import Priority, TaskStatus
from daypilot.domain.task import Task

router = APIRouter(prefix="/tasks", tags=["tasks"])


def _task_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        title=task.title,
        description=task.description,
        status=task.status.value,
        scheduling_status=task.scheduling_status.value,
        priority=task.priority.value if task.priority is not None else None,
        estimated_duration_microseconds=(
            (task.estimated_duration.days * 86_400 + task.estimated_duration.seconds)
            * 1_000_000
            + task.estimated_duration.microseconds
        ),
        deadline=task.deadline,
        parent_id=task.parent.id if task.parent is not None else None,
        children_ids=[child.id for child in task.children],
        metadata=dict(task.metadata),
    )


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    request: TaskCreate,
    application: PersistentDayPilotApplicationService = Depends(get_persistent_application),
    state_id: str = Depends(get_state_id),
    planning_window=Depends(get_planning_window),
) -> TaskResponse:
    start, end = planning_window
    application.create_task(
        state_id,
        TaskCreateRequest(
            id=request.id,
            title=request.title,
            description=request.description,
            priority=Priority(request.priority),
            estimated_duration=timedelta(microseconds=request.estimated_duration_microseconds),
            deadline=request.deadline,
            status=TaskStatus(request.status),
        ),
        start,
        end,
    )
    return _task_response(application.get_task(state_id, request.id))


@router.get("/{task_id}", response_model=TaskResponse)
def get_task(
    task_id: str,
    application: PersistentDayPilotApplicationService = Depends(get_persistent_application),
    state_id: str = Depends(get_state_id),
) -> TaskResponse:
    return _task_response(application.get_task(state_id, task_id))


@router.patch("/{task_id}", response_model=TaskResponse)
def update_task(
    task_id: str,
    request: TaskUpdate,
    application: PersistentDayPilotApplicationService = Depends(get_persistent_application),
    state_id: str = Depends(get_state_id),
    planning_window=Depends(get_planning_window),
) -> TaskResponse:
    start, end = planning_window
    application.change_task(
        state_id,
        task_id,
        TaskUpdateRequest(
            title=request.title,
            description=request.description,
            priority=Priority(request.priority) if request.priority is not None else None,
            estimated_duration=(
                timedelta(microseconds=request.estimated_duration_microseconds)
                if request.estimated_duration_microseconds is not None
                else None
            ),
            deadline=request.deadline,
            status=TaskStatus(request.status) if request.status is not None else None,
        ),
        start,
        end,
    )
    return _task_response(application.get_task(state_id, task_id))


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: str,
    application: PersistentDayPilotApplicationService = Depends(get_persistent_application),
    state_id: str = Depends(get_state_id),
    planning_window=Depends(get_planning_window),
) -> Response:
    start, end = planning_window
    application.remove_task(state_id, task_id, start, end)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

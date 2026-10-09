"""Goal HTTP endpoints, delegating all operations to the persistent facade."""

from fastapi import APIRouter, Depends, Response, status

from daypilot.api.dependencies import get_persistent_application, get_state_id
from daypilot.api.schemas.goals import GoalCreate, GoalResponse, GoalUpdate
from daypilot.application.goal_service import GoalCreateRequest, GoalUpdateRequest
from daypilot.application.persistent_facade import PersistentDayPilotApplicationService
from daypilot.domain.goal import Goal

router = APIRouter(prefix="/goals", tags=["goals"])


def _goal_response(goal: Goal) -> GoalResponse:
    status_value = goal.status.value if hasattr(goal.status, "value") else goal.status
    return GoalResponse(
        id=goal.id,
        title=goal.title,
        description=goal.description,
        deadline=goal.deadline,
        status=status_value,
        root_task_ids=[task.id for task in goal.root_tasks],
    )


@router.post("", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
def create_goal(
    request: GoalCreate,
    application: PersistentDayPilotApplicationService = Depends(get_persistent_application),
    state_id: str = Depends(get_state_id),
) -> GoalResponse:
    goal = GoalCreateRequest(
        id=request.id,
        title=request.title,
        description=request.description,
        deadline=request.deadline,
        status=request.status,
        root_task_ids=tuple(request.root_task_ids),
    )
    return _goal_response(application.create_goal(state_id, goal))


@router.get("/{goal_id}", response_model=GoalResponse)
def get_goal(
    goal_id: str,
    application: PersistentDayPilotApplicationService = Depends(get_persistent_application),
    state_id: str = Depends(get_state_id),
) -> GoalResponse:
    return _goal_response(application.get_goal(state_id, goal_id))


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(
    goal_id: str,
    request: GoalUpdate,
    application: PersistentDayPilotApplicationService = Depends(get_persistent_application),
    state_id: str = Depends(get_state_id),
) -> GoalResponse:
    goal = application.change_goal(
        state_id,
        goal_id,
        GoalUpdateRequest(
            title=request.title,
            description=request.description,
            deadline=request.deadline,
            status=request.status,
        ),
    )
    return _goal_response(goal)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(
    goal_id: str,
    application: PersistentDayPilotApplicationService = Depends(get_persistent_application),
    state_id: str = Depends(get_state_id),
) -> Response:
    application.remove_goal(state_id, goal_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

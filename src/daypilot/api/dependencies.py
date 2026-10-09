"""Explicit FastAPI dependencies for application and planner context."""

from collections.abc import Callable
from datetime import datetime
import os
from typing import TYPE_CHECKING

from fastapi import HTTPException, Request, status

if TYPE_CHECKING:
    from daypilot.application.persistent_facade import PersistentDayPilotApplicationService


def get_persistent_application(request: Request) -> "PersistentDayPilotApplicationService":
    """Return the injected facade, lazily constructing the configured default."""
    application = getattr(request.app.state, "persistent_application", None)
    if application is None:
        application, engine = _build_default_application()
        request.app.state.persistent_application = application
        request.app.state.database_engine = engine
    return application


def get_state_id(request: Request) -> str:
    state_id = getattr(request.app.state, "state_id", None) or os.environ.get("DAYPILOT_STATE_ID")
    if not state_id:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DAYPILOT_STATE_ID is not configured",
        )
    return state_id


def get_planning_window(request: Request) -> tuple[datetime, datetime]:
    provider: Callable[[], tuple[datetime, datetime]] | None = getattr(
        request.app.state, "planning_window_provider", None
    )
    if provider is not None:
        return provider()
    start = os.environ.get("DAYPILOT_PLANNING_START")
    end = os.environ.get("DAYPILOT_PLANNING_END")
    if not start or not end:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DAYPILOT_PLANNING_START and DAYPILOT_PLANNING_END must be configured",
        )
    try:
        return _aware_datetime(start), _aware_datetime(end)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Configured planning window must use timezone-aware ISO timestamps",
        ) from exc


def _aware_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("timestamp is not timezone-aware")
    return parsed


def _build_default_application():
    from daypilot.application.application_service import DayPilotApplicationService
    from daypilot.application.constraint_service import ConstraintApplicationService
    from daypilot.application.dependency_service import DependencyApplicationService
    from daypilot.application.goal_service import GoalApplicationService
    from daypilot.application.hierarchy_service import TaskHierarchyApplicationService
    from daypilot.application.observation_service import ObservationApplicationService
    from daypilot.application.persistent_facade import PersistentDayPilotApplicationService
    from daypilot.application.planning_service import PlanningApplicationService
    from daypilot.application.task_service import TaskApplicationService
    from daypilot.application.times_service import CalendarApplicationService
    from daypilot.persistence.database import (
        DatabaseSettings,
        create_database_engine,
        create_session_factory,
    )
    from daypilot.persistence.unit_of_works import SQLAlchemyPlannerStateUnitOfWork

    settings = DatabaseSettings.from_environment()
    engine = create_database_engine(settings)
    session_factory = create_session_factory(engine)
    application = DayPilotApplicationService(
        task_service=TaskApplicationService(),
        goal_service=GoalApplicationService(),
        dependency_service=DependencyApplicationService(),
        calendar_service=CalendarApplicationService(),
        constraint_service=ConstraintApplicationService(),
        observation_service=ObservationApplicationService(),
        hierarchy_service=TaskHierarchyApplicationService(),
        planning_service=PlanningApplicationService(),
    )
    persistent = PersistentDayPilotApplicationService(
        application=application,
        unit_of_work_factory=lambda: SQLAlchemyPlannerStateUnitOfWork(session_factory),
    )
    return persistent, engine

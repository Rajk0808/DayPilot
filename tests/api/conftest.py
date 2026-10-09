from datetime import datetime, timedelta, timezone

import pytest

from daypilot.api.app import create_app
from daypilot.application.application_service import DayPilotApplicationService
from daypilot.application.goal_service import GoalApplicationService
from daypilot.application.persistent_facade import PersistentDayPilotApplicationService
from daypilot.application.planning_service import PlanningApplicationService
from daypilot.application.task_service import TaskApplicationService
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.planner import PlannerState
from daypilot.persistence.repositories.planner_state_repository import InMemoryPlannerStateRepository
from daypilot.persistence.unit_of_works.planner_state import InMemoryPlannerStateUnitOfWork

PLANNING_START = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)
PLANNING_END = PLANNING_START + timedelta(hours=8)


@pytest.fixture
def api_client():
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(PlannerState([], [], DependencyGraph(), [], [], None, []))
    application = DayPilotApplicationService(
        task_service=TaskApplicationService(),
        goal_service=GoalApplicationService(),
        dependency_service=None,
        calendar_service=None,
        constraint_service=None,
        observation_service=None,
        hierarchy_service=None,
        planning_service=PlanningApplicationService(),
    )
    persistent_application = PersistentDayPilotApplicationService(
        application,
        lambda: InMemoryPlannerStateUnitOfWork(repository),
    )
    app = create_app(
        persistent_application,
        state_id=state_id,
        planning_window_provider=lambda: (PLANNING_START, PLANNING_END),
    )
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client

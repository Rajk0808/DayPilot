from datetime import datetime, timedelta, timezone

from daypilot.application.application_service import DayPilotApplicationService
from daypilot.application.constraint_service import ConstraintApplicationService
from daypilot.application.dependency_service import DependencyApplicationService
from daypilot.application.goal_service import GoalApplicationService
from daypilot.application.hierarchy_service import TaskHierarchyApplicationService
from daypilot.application.observation_service import ObservationApplicationService
from daypilot.application.planning_service import PlanningApplicationService
from daypilot.application.task_service import TaskApplicationService, TaskCreateRequest
from daypilot.application.times_service import CalendarApplicationService
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.planner import PlannerState
from daypilot.integrations.calendar import CalendarProviderAdapter
from daypilot.integrations.calendar.providers.in_memory import (
    InMemoryCalendarProvider,
    ProviderCalendarEvent,
)


def test_planner_replans_around_events_fetched_from_calendar_integration():
    start = datetime(2026, 10, 8, 9, tzinfo=timezone.utc)
    end = start + timedelta(hours=8)
    provider = InMemoryCalendarProvider(
        [
            ProviderCalendarEvent(
                id="provider-event",
                title="Busy",
                start=start,
                end=start + timedelta(hours=2),
                metadata={"source": "fake-calendar"},
            )
        ]
    )
    calendar = CalendarProviderAdapter(provider)
    app = DayPilotApplicationService(
        task_service=TaskApplicationService(),
        goal_service=GoalApplicationService(),
        dependency_service=DependencyApplicationService(),
        calendar_service=CalendarApplicationService(),
        constraint_service=ConstraintApplicationService(),
        observation_service=ObservationApplicationService(),
        hierarchy_service=TaskHierarchyApplicationService(),
        planning_service=PlanningApplicationService(),
    )
    state = PlannerState([], [], DependencyGraph(), [], [], None, [])
    app.create_task(state, TaskCreateRequest("task-1", "Work"), start, end)

    provider_events = calendar.fetch_events(start, end)
    assert len(provider_events) == 1
    app.add_calendar_event(provider_events[0], state, start, end)

    scheduled = state.current_plan.schedule_blocks
    assert len(scheduled) == 1
    assert scheduled[0].start >= provider_events[0].end

from datetime import datetime, timedelta, timezone

import pytest

from daypilot.application import task_service as task_service_module
from daypilot.application.application_service import DayPilotApplicationService
from daypilot.application.persistent_facade import PersistentDayPilotApplicationService
from daypilot.application.planning_service import PlanningApplicationService
from daypilot.application.task_service import TaskApplicationService, TaskCreateRequest
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import (
    ObservationOutcome,
    PlanningChangeType,
    SchedulingStatus,
    TaskStatus,
)
from daypilot.domain.goal import Goal
from daypilot.domain.observation import Observation
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import PlanningChange
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task
from daypilot.persistence.repositories.planner_state_repository import (
    InMemoryPlannerStateRepository,
)
from daypilot.persistence.unit_of_works.planner_state import InMemoryPlannerStateUnitOfWork


START = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
END = START + timedelta(hours=4)


def app_service():
    return DayPilotApplicationService(
        task_service=TaskApplicationService(),
        goal_service=None,
        dependency_service=None,
        calendar_service=None,
        constraint_service=None,
        observation_service=None,
        hierarchy_service=None,
        planning_service=PlanningApplicationService(),
    )


def state_with_existing_observation():
    task = Task(
        "T1",
        "Existing task",
        scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1),
    )
    graph = DependencyGraph()
    graph.register_task(task)
    goal = Goal("G1", "Goal", root_tasks=[task])
    block = ScheduleBlock(task, START, START + timedelta(hours=1), TaskStatus.NOT_STARTED)
    plan = Plan("P1", START, timedelta(hours=4), [block], {})
    observation = Observation(
        task,
        block,
        START + timedelta(minutes=5),
        START + timedelta(minutes=20),
        ObservationOutcome.PARTIALLY_COMPLETED,
    )
    return PlannerState([goal], [task], graph, [], [], plan, [observation])


def persistent_application(repository):
    return PersistentDayPilotApplicationService(
        application=app_service(),
        unit_of_work_factory=lambda: InMemoryPlannerStateUnitOfWork(repository),
    )


def test_persistent_create_task_saves_through_repository_and_preserves_identity():
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(state_with_existing_observation())
    application = persistent_application(repository)

    result = application.create_task(
        state_id,
        TaskCreateRequest("T2", "New task", estimated_duration=timedelta(minutes=30)),
        START,
        END,
    )

    loaded = repository.get(state_id)
    tasks = {task.id: task for task in loaded.tasks}
    assert result is not None
    assert "T2" in tasks
    assert loaded.goals[0].root_tasks[0] is tasks["T1"]
    assert loaded.dependency_graph.tasks["T1"] is tasks["T1"]
    assert loaded.dependency_graph.tasks["T2"] is tasks["T2"]
    assert loaded.current_plan is not None
    task_one_block = next(
        block for block in loaded.current_plan.schedule_blocks if block.task is tasks["T1"]
    )
    assert loaded.observations[0].task is tasks["T1"]
    assert loaded.observations[0].scheduled_block is task_one_block
    assert repository._planner_states[state_id].version == 2


def test_failed_create_task_rolls_back_and_does_not_save(monkeypatch):
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(state_with_existing_observation())
    application = persistent_application(repository)

    def fail_replan(*args, **kwargs):
        raise RuntimeError("planning failed")

    monkeypatch.setattr(task_service_module, "replan", fail_replan)

    with pytest.raises(RuntimeError, match="planning failed"):
        application.create_task(
            state_id,
            TaskCreateRequest("T2", "Will not persist"),
            START,
            END,
        )

    loaded = repository.get(state_id)
    assert [task.id for task in loaded.tasks] == ["T1"]
    assert repository._planner_states[state_id].version == 1


def test_preview_replan_does_not_persist_or_increment_version():
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(state_with_existing_observation())
    application = persistent_application(repository)
    original_plan_id = repository.get(state_id).current_plan.id

    result = application.preview_replan(
        state_id,
        lambda state: PlanningChange(change_type=PlanningChangeType.PLAN_REPLACED),
        START,
        END,
    )

    assert result is not None
    loaded = repository.get(state_id)
    assert loaded.current_plan is not None
    assert loaded.current_plan.id == original_plan_id
    assert repository._planner_states[state_id].version == 1

"""Opt-in PostgreSQL integration coverage for the SQLAlchemy repository.

Set ``DAYPILOT_TEST_DATABASE_URL`` to a disposable PostgreSQL database URL to
run this test. It creates and drops an isolated, uniquely named schema.
"""

import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import (
    ConstraintType,
    ObservationOutcome,
    SchedulingStatus,
    TaskStatus,
)
from daypilot.domain.goal import Goal
from daypilot.domain.observation import Observation
from daypilot.domain.planner import PlannerState
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.times import CalendarEvent, Constraint, TimeWindow
from daypilot.domain.task import Task
from daypilot.persistence.database import DatabaseSettings, create_database_engine
from daypilot.persistence.exceptions import EntityNotFoundError
from daypilot.persistence.orm import (
    Base,
    ConstraintORM,
    GoalRootTaskORM,
    ObservationORM,
    PlannerStateORM,
    ScheduleBlockORM,
)
from daypilot.persistence.repositories.sqlalchemy_planner_state_repository import (
    SQLAlchemyPlannerStateRepository,
)
import daypilot.persistence.repositories.sqlalchemy_planner_state_repository as repository_module
from sqlalchemy.engine import make_url

DATABASE_URL = os.environ.get("DAYPILOT_TEST_DATABASE_URL")
if DATABASE_URL and make_url(DATABASE_URL).get_backend_name() != "postgresql":
    raise RuntimeError("DAYPILOT_TEST_DATABASE_URL must use PostgreSQL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="Set DAYPILOT_TEST_DATABASE_URL to run PostgreSQL repository integration coverage",
)


@pytest.fixture
def postgres_repository():
    assert DATABASE_URL is not None
    engine = create_database_engine(DatabaseSettings(DATABASE_URL))
    schema = f"daypilot_test_{uuid4().hex}"
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    schema_engine = engine.execution_options(schema_translate_map={None: schema})
    try:
        Base.metadata.create_all(schema_engine)
        factory = sessionmaker(schema_engine, expire_on_commit=False)
        yield SQLAlchemyPlannerStateRepository(factory), factory
    finally:
        Base.metadata.drop_all(schema_engine)
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


def test_postgresql_full_aggregate_atomicity_replacement_and_delete(postgres_repository, monkeypatch):
    repository, factory = postgres_repository
    start = datetime(2026, 10, 8, 9, 0, 0, 123456, tzinfo=timezone.utc)
    prerequisite = Task(
        "pg-task-a", "Prerequisite", status=TaskStatus.COMPLETED,
        estimated_duration=timedelta(minutes=30, microseconds=321),
    )
    task = Task(
        "pg-task-b", "PostgreSQL persistence",
        scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1, microseconds=654),
    )
    dependent = Task(
        "pg-task-c", "Review", scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(minutes=45, microseconds=987),
    )
    prerequisite.add_child(task)
    graph = DependencyGraph()
    for item in (prerequisite, task, dependent):
        graph.register_task(item)
    graph.add_dependency(dependent, task)
    block_one = ScheduleBlock(task, start, start + timedelta(hours=1))
    block_two = ScheduleBlock(dependent, start + timedelta(hours=1), start + timedelta(hours=2))
    plan = Plan(
        "pg-plan",
        start,
        timedelta(hours=3, microseconds=987),
        [block_one, block_two],
        {"kind": "postgres"},
    )
    observation = Observation(
        task,
        block_one,
        start + timedelta(minutes=1, microseconds=234),
        start + timedelta(minutes=20, microseconds=567),
        ObservationOutcome.PARTIALLY_COMPLETED,
        {"note": "jsonb round trip"},
    )
    state = PlannerState(
        goals=[Goal("pg-goal", "Complete", root_tasks=[prerequisite, dependent])],
        tasks=[prerequisite, task, dependent],
        dependency_graph=graph,
        calendar_events=[
            CalendarEvent(
                "pg-event", "Meeting", start + timedelta(hours=2),
                start + timedelta(hours=2, minutes=30), {"room": "A"},
            )
        ],
        constraints=[
            Constraint(
                ConstraintType.HARD_CONSTRAINT,
                TimeWindow(start, start + timedelta(hours=3)),
                "PostgreSQL work window",
            )
        ],
        current_plan=plan,
        observations=[observation],
    )

    state_id = repository.save(state)
    with factory() as session:
        persisted_uuid = session.scalar(
            select(ConstraintORM.constraint_id).where(ConstraintORM.state_id == state_id)
        )
    restored = repository.get(state_id)
    task_b = next(item for item in restored.tasks if item.id == "pg-task-b")
    assert restored.goals[0].root_tasks[0] is restored.tasks[0]
    assert restored.dependency_graph.tasks[task_b.id] is task_b
    assert restored.current_plan is not None
    assert restored.current_plan.planning_horizon == timedelta(hours=3, microseconds=987)
    assert restored.observations[0].scheduled_block is restored.current_plan.schedule_blocks[0]
    assert restored.observations[0].actual_start.microsecond == 123690
    assert task_b.estimated_duration == timedelta(hours=1, microseconds=654)
    assert restored.calendar_events[0].metadata == {"room": "A"}
    assert restored.constraints[0].description == "PostgreSQL work window"

    # The valid GoalRootTask and observation rows exercise their composite
    # same-state/task foreign keys. Verify PostgreSQL also rejects a bad edge.
    with factory() as session:
        session.add(
            GoalRootTaskORM(state_id=state_id, goal_id="pg-goal", task_id="missing-task")
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    # A failed late observation insert must roll back the aggregate replacement.
    original_to_orm = repository_module.planner_state_mapper.to_orm

    def append_invalid_observation(snapshot):
        rows = original_to_orm(snapshot)
        rows["observations"].append(
            ObservationORM(
                state_id=state_id,
                id="bad-observation",
                task_id="missing-task",
                schedule_block_id="missing-block",
                actual_start_timestamp_microseconds=1,
                actual_end_timestamp_microseconds=2,
                outcome="bad",
                metadata_json={},
            )
        )
        return rows

    monkeypatch.setattr(
        repository_module.planner_state_mapper,
        "to_orm",
        append_invalid_observation,
    )
    with pytest.raises(IntegrityError):
        repository.save(PlannerState([], [], DependencyGraph(), [], [], None, []), state_id=state_id)
    monkeypatch.setattr(repository_module.planner_state_mapper, "to_orm", original_to_orm)
    assert len(repository.get(state_id).tasks) == 3

    repository.save(restored, state_id=state_id)
    with factory() as session:
        assert session.scalar(
            select(ConstraintORM.constraint_id).where(ConstraintORM.state_id == state_id)
        ) == persisted_uuid
        assert session.scalar(
            select(PlannerStateORM.version).where(PlannerStateORM.id == state_id)
        ) == 2

    # Replacement uses ON DELETE CASCADE for all previous child rows.
    repository.save(PlannerState([], [], DependencyGraph(), [], [], None, []), state_id=state_id)
    assert repository.get(state_id).tasks == []
    with factory() as session:
        for model in (
            GoalRootTaskORM,
            ObservationORM,
            ScheduleBlockORM,
            ConstraintORM,
        ):
            assert session.scalar(
                select(func.count()).select_from(model).where(model.state_id == state_id)
            ) == 0

    repository.delete(state_id)
    assert not repository.exists(state_id)
    with pytest.raises(EntityNotFoundError):
        repository.get(state_id)

"""PostgreSQL verification for Alembic schema and the SQLAlchemy UOW."""

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.engine import make_url

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import ConstraintType
from daypilot.domain.goal import Goal
from daypilot.domain.planner import PlannerState
from daypilot.domain.task import Task
from daypilot.domain.times import Constraint, TimeWindow
from daypilot.persistence.database import DatabaseSettings, create_database_engine
from daypilot.persistence.orm import ConstraintORM, GoalRootTaskORM, TaskORM
from daypilot.persistence.unit_of_works import SQLAlchemyPlannerStateUnitOfWork

DATABASE_URL = os.environ.get("DAYPILOT_TEST_DATABASE_URL")
if DATABASE_URL and make_url(DATABASE_URL).get_backend_name() != "postgresql":
    raise RuntimeError("DAYPILOT_TEST_DATABASE_URL must use PostgreSQL")
pytestmark = pytest.mark.skipif(
    not DATABASE_URL,
    reason="Set DAYPILOT_TEST_DATABASE_URL to run PostgreSQL migration/UOW tests",
)


@pytest.fixture
def migrated_schema():
    assert DATABASE_URL is not None
    engine = create_database_engine(DatabaseSettings(DATABASE_URL))
    schema = f"daypilot_migration_{uuid4().hex}"
    quoted_schema = engine.dialect.identifier_preparer.quote(schema)
    with engine.begin() as connection:
        connection.execute(text(f"CREATE SCHEMA {quoted_schema}"))
    schema_engine = engine.execution_options(schema_translate_map={None: schema})
    config_path = str(Path(__file__).resolve().parents[3] / "alembic.ini")

    def run_migration(action, revision):
        with schema_engine.connect() as connection:
            connection.exec_driver_sql(f"SET search_path TO {quoted_schema}")
            config = Config(config_path)
            config.attributes["connection"] = connection
            action(config, revision)
            connection.commit()

    try:
        run_migration(command.upgrade, "head")
        run_migration(command.downgrade, "-1")
        run_migration(command.upgrade, "head")
        yield schema_engine, schema, config_path
    finally:
        with engine.begin() as connection:
            connection.execute(text(f"DROP SCHEMA {quoted_schema} CASCADE"))
        engine.dispose()


def _state(task_id: str, constraint_description: str) -> PlannerState:
    task = Task(
        task_id,
        "Persisted task",
        estimated_duration=timedelta(seconds=1, microseconds=22),
        deadline=datetime(2026, 10, 8, 9, 0, 0, 123456, tzinfo=timezone.utc),
        metadata={"payload": {"number": 3}},
    )
    graph = DependencyGraph()
    graph.register_task(task)
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(
            datetime(2026, 10, 8, 9, tzinfo=timezone.utc),
            datetime(2026, 10, 8, 17, tzinfo=timezone.utc),
        ),
        constraint_description,
    )
    goal = Goal(f"goal-{task_id}", "Owns task", root_tasks=[task])
    return PlannerState([goal], [task], graph, [], [constraint], None, [])


def test_migrated_postgresql_schema_repository_and_uow(migrated_schema):
    schema_engine, schema, _ = migrated_schema
    factory = sessionmaker(schema_engine, expire_on_commit=False)
    with schema_engine.connect() as connection:
        tables = set(inspect(connection).get_table_names(schema=schema))
    assert tables == {
        "alembic_version",
        "planner_states",
        "tasks",
        "goals",
        "goal_root_tasks",
        "dependencies",
        "calendar_events",
        "constraints",
        "plans",
        "schedule_blocks",
        "observations",
    }

    with SQLAlchemyPlannerStateUnitOfWork(factory) as uow:
        state_id = uow.planner_states.save(_state("task-one", "fixed"))
    with SQLAlchemyPlannerStateUnitOfWork(factory) as uow:
        other_state_id = uow.planner_states.save(_state("task-two", "other"))

    with factory() as session:
        task_row = session.get(TaskORM, (state_id, "task-one"))
        constraint_row = session.scalar(
            select(ConstraintORM).where(ConstraintORM.state_id == state_id)
        )
        assert task_row.metadata_json == {"payload": {"number": 3}}
        assert task_row.estimated_duration_microseconds == 1_000_022
        assert task_row.deadline_timestamp_microseconds == 1_791_450_000_123_456
        assert constraint_row is not None
        persisted_constraint_id = constraint_row.constraint_id
        assert persisted_constraint_id is not None

        session.add(
            GoalRootTaskORM(
                state_id=state_id,
                goal_id="goal-task-one",
                task_id="task-two",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()

    with pytest.raises(RuntimeError, match="rollback transaction"):
        with SQLAlchemyPlannerStateUnitOfWork(factory) as uow:
            loaded = uow.planner_states.get(state_id)
            loaded.tasks[0].title = "not committed"
            uow.planner_states.save(loaded, state_id=state_id)
            raise RuntimeError("rollback transaction")

    with SQLAlchemyPlannerStateUnitOfWork(factory) as uow:
        restored = uow.planner_states.get(state_id)
        assert restored.tasks[0].title == "Persisted task"
        assert restored.tasks[0].estimated_duration == timedelta(seconds=1, microseconds=22)
        assert restored.constraints[0].description == "fixed"

        restored.tasks[0].title = "replacement committed"
        uow.planner_states.save(restored, state_id=state_id)

    with factory() as session:
        assert session.scalar(
            select(ConstraintORM.constraint_id).where(ConstraintORM.state_id == state_id)
        ) == persisted_constraint_id

    with SQLAlchemyPlannerStateUnitOfWork(factory) as uow:
        uow.planner_states.delete(state_id)
        uow.planner_states.delete(other_state_id)

    with factory() as session:
        assert session.scalar(
            select(TaskORM).where(TaskORM.state_id == state_id)
        ) is None
        assert session.scalar(
            select(ConstraintORM).where(ConstraintORM.state_id == state_id)
        ) is None


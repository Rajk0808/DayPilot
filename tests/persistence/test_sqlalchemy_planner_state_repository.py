from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, event, select
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
from daypilot.domain.task import Task
from daypilot.domain.times import CalendarEvent, Constraint, TimeWindow
from daypilot.persistence.exceptions import EntityNotFoundError
from daypilot.persistence.orm import Base, ObservationORM, PlannerStateORM
from daypilot.persistence.repositories.sqlalchemy_planner_state_repository import (
    SQLAlchemyPlannerStateRepository,
)
import daypilot.persistence.repositories.sqlalchemy_planner_state_repository as sql_repo_module


@pytest.fixture
def database():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    yield engine, factory
    Base.metadata.drop_all(engine)
    engine.dispose()


def full_state():
    start = datetime(2026, 10, 7, 9, tzinfo=timezone.utc)
    prerequisite = Task(
        "task-a", "Prerequisite", status=TaskStatus.COMPLETED,
        estimated_duration=timedelta(hours=1),
    )
    child = Task(
        "task-b", "Draft", scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1),
    )
    prerequisite.add_child(child)
    dependent = Task(
        "task-c", "Review", scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1),
    )
    graph = DependencyGraph()
    for task in (prerequisite, child, dependent):
        graph.register_task(task)
    graph.add_dependency(dependent, child)
    block_one = ScheduleBlock(child, start, start + timedelta(hours=1))
    block_two = ScheduleBlock(dependent, start + timedelta(hours=1), start + timedelta(hours=2))
    plan = Plan("plan-1", start, timedelta(hours=3), [block_one, block_two], {"kind": "daily"})
    observation = Observation(
        child,
        block_one,
        start + timedelta(minutes=5),
        start + timedelta(minutes=25),
        ObservationOutcome.PARTIALLY_COMPLETED,
        {"note": "started"},
    )
    goal = Goal("goal-1", "Finish", root_tasks=[prerequisite, dependent])
    event_item = CalendarEvent(
        "event-1", "Meeting", start + timedelta(hours=2), start + timedelta(hours=2, minutes=30),
        {"calendar": "work"},
    )
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(start, start + timedelta(hours=3)),
        "Work window",
    )
    return PlannerState(
        [goal], [prerequisite, child, dependent], graph, [event_item], [constraint], plan,
        [observation],
    )


def empty_state():
    return PlannerState([], [], DependencyGraph(), [], [], None, [])


def test_save_generates_id_and_starts_at_version_one(database):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)

    state_id = repository.save(empty_state())

    assert state_id
    assert repository.exists(state_id)
    with factory() as session:
        assert session.get(PlannerStateORM, state_id).version == 1


def test_full_aggregate_round_trip_preserves_graph_identity_and_constraint_uuid(database):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)
    state_id = repository.save(full_state())

    restored = repository.get(state_id)

    assert restored.current_plan is not None
    assert restored.current_plan.id == "plan-1"
    task_a = next(task for task in restored.tasks if task.id == "task-a")
    task_b = next(task for task in restored.tasks if task.id == "task-b")
    assert task_a.children[0] is task_b
    assert restored.goals[0].root_tasks[0] is task_a
    assert restored.dependency_graph.tasks["task-a"] is task_a
    assert restored.dependency_graph.tasks["task-b"] is task_b
    assert restored.dependency_graph.has_dependency(
        restored.dependency_graph.tasks["task-c"], task_b
    )
    assert restored.observations[0].task is task_b
    assert restored.observations[0].scheduled_block is restored.current_plan.schedule_blocks[0]
    assert restored.constraints[0].description == "Work window"
    assert restored.calendar_events[0].id == "event-1"

    # Persistence-owned constraint identity is represented by the row UUID and
    # remains stable when the aggregate is read again and saved.
    with factory() as session:
        before = session.execute(select(sql_repo_module.ConstraintORM)).scalar_one().constraint_id
    repository.save(restored, state_id=state_id)
    with factory() as session:
        after = session.execute(select(sql_repo_module.ConstraintORM)).scalar_one().constraint_id
        assert session.get(PlannerStateORM, state_id).version == 2
    assert before == after


def test_replacement_removes_stale_child_rows_and_increments_version(database):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)
    state_id = repository.save(full_state())

    repository.save(empty_state(), state_id=state_id)

    assert repository.get(state_id).tasks == []
    with factory() as session:
        assert session.get(PlannerStateORM, state_id).version == 2
        assert session.scalar(select(ObservationORM).where(ObservationORM.state_id == state_id)) is None


def test_exists_missing_get_and_delete_semantics(database):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)
    state_id = repository.save(empty_state())

    assert repository.exists(state_id)
    assert not repository.exists("missing")
    repository.delete(state_id)
    assert not repository.exists(state_id)
    with pytest.raises(EntityNotFoundError):
        repository.get(state_id)
    with pytest.raises(EntityNotFoundError):
        repository.delete(state_id)


def test_explicit_save_requires_existing_state_id(database):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)

    with pytest.raises(EntityNotFoundError):
        repository.save(empty_state(), state_id="not-created")


def test_save_and_get_are_isolated_from_caller_mutation(database):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)
    state = full_state()
    state_id = repository.save(state)
    state.tasks[1].metadata["after-save"] = "caller"

    first_read = repository.get(state_id)
    first_read.tasks[1].metadata["after-read"] = "caller"
    second_read = repository.get(state_id)

    assert "after-save" not in second_read.tasks[1].metadata
    assert "after-read" not in second_read.tasks[1].metadata


def test_changed_constraint_values_may_receive_a_new_persistence_uuid(database):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)
    state_id = repository.save(full_state())
    with factory() as session:
        original_id = session.scalar(
            select(sql_repo_module.ConstraintORM.constraint_id).where(
                sql_repo_module.ConstraintORM.state_id == state_id
            )
        )

    state = repository.get(state_id)
    original = state.constraints[0]
    state.constraints[0] = Constraint(
        original.type,
        original.rule_information,
        "Changed constraint value",
    )
    repository.save(state, state_id=state_id)

    with factory() as session:
        updated_id = session.scalar(
            select(sql_repo_module.ConstraintORM.constraint_id).where(
                sql_repo_module.ConstraintORM.state_id == state_id
            )
        )
    assert updated_id != original_id


def test_states_are_isolated_by_id(database):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)
    state_a = repository.save(full_state())
    state_b = repository.save(empty_state())

    assert state_a != state_b
    assert len(repository.get(state_a).tasks) == 3
    assert repository.get(state_b).tasks == []


def test_failed_mid_save_rolls_back_replacement_atomically(database, monkeypatch):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)
    state_id = repository.save(full_state())
    original_mapper = sql_repo_module.planner_state_mapper.to_orm

    def with_invalid_late_row(snapshot):
        rows = original_mapper(snapshot)
        rows["observations"].append(
            ObservationORM(
                state_id=snapshot.state_id,
                id="invalid-observation",
                task_id="missing-task",
                schedule_block_id="missing-block",
                actual_start_timestamp_microseconds=1,
                actual_end_timestamp_microseconds=2,
                outcome="invalid",
                metadata_json={},
            )
        )
        return rows

    monkeypatch.setattr(sql_repo_module.planner_state_mapper, "to_orm", with_invalid_late_row)
    with pytest.raises(IntegrityError):
        repository.save(empty_state(), state_id=state_id)
    monkeypatch.setattr(sql_repo_module.planner_state_mapper, "to_orm", original_mapper)

    restored = repository.get(state_id)
    assert len(restored.tasks) == 3
    with factory() as session:
        assert session.get(PlannerStateORM, state_id).version == 1


def test_cross_state_orm_rows_are_rejected_before_persistence(database, monkeypatch):
    _, factory = database
    repository = SQLAlchemyPlannerStateRepository(factory)
    original_mapper = sql_repo_module.planner_state_mapper.to_orm

    def with_wrong_owner(snapshot):
        rows = original_mapper(snapshot)
        rows["tasks"][0].state_id = "some-other-state"
        return rows

    monkeypatch.setattr(sql_repo_module.planner_state_mapper, "to_orm", with_wrong_owner)
    with pytest.raises(ValueError, match="belongs to state"):
        repository.save(full_state())
    monkeypatch.setattr(sql_repo_module.planner_state_mapper, "to_orm", original_mapper)

    assert not repository.exists("some-other-state")


def test_repository_can_join_an_external_session_transaction(database):
    _, factory = database
    with factory() as session:
        repository = SQLAlchemyPlannerStateRepository(session)
        with session.begin():
            state_id = repository.save(empty_state())
            assert repository.exists(state_id)
        assert repository.exists(state_id)



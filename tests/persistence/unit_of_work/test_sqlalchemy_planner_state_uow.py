import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.planner import PlannerState
from daypilot.domain.task import Task
from daypilot.persistence.orm import Base, PlannerStateORM
from daypilot.persistence.unit_of_works import SQLAlchemyPlannerStateUnitOfWork


class TrackingSession(Session):
    close_count = 0

    def close(self):
        self.close_count += 1
        super().close()


@pytest.fixture
def database():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(engine, "begin")
    def begin_sqlite_transaction(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, class_=TrackingSession, expire_on_commit=False)
    try:
        yield engine, factory
    finally:
        engine.dispose()


def state(title="Task"):
    task = Task("task-1", title)
    graph = DependencyGraph()
    graph.register_task(task)
    return PlannerState([], [task], graph, [], [], None, [])


def test_context_exit_commits_and_closes_session(database):
    engine, factory = database
    created = []

    def tracked_factory():
        session = factory()
        created.append(session)
        return session

    with SQLAlchemyPlannerStateUnitOfWork(tracked_factory) as uow:
        state_id = uow.planner_states.save(state())
        assert uow.session is created[0]

    assert created[0].close_count == 1
    assert created[0].get_transaction() is None
    with Session(engine) as session:
        assert session.get(PlannerStateORM, state_id) is not None


def test_exception_rolls_back_and_closes_session(database):
    engine, factory = database
    sessions = []

    def tracked_factory():
        session = factory()
        sessions.append(session)
        return session

    with pytest.raises(RuntimeError, match="abort"):
        with SQLAlchemyPlannerStateUnitOfWork(tracked_factory) as uow:
            state_id = uow.planner_states.save(state())
            raise RuntimeError("abort")

    assert sessions[0].close_count == 1
    assert sessions[0].get_transaction() is None
    with Session(engine) as session:
        assert session.get(PlannerStateORM, state_id) is None


def test_repository_uses_uow_owned_session(database):
    _, factory = database
    session = factory()
    uow = SQLAlchemyPlannerStateUnitOfWork(lambda: session)
    with uow:
        assert uow.planner_states._session is uow.session
        state_id = uow.planner_states.save(state())
        assert uow.planner_states.exists(state_id)
    assert session.close_count == 1


def test_failed_transaction_leaves_database_unchanged(database):
    engine, factory = database
    repository = SQLAlchemyPlannerStateUnitOfWork(factory)
    with repository as uow:
        state_id = uow.planner_states.save(state("original"))

    with pytest.raises(ValueError, match="abort replacement"):
        with SQLAlchemyPlannerStateUnitOfWork(factory) as uow:
            loaded = uow.planner_states.get(state_id)
            loaded.tasks[0].title = "uncommitted replacement"
            uow.planner_states.save(loaded, state_id=state_id)
            raise ValueError("abort replacement")

    with SQLAlchemyPlannerStateUnitOfWork(factory) as uow:
        assert uow.planner_states.exists(state_id)
        assert uow.planner_states.get(state_id).tasks[0].title == "original"


"""SQLAlchemy transaction boundary for planner state persistence."""

from collections.abc import Callable

from sqlalchemy.orm import Session

from daypilot.persistence.repositories.sqlalchemy_planner_state_repository import (
    SQLAlchemyPlannerStateRepository,
)
from daypilot.persistence.repositories.planner_state_repository import PlannerStateRepository
from daypilot.persistence.unit_of_works.planner_state import PlannerStateUnitOfWork


class SQLAlchemyPlannerStateUnitOfWork(PlannerStateUnitOfWork):
    """Own one SQLAlchemy session and transaction for a unit of work."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        if not callable(session_factory):
            raise TypeError("session_factory must be callable")
        self._session_factory = session_factory
        self._session: Session | None = None
        self._repository: SQLAlchemyPlannerStateRepository | None = None
        self._transaction = None
        self._state = "new"

    @property
    def planner_states(self) -> PlannerStateRepository:
        self._require_active()
        assert self._repository is not None
        return self._repository

    @property
    def lifecycle_state(self) -> str:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state == "active"

    @property
    def session(self) -> Session:
        """The UOW-owned session, available only while active."""
        self._require_active()
        assert self._session is not None
        return self._session

    def begin(self) -> None:
        if self._state != "new":
            raise RuntimeError(f"Cannot begin a unit of work in state {self._state!r}.")
        session = self._session_factory()
        if not isinstance(session, Session):
            close = getattr(session, "close", None)
            if callable(close):
                close()
            raise TypeError("session_factory must return a SQLAlchemy Session")
        try:
            self._transaction = session.begin()
            self._session = session
            self._repository = SQLAlchemyPlannerStateRepository(session)
            self._state = "active"
        except Exception:
            session.close()
            raise

    def commit(self) -> None:
        self._require_active()
        try:
            assert self._transaction is not None
            self._transaction.commit()
            self._state = "committed"
        except Exception:
            if self._transaction is not None and self._transaction.is_active:
                self._transaction.rollback()
            self._state = "rolled_back"
            raise
        finally:
            self._close_session()

    def rollback(self) -> None:
        self._require_active()
        try:
            assert self._transaction is not None
            self._transaction.rollback()
            self._state = "rolled_back"
        finally:
            self._close_session()

    def __enter__(self) -> "SQLAlchemyPlannerStateUnitOfWork":
        self.begin()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._state != "active":
            return False
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def _require_active(self) -> None:
        if self._state != "active":
            raise RuntimeError(f"Unit of work is not active (state: {self._state}).")

    def _close_session(self) -> None:
        session, self._session = self._session, None
        self._transaction = None
        self._repository = None
        if session is not None:
            session.close()


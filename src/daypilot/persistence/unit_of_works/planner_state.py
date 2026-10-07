    
"""Unit-of-work contract and an in-memory transactional implementation."""

from abc import ABC, abstractmethod
from copy import deepcopy
from daypilot.domain.planner import PlannerState
from daypilot.persistence.repositories.planner_state_repository import (
    InMemoryPlannerStateRepository,
    PlannerStateRepository,
)


class PlannerStateUnitOfWork(ABC):
    """Persistence transaction boundary for PlannerState repository operations."""

    @property
    @abstractmethod
    def planner_states(self) -> PlannerStateRepository:
        """Repository whose operations participate in this unit of work."""

    @abstractmethod
    def begin(self) -> None:
        """Start the unit of work."""

    @abstractmethod
    def commit(self) -> None:
        """Make all staged persistence changes visible together."""

    @abstractmethod
    def rollback(self) -> None:
        """Discard all staged persistence changes."""

    @abstractmethod
    def __enter__(self) -> "PlannerStateUnitOfWork":
        pass

    @abstractmethod
    def __exit__(self, exc_type, exc_value, traceback) -> bool | None:
        pass


class _TransactionalRepository(PlannerStateRepository):
    """Repository facade that prevents use outside an active UOW."""

    def __init__(self, unit_of_work: "InMemoryPlannerStateUnitOfWork") -> None:
        self._unit_of_work = unit_of_work

    def _repository(self) -> InMemoryPlannerStateRepository:
        self._unit_of_work._require_active()
        assert self._unit_of_work._working_repository is not None
        return self._unit_of_work._working_repository

    def save(self, state: PlannerState, state_id: str | None = None) -> str:
        return self._repository().save(state, state_id)

    def get(self, state_id: str) -> PlannerState:
        return self._repository().get(state_id)

    def exists(self, state_id: str) -> bool:
        return self._repository().exists(state_id)

    def delete(self, state_id: str) -> None:
        self._repository().delete(state_id)


class InMemoryPlannerStateUnitOfWork(PlannerStateUnitOfWork):
    """Stages repository changes and atomically publishes or discards them.

    Lifecycle: a UOW can be entered once. Successful context exit commits;
    exceptional exit rolls back and propagates the exception. Explicit commit
    or rollback closes it immediately. Nested and repeated use is rejected.
    """

    def __init__(self, repository: InMemoryPlannerStateRepository) -> None:
        if not isinstance(repository, InMemoryPlannerStateRepository):
            raise TypeError("In-memory unit of work requires an in-memory planner state repository.")
        self._committed_repository = repository
        self._working_repository: InMemoryPlannerStateRepository | None = None
        self._state = "new"
        self._repository_facade = _TransactionalRepository(self)

    @property
    def planner_states(self) -> PlannerStateRepository:
        return self._repository_facade

    @property
    def lifecycle_state(self) -> str:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state == "active"

    def begin(self) -> None:
        if self._state != "new":
            raise RuntimeError(f"Cannot begin a unit of work in state {self._state!r}.")
        self._working_repository = InMemoryPlannerStateRepository()
        # This adapter's complete committed representation is one dictionary
        # of immutable-by-convention snapshots; copy it for isolated staging.
        self._working_repository._planner_states = deepcopy(
            self._committed_repository._planner_states
        )
        self._state = "active"

    def commit(self) -> None:
        self._require_active()
        assert self._working_repository is not None
        replacement = deepcopy(self._working_repository._planner_states)
        # One reference replacement publishes the staged aggregate set.
        self._committed_repository._planner_states = replacement
        self._working_repository = None
        self._state = "committed"

    def rollback(self) -> None:
        self._require_active()
        self._working_repository = None
        self._state = "rolled_back"

    def __enter__(self) -> "InMemoryPlannerStateUnitOfWork":
        self.begin()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        if self._state != "active":
            return False
        if exc_type is None:
            try:
                self.commit()
            except Exception:
                if self._state == "active":
                    self.rollback()
                raise
        else:
            self.rollback()
        return False

    def _require_active(self) -> None:
        if self._state != "active":
            raise RuntimeError(f"Unit of work is not active (state: {self._state}).")

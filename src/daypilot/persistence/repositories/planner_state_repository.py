"""Planner state repository contract and snapshot-backed in-memory adapter.

``save(state)`` creates a state and returns its stable repository ID. To update
an existing aggregate, including after reconstruction, pass the ID returned by
the original save:
``save(reconstructed_state, state_id=state_id)``.

The adapter stores defensive copies of database-neutral persisted snapshots and
reconstructs a fresh domain aggregate on each read.
"""

from abc import ABC, abstractmethod
from copy import deepcopy
from uuid import uuid4

from daypilot.domain.planner import PlannerState
from daypilot.persistence.aggregate.planner_state import (
    PersistedPlannerState,
    from_persisted_planner_state,
    to_persisted_planner_state,
)
from daypilot.persistence.exceptions import EntityNotFoundError


class PlannerStateRepository(ABC):
    """Storage-independent contract for PlannerState aggregates."""

    @abstractmethod
    def save(self, state: PlannerState, state_id: str | None = None) -> str:
        """
        Create a new PlannerState when state_id is omitted,
        or update an existing PlannerState identified by state_id.
        """
        
    @abstractmethod
    def get(self, state_id: str) -> PlannerState:
        """Return a state, raising EntityNotFoundError when it is absent."""

    @abstractmethod
    def exists(self, state_id: str) -> bool:
        """Return whether the given state ID is stored."""

    @abstractmethod
    def delete(self, state_id: str) -> None:
        """Delete a state, raising EntityNotFoundError when it is absent."""


class InMemoryPlannerStateRepository(PlannerStateRepository):
    """Dictionary-backed adapter storing complete persisted aggregate snapshots."""

    def __init__(self) -> None:
        self._planner_states: dict[str, PersistedPlannerState] = {}

    def save(self, state: PlannerState, state_id: str | None = None) -> str:
        if state is None:
            raise TypeError("Planner state cannot be None")
        if not isinstance(state, PlannerState):
            raise TypeError("Planner state must be an instance of PlannerState")
        if state_id is not None and (not isinstance(state_id, str) or not state_id):
            raise ValueError("Planner state ID must be a non-empty string")

        if state_id is None:
            state_id = uuid4().hex
            version = 1
        else:
            existing = self._planner_states.get(state_id)
            if existing is None:
                raise EntityNotFoundError(f"Planner state {state_id!r} does not exist")
            version = existing.version + 1

        snapshot = to_persisted_planner_state(state, state_id, version=version)
        self._planner_states[state_id] = deepcopy(snapshot)
        return state_id

    def get(self, state_id: str) -> PlannerState:
        self._validate_state_id(state_id)
        try:
            snapshot = deepcopy(self._planner_states[state_id])
        except KeyError as exc:
            raise EntityNotFoundError(
                f"Planner state {state_id!r} does not exist"
            ) from exc
        return from_persisted_planner_state(snapshot)

    def exists(self, state_id: str) -> bool:
        self._validate_state_id(state_id)
        return state_id in self._planner_states

    def delete(self, state_id: str) -> None:
        self._validate_state_id(state_id)
        try:
            del self._planner_states[state_id]
        except KeyError as exc:
            raise EntityNotFoundError(
                f"Planner state {state_id!r} does not exist"
            ) from exc

    @staticmethod
    def _validate_state_id(state_id: str) -> None:
        if state_id is None:
            raise TypeError("Planner state ID cannot be None")
        if not isinstance(state_id, str) or not state_id:
            raise ValueError("Planner state ID must be a non-empty string")

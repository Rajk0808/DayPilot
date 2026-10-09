"""SQLAlchemy adapter for complete PlannerState aggregate persistence."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from uuid import uuid4

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session

from daypilot.domain.planner import PlannerState
from daypilot.persistence.aggregate.planner_state import (
    PersistedPlannerState,
    from_persisted_planner_state,
    to_persisted_planner_state,
)
from daypilot.persistence.exceptions import EntityNotFoundError
from daypilot.persistence.models.constraint import ConstraintRecord
from daypilot.persistence.orm import (
    CalendarEventORM,
    ConstraintORM,
    DependencyORM,
    GoalORM,
    GoalRootTaskORM,
    ObservationORM,
    PlanORM,
    PlannerStateORM,
    ScheduleBlockORM,
    TaskORM,
)
from daypilot.persistence.orm_mappers import planner_state as planner_state_mapper
from daypilot.persistence.repositories.planner_state_repository import PlannerStateRepository

SessionFactory = Callable[[], Session]


class SQLAlchemyPlannerStateRepository(PlannerStateRepository):
    """Persist aggregate snapshots through a SQLAlchemy session.

    Pass a session factory for repository-owned transactions, or a Session when
    an outer unit of work owns commit and rollback. Operations on a Session with
    an active transaction use a savepoint and leave the outer transaction open.
    """

    def __init__(self, session_or_factory: Session | SessionFactory) -> None:
        if isinstance(session_or_factory, Session):
            self._session = session_or_factory
            self._session_factory = None
        elif callable(session_or_factory):
            self._session = None
            self._session_factory = session_or_factory
        else:
            raise TypeError("Expected a SQLAlchemy Session or session factory")

    def save(self, state: PlannerState, state_id: str | None = None) -> str:
        if state is None:
            raise TypeError("Planner state cannot be None")
        if not isinstance(state, PlannerState):
            raise TypeError("Planner state must be an instance of PlannerState")
        if state_id is not None and (not isinstance(state_id, str) or not state_id):
            raise ValueError("Planner state ID must be a non-empty string")

        assigned_id = state_id or uuid4().hex
        with self._session_scope() as session:
            existing = session.get(PlannerStateORM, assigned_id, populate_existing=True)
            if state_id is not None and existing is None:
                raise EntityNotFoundError(f"Planner state {state_id!r} does not exist")
            if state_id is None and existing is not None:
                raise ValueError(f"Generated planner state ID {assigned_id!r} already exists")
            version = existing.version + 1 if existing is not None else 1
            snapshot = to_persisted_planner_state(state, assigned_id, version=version)
            if existing is not None:
                previous_constraints = list(
                    session.scalars(
                        select(ConstraintORM).where(ConstraintORM.state_id == assigned_id)
                    )
                )
                _preserve_matching_constraint_ids(snapshot, previous_constraints)
            rows = planner_state_mapper.to_orm(snapshot)
            _validate_row_ownership(rows, assigned_id)

            if existing is not None:
                # Database ON DELETE CASCADE removes all prior child rows. Flush
                # the root deletion before inserting the replacement with the
                # same primary key, within this same transaction/savepoint.
                _expunge_state_rows(session, assigned_id)
                session.execute(
                    delete(PlannerStateORM).where(PlannerStateORM.id == assigned_id)
                )
                session.flush()
            for table_name in (
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
            ):
                row_group = rows[table_name]
                session.add_all(row_group)
                session.flush()
        return assigned_id

    def get(self, state_id: str) -> PlannerState:
        _validate_state_id(state_id)
        with self._session_scope() as session:
            state_row = session.get(PlannerStateORM, state_id, populate_existing=True)
            if state_row is None:
                raise EntityNotFoundError(f"Planner state {state_id!r} does not exist")
            collections = {
                name: list(
                    session.scalars(
                        select(model)
                        .where(model.state_id == state_id)
                        .execution_options(populate_existing=True)
                    )
                )
                for name, model in _CHILD_MODELS.items()
            }
            snapshot: PersistedPlannerState = planner_state_mapper.from_orm(
                state_row,
                **collections,
            )
            return from_persisted_planner_state(snapshot)

    def exists(self, state_id: str) -> bool:
        _validate_state_id(state_id)
        with self._session_scope() as session:
            return bool(
                session.scalar(
                    select(exists().where(PlannerStateORM.id == state_id))
                )
            )

    def delete(self, state_id: str) -> None:
        _validate_state_id(state_id)
        with self._session_scope() as session:
            result = session.execute(
                delete(PlannerStateORM).where(PlannerStateORM.id == state_id)
            )
            if result.rowcount == 0:
                raise EntityNotFoundError(f"Planner state {state_id!r} does not exist")
            session.flush()

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        if self._session_factory is not None:
            with self._session_factory() as session:
                with session.begin():
                    yield session
            return

        assert self._session is not None
        transaction = (
            self._session.begin_nested()
            if self._session.in_transaction()
            else self._session.begin()
        )
        with transaction:
            yield self._session


_CHILD_MODELS = {
    "tasks": TaskORM,
    "goals": GoalORM,
    "goal_root_tasks": GoalRootTaskORM,
    "dependencies": DependencyORM,
    "calendar_events": CalendarEventORM,
    "constraints": ConstraintORM,
    "plans": PlanORM,
    "schedule_blocks": ScheduleBlockORM,
    "observations": ObservationORM,
}


def _validate_state_id(state_id: str) -> None:
    if state_id is None:
        raise TypeError("Planner state ID cannot be None")
    if not isinstance(state_id, str) or not state_id:
        raise ValueError("Planner state ID must be a non-empty string")


def _validate_row_ownership(rows: dict[str, list[object]], state_id: str) -> None:
    for table_name, row_group in rows.items():
        for row in row_group:
            row_state_id = row.id if isinstance(row, PlannerStateORM) else row.state_id
            if row_state_id != state_id:
                raise ValueError(
                    f"ORM row for {table_name} belongs to state {row_state_id!r}, "
                    f"expected {state_id!r}"
                )


def _expunge_state_rows(session: Session, state_id: str) -> None:
    """Detach only rows for the replaced aggregate from this session identity map."""
    for instance in list(session.identity_map.values()):
        instance_state_id = (
            instance.id
            if isinstance(instance, PlannerStateORM)
            else getattr(instance, "state_id", None)
        )
        if instance_state_id == state_id:
            session.expunge(instance)


def _preserve_matching_constraint_ids(snapshot, previous_rows: list[ConstraintORM]) -> None:
    """Retain UUIDs for unchanged constraints when updating a domain snapshot.

    Constraint has no domain identity, so only an exact value match can safely
    carry an old persistence UUID forward. New or changed values retain their
    newly generated record IDs. Thus unchanged values may retain an ID, while
    changed values cannot be proven to represent the same constraint object.
    """
    previous_by_value: dict[tuple[object, ...], list[ConstraintORM]] = {}
    for row in previous_rows:
        previous_by_value.setdefault(_constraint_value(row), []).append(row)

    updated: dict[str, ConstraintRecord] = {}
    ordered_ids: list[str] = []
    for record in snapshot.constraints.values():
        matches = previous_by_value.get(_constraint_value(record))
        if matches:
            record = replace(record, constraint_id=matches.pop(0).constraint_id)
        key = str(record.constraint_id)
        updated[key] = record
        ordered_ids.append(key)
    snapshot.constraints = updated
    snapshot.planner_state_record.constraint_ids = ordered_ids
    snapshot.validate()


def _constraint_value(item) -> tuple[object, ...]:
    if isinstance(item, ConstraintORM):
        return (
            item.type,
            item.start_timestamp_microseconds,
            item.end_timestamp_microseconds,
            item.description,
        )
    return (
        item.type,
        item.rule_information_start_timestamp_microseconds,
        item.rule_information_end_timestamp_microseconds,
        item.description,
    )

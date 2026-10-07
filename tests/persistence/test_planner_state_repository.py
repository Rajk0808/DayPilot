from datetime import datetime, timedelta, timezone

import pytest

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
from daypilot.persistence.aggregate.planner_state import PersistedPlannerState
from daypilot.persistence.exceptions import EntityNotFoundError, PersistenceError
from daypilot.persistence.repositories.planner_state_repository import (
    InMemoryPlannerStateRepository,
    PlannerStateRepository,
)


def empty_state():
    return PlannerState([], [], DependencyGraph(), [], [], None, [])


def complete_state():
    start = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
    first = Task(
        "T1", "Prepare", scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1),
    )
    second = Task(
        "T2", "Review", scheduling_status=SchedulingStatus.SCHEDULED,
        estimated_duration=timedelta(hours=1),
    )
    graph = DependencyGraph()
    graph.register_task(first)
    graph.register_task(second)
    graph.add_dependency(second, first)
    goal = Goal("G1", "Complete work", root_tasks=[first, second])
    first_block = ScheduleBlock(first, start, start + timedelta(hours=1))
    second_block = ScheduleBlock(
        second, start + timedelta(hours=1), start + timedelta(hours=2)
    )
    plan = Plan("P1", start, timedelta(hours=3), [first_block, second_block], {"source": "test"})
    observation = Observation(
        first,
        first_block,
        start + timedelta(minutes=5),
        start + timedelta(minutes=20),
        ObservationOutcome.PARTIALLY_COMPLETED,
        {"note": "started"},
    )
    event = CalendarEvent(
        "E1", "Meeting", start + timedelta(hours=2), start + timedelta(hours=2, minutes=30)
    )
    constraint = Constraint(
        ConstraintType.HARD_CONSTRAINT,
        TimeWindow(start, start + timedelta(hours=3)),
        "Work window",
    )
    return PlannerState(
        [goal], [first, second], graph, [event], [constraint], plan, [observation]
    )


def test_repository_contract_is_separate_from_in_memory_adapter():
    repository = InMemoryPlannerStateRepository()

    assert isinstance(repository, PlannerStateRepository)
    assert issubclass(EntityNotFoundError, PersistenceError)


def test_save_stores_snapshot_and_returns_stable_id():
    repository = InMemoryPlannerStateRepository()

    state_id = repository.save(empty_state())

    assert repository.exists(state_id)
    assert isinstance(repository._planner_states[state_id], PersistedPlannerState)
    assert repository._planner_states[state_id].state_id == state_id
    assert repository._planner_states[state_id].version == 1


def test_get_reconstructs_a_fresh_complete_domain_aggregate_with_shared_identity():
    repository = InMemoryPlannerStateRepository()
    original = complete_state()
    state_id = repository.save(original)

    loaded = repository.get(state_id)

    assert loaded is not original
    assert [task.id for task in loaded.tasks] == ["T1", "T2"]
    assert loaded.goals[0].root_tasks[0] is loaded.tasks[0]
    assert loaded.goals[0].root_tasks[1] is loaded.tasks[1]
    assert loaded.dependency_graph.tasks["T1"] is loaded.tasks[0]
    assert loaded.dependency_graph.tasks["T2"] is loaded.tasks[1]
    assert loaded.dependency_graph.has_dependency(loaded.tasks[1], loaded.tasks[0])
    assert loaded.current_plan is not None
    assert loaded.current_plan.id == "P1"
    assert loaded.current_plan.schedule_blocks[0] is loaded.observations[0].scheduled_block
    assert loaded.observations[0].task is loaded.tasks[0]
    assert loaded.calendar_events[0].id == "E1"
    assert loaded.constraints[0].description == "Work window"


def test_save_with_existing_id_replaces_snapshot_and_increments_version():
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(empty_state())
    updated = empty_state()

    assert repository.save(updated, state_id=state_id) == state_id
    assert repository._planner_states[state_id].version == 2
    repository.save(empty_state(), state_id=state_id)
    assert repository._planner_states[state_id].version == 3
    assert repository.get(state_id) is not updated


def test_save_with_unknown_explicit_id_raises_not_found():
    with pytest.raises(EntityNotFoundError):
        InMemoryPlannerStateRepository().save(empty_state(), state_id="missing")


def test_saving_same_state_without_id_creates_independent_snapshots():
    repository = InMemoryPlannerStateRepository()
    state = empty_state()

    first_id = repository.save(state)
    second_id = repository.save(state)

    assert first_id != second_id
    assert repository.get(first_id) is not state
    assert repository.get(second_id) is not state
    assert repository._planner_states[first_id] is not repository._planner_states[second_id]


def test_each_get_reconstructs_a_new_object_and_loaded_mutation_is_not_persisted():
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(complete_state())
    first = repository.get(state_id)
    first.tasks[0].title = "Changed after load"

    second = repository.get(state_id)

    assert second is not first
    assert second.tasks[0].title == "Prepare"


def test_mutating_input_after_save_does_not_change_stored_snapshot():
    repository = InMemoryPlannerStateRepository()
    state = complete_state()
    state_id = repository.save(state)
    state.tasks[0].title = "Changed after save"

    assert repository.get(state_id).tasks[0].title == "Prepare"
    assert repository._planner_states[state_id].tasks["T1"].title == "Prepare"


def test_get_and_delete_missing_state_raise_repository_error():
    repository = InMemoryPlannerStateRepository()

    with pytest.raises(EntityNotFoundError):
        repository.get("missing")
    with pytest.raises(EntityNotFoundError):
        repository.delete("missing")


def test_exists_and_delete_cover_existing_and_missing_states():
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(empty_state())

    assert repository.exists(state_id)
    repository.delete(state_id)
    assert not repository.exists(state_id)
    with pytest.raises(EntityNotFoundError):
        repository.get(state_id)


@pytest.mark.parametrize("invalid", [None, object()])
def test_save_rejects_invalid_aggregate_with_type_error(invalid):
    with pytest.raises(TypeError):
        InMemoryPlannerStateRepository().save(invalid)


def test_save_rejects_mutated_invalid_planner_state():
    state = complete_state()
    state.tasks[0].children.append(state.tasks[1])

    with pytest.raises(ValueError):
        InMemoryPlannerStateRepository().save(state)

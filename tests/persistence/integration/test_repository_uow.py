import pytest

from daypilot.persistence.repositories.planner_state_repository import (
    InMemoryPlannerStateRepository,
)
from daypilot.persistence.unit_of_works.planner_state import InMemoryPlannerStateUnitOfWork


def test_uow_commit_publishes_complete_aggregate_change(complete_planner_state):
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(complete_planner_state)

    with InMemoryPlannerStateUnitOfWork(repository) as uow:
        changed = uow.planner_states.get(state_id)
        changed.tasks[0].title = "Committed title"
        uow.planner_states.save(changed, state_id=state_id)
        assert repository.get(state_id).tasks[0].title == "Prepare"

    assert repository.get(state_id).tasks[0].title == "Committed title"
    assert repository._planner_states[state_id].version == 2


def test_uow_rollback_keeps_old_aggregate_after_staged_update(complete_planner_state):
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(complete_planner_state)
    uow = InMemoryPlannerStateUnitOfWork(repository)

    with uow:
        changed = uow.planner_states.get(state_id)
        changed.tasks[0].title = "Rolled back title"
        uow.planner_states.save(changed, state_id=state_id)
        uow.rollback()

    assert repository.get(state_id).tasks[0].title == "Prepare"
    assert repository._planner_states[state_id].version == 1


def test_exception_in_uow_rolls_back_complete_aggregate(complete_planner_state):
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(complete_planner_state)

    with pytest.raises(RuntimeError, match="replanning failed"):
        with InMemoryPlannerStateUnitOfWork(repository) as uow:
            changed = uow.planner_states.get(state_id)
            changed.tasks[0].title = "Uncommitted title"
            uow.planner_states.save(changed, state_id=state_id)
            raise RuntimeError("replanning failed")

    loaded = repository.get(state_id)
    assert loaded.tasks[0].title == "Prepare"
    assert loaded.current_plan is not None
    assert loaded.current_plan.id == "P1"
    assert repository._planner_states[state_id].version == 1

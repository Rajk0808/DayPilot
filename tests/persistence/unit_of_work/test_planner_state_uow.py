import pytest

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.planner import PlannerState
from daypilot.domain.task import Task
from daypilot.persistence.repositories.planner_state_repository import (
    InMemoryPlannerStateRepository,
)
from daypilot.persistence.unit_of_works.planner_state import (
    InMemoryPlannerStateUnitOfWork,
    PlannerStateUnitOfWork,
)


def state_with_title(title):
    task = Task("task-1", title)
    graph = DependencyGraph()
    graph.register_task(task)
    return PlannerState([], [task], graph, [], [], None, [])


def test_uow_contract_and_enter_begin_transactional_working_copy():
    repository = InMemoryPlannerStateRepository()
    uow = InMemoryPlannerStateUnitOfWork(repository)
    assert isinstance(uow, PlannerStateUnitOfWork)

    with pytest.raises(RuntimeError, match="not active"):
        uow.planner_states.exists("unused")

    with uow as active:
        assert active is uow
        assert uow.is_active
        new_id = uow.planner_states.save(state_with_title("staged"))
        assert uow.planner_states.exists(new_id)
        assert not repository.exists(new_id)

    assert repository.exists(new_id)
    assert uow.lifecycle_state == "committed"


def test_successful_context_exit_commits_staged_changes():
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(state_with_title("before"))

    with InMemoryPlannerStateUnitOfWork(repository) as uow:
        state = uow.planner_states.get(state_id)
        state.tasks[0].title = "after"
        uow.planner_states.save(state, state_id=state_id)
        assert repository.get(state_id).tasks[0].title == "before"

    assert repository.get(state_id).tasks[0].title == "after"
    assert repository._planner_states[state_id].version == 2


def test_exception_rolls_back_and_preserves_previously_committed_state():
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(state_with_title("committed"))

    with pytest.raises(RuntimeError, match="abort work"):
        with InMemoryPlannerStateUnitOfWork(repository) as uow:
            state = uow.planner_states.get(state_id)
            state.tasks[0].title = "uncommitted"
            uow.planner_states.save(state, state_id=state_id)
            raise RuntimeError("abort work")

    assert repository.get(state_id).tasks[0].title == "committed"
    assert repository._planner_states[state_id].version == 1


def test_changes_inside_failed_uow_are_invisible_afterward():
    repository = InMemoryPlannerStateRepository()
    uow = InMemoryPlannerStateUnitOfWork(repository)

    with pytest.raises(ValueError):
        with uow:
            staged_id = uow.planner_states.save(state_with_title("temporary"))
            raise ValueError("failure")

    assert not repository.exists(staged_id)
    assert uow.lifecycle_state == "rolled_back"


def test_explicit_rollback_discards_changes_and_closes_uow():
    repository = InMemoryPlannerStateRepository()
    uow = InMemoryPlannerStateUnitOfWork(repository)
    uow.begin()
    staged_id = uow.planner_states.save(state_with_title("temporary"))

    uow.rollback()

    assert not repository.exists(staged_id)
    assert uow.lifecycle_state == "rolled_back"
    with pytest.raises(RuntimeError, match="not active"):
        uow.planner_states.exists(staged_id)


def test_nested_and_repeated_lifecycle_use_is_rejected():
    repository = InMemoryPlannerStateRepository()
    uow = InMemoryPlannerStateUnitOfWork(repository)

    with uow:
        with pytest.raises(RuntimeError, match="Cannot begin"):
            uow.__enter__()

    with pytest.raises(RuntimeError, match="Cannot begin"):
        uow.__enter__()


def test_cannot_commit_after_rollback_or_rollback_after_commit():
    rolled_back = InMemoryPlannerStateUnitOfWork(InMemoryPlannerStateRepository())
    rolled_back.begin()
    rolled_back.rollback()
    with pytest.raises(RuntimeError, match="not active"):
        rolled_back.commit()

    committed = InMemoryPlannerStateUnitOfWork(InMemoryPlannerStateRepository())
    committed.begin()
    committed.commit()
    with pytest.raises(RuntimeError, match="not active"):
        committed.rollback()


def test_repository_facade_cannot_be_used_after_commit_or_rollback():
    committed = InMemoryPlannerStateUnitOfWork(InMemoryPlannerStateRepository())
    committed.begin()
    committed.commit()
    with pytest.raises(RuntimeError, match="not active"):
        committed.planner_states.save(state_with_title("closed"))

    rolled_back = InMemoryPlannerStateUnitOfWork(InMemoryPlannerStateRepository())
    rolled_back.begin()
    rolled_back.rollback()
    with pytest.raises(RuntimeError, match="not active"):
        rolled_back.planner_states.get("missing")

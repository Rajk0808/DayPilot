import pytest

from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.goal import Goal
from daypilot.domain.planner import PlannerState
from daypilot.domain.task import Task
from daypilot.persistence.repositories.planner_state_repository import (
    InMemoryPlannerStateRepository,
)


def test_repository_round_trip_preserves_complete_planner_graph(complete_planner_state):
    repository = InMemoryPlannerStateRepository()
    original = complete_planner_state

    state_id = repository.save(original)
    loaded = repository.get(state_id)

    tasks = {task.id: task for task in loaded.tasks}
    assert set(tasks) == {task.id for task in original.tasks}
    assert [goal.id for goal in loaded.goals] == ["G1"]
    assert loaded.goals[0].root_tasks[0] is tasks["T1"]
    assert loaded.goals[0].root_tasks[1] is tasks["T3"]

    assert tasks["T2"].parent is tasks["T1"]
    assert tasks["T2"] in tasks["T1"].children
    assert loaded.dependency_graph.tasks["T1"] is tasks["T1"]
    assert loaded.dependency_graph.tasks["T2"] is tasks["T2"]
    assert loaded.dependency_graph.tasks["T3"] is tasks["T3"]
    assert loaded.dependency_graph.has_dependency(tasks["T3"], tasks["T2"])

    assert loaded.current_plan is not None
    assert loaded.current_plan.id == "P1"
    assert loaded.current_plan.schedule_blocks[0].task is tasks["T2"]
    assert loaded.current_plan.schedule_blocks[1].task is tasks["T3"]
    assert loaded.observations[0].task is tasks["T2"]
    assert loaded.observations[0].scheduled_block is loaded.current_plan.schedule_blocks[0]
    assert loaded.observations[0].actual_start == original.observations[0].actual_start
    assert loaded.observations[0].actual_end == original.observations[0].actual_end
    assert loaded.observations[0].outcome is original.observations[0].outcome
    assert loaded.observations[0].metadata == original.observations[0].metadata
    assert loaded.calendar_events[0].id == "E1"
    assert loaded.constraints[0].description == "Available work window"


def test_none_current_plan_survives_repository_round_trip():
    task = Task("T1", "Unscheduled")
    graph = DependencyGraph()
    graph.register_task(task)
    state = PlannerState(
        goals=[Goal("G1", "Goal", root_tasks=[task])],
        tasks=[task],
        dependency_graph=graph,
        calendar_events=[],
        constraints=[],
        current_plan=None,
        observations=[],
    )

    loaded = InMemoryPlannerStateRepository()
    state_id = loaded.save(state)

    assert loaded.get(state_id).current_plan is None


def test_loaded_aggregate_is_isolated_from_persisted_snapshot(complete_planner_state):
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(complete_planner_state)
    first_load = repository.get(state_id)
    first_load.tasks[0].title = "Changed only in this load"

    second_load = repository.get(state_id)

    assert second_load.tasks[0].title == "Prepare"
    assert second_load is not first_load


def test_update_round_trip_replaces_state_and_increments_version(complete_planner_state):
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(complete_planner_state)
    updated = repository.get(state_id)
    updated.tasks[0].title = "Updated parent task"

    assert repository.save(updated, state_id=state_id) == state_id
    reloaded = repository.get(state_id)

    assert reloaded.tasks[0].title == "Updated parent task"
    assert repository._planner_states[state_id].version == 2


def test_invalid_update_does_not_replace_previous_snapshot(complete_planner_state):
    repository = InMemoryPlannerStateRepository()
    state_id = repository.save(complete_planner_state)
    invalid_update = repository.get(state_id)
    invalid_update.tasks[0].children.append(invalid_update.tasks[2])

    with pytest.raises(ValueError):
        repository.save(invalid_update, state_id=state_id)

    persisted = repository.get(state_id)
    assert persisted.tasks[0].title == "Prepare"
    assert repository._planner_states[state_id].version == 1

import pytest

from daypilot.persistence.aggregate.planner_state import (
    from_persisted_planner_state,
    to_persisted_planner_state,
)
from daypilot.persistence.mappers.planner_state import dependency_id
from daypilot.persistence.mappers.schedule_block import ScheduleBlockMappingContext
from daypilot.persistence.mappers.task import TaskMappingContext


def snapshot_of(state):
    return to_persisted_planner_state(state, "state-corrupt-test")


def test_goal_reference_to_unknown_task_is_rejected(complete_planner_state):
    snapshot = snapshot_of(complete_planner_state)
    snapshot.goals["G1"].root_task_ids.append("UNKNOWN")

    with pytest.raises(ValueError, match="outside the aggregate"):
        from_persisted_planner_state(snapshot)


def test_task_reference_to_unknown_parent_is_rejected(complete_planner_state):
    snapshot = snapshot_of(complete_planner_state)
    snapshot.tasks["T2"].parent_id = "UNKNOWN"

    with pytest.raises(ValueError, match="outside the aggregate"):
        from_persisted_planner_state(snapshot)


def test_dependency_reference_to_unknown_task_is_rejected(complete_planner_state):
    snapshot = snapshot_of(complete_planner_state)
    dependency = next(iter(snapshot.dependencies.values()))
    dependency.prerequisite_task_id = "UNKNOWN"
    new_key = dependency_id(dependency)
    snapshot.dependencies = {new_key: dependency}
    snapshot.planner_state_record.dependency_ids = [new_key]

    with pytest.raises(ValueError, match="outside the aggregate"):
        from_persisted_planner_state(snapshot)


def test_plan_reference_to_unknown_schedule_block_is_rejected(complete_planner_state):
    snapshot = snapshot_of(complete_planner_state)
    snapshot.plans["P1"].schedule_block_ids[0] = "UNKNOWN"

    with pytest.raises(ValueError, match="Schedule block records do not match"):
        from_persisted_planner_state(snapshot)


def test_observation_reference_to_unknown_schedule_block_is_rejected(complete_planner_state):
    snapshot = snapshot_of(complete_planner_state)
    observation = next(iter(snapshot.observations.values()))
    observation.schedule_block_id = "UNKNOWN"

    with pytest.raises(ValueError, match="Schedule block records do not match"):
        from_persisted_planner_state(snapshot)


def test_duplicate_entity_ids_are_rejected(complete_planner_state):
    snapshot = snapshot_of(complete_planner_state)
    snapshot.planner_state_record.task_ids.append("T1")

    with pytest.raises(ValueError, match="duplicate task IDs"):
        from_persisted_planner_state(snapshot)


def test_repeated_schedule_block_record_resolves_to_same_object(complete_planner_state):
    snapshot = snapshot_of(complete_planner_state)
    task_context = TaskMappingContext()
    task_context.reconstruct(list(snapshot.tasks.values()))
    block_context = ScheduleBlockMappingContext()
    record = next(iter(snapshot.schedule_blocks.values()))
    first = block_context.resolve(record, task_context)
    second = block_context.resolve(record, task_context)

    assert second is first

from pathlib import Path

import pytest

from daypilot.persistence.orm.goal_root_task import GoalRootTaskORM
from daypilot.persistence.orm_mappers.goal_root_task import from_orm, to_orm


def test_to_orm_maps_ids_and_takes_state_id_externally():
    orm = to_orm(
        state_id="state-1",
        goal_id="goal-1",
        task_id="task-1",
    )

    assert isinstance(orm, GoalRootTaskORM)
    assert orm.state_id == "state-1"
    assert orm.goal_id == "goal-1"
    assert orm.task_id == "task-1"


def test_from_orm_returns_logical_association_ids():
    orm = to_orm(
        state_id="state-1",
        goal_id="goal-1",
        task_id="task-1",
    )

    assert from_orm(orm) == ("goal-1", "task-1")


def test_to_orm_rejects_invalid_state_id():
    with pytest.raises(ValueError, match="state_id"):
        to_orm(
            state_id="",
            goal_id="goal-1",
            task_id="task-1",
        )


def test_to_orm_rejects_invalid_goal_id():
    with pytest.raises(ValueError, match="goal_id"):
        to_orm(
            state_id="state-1",
            goal_id="",
            task_id="task-1",
        )


def test_to_orm_rejects_invalid_task_id():
    with pytest.raises(ValueError, match="task_id"):
        to_orm(
            state_id="state-1",
            goal_id="goal-1",
            task_id="",
        )


def test_from_orm_rejects_wrong_type():
    with pytest.raises(TypeError, match="GoalRootTaskORM"):
        from_orm(object())


def test_mapper_does_not_import_domain_or_application_modules():
    source = (
        Path(__file__).parents[3]
        / "src/daypilot/persistence/orm_mappers/goal_root_task.py"
    )
    contents = source.read_text(encoding="utf-8")

    assert "daypilot.domain" not in contents
    assert "daypilot.application" not in contents

from pathlib import Path

import pytest

from daypilot.persistence.orm.dependency import DependencyORM
from daypilot.persistence.orm_mappers.dependency import from_orm, to_orm


def test_to_orm_maps_ids_and_external_state_id():
    orm = to_orm(
        state_id="state-1",
        dependent_task_id="task-b",
        prerequisite_task_id="task-a",
    )

    assert isinstance(orm, DependencyORM)
    assert orm.state_id == "state-1"
    assert orm.dependent_task_id == "task-b"
    assert orm.prerequisite_task_id == "task-a"


@pytest.mark.parametrize(
    ("field", "values"),
    [
        ("state_id", {"state_id": "", "dependent_task_id": "task-b", "prerequisite_task_id": "task-a"}),
        ("dependent_task_id", {"state_id": "state-1", "dependent_task_id": "", "prerequisite_task_id": "task-a"}),
        ("prerequisite_task_id", {"state_id": "state-1", "dependent_task_id": "task-b", "prerequisite_task_id": ""}),
    ],
)
def test_to_orm_rejects_empty_ids(field, values):
    with pytest.raises(ValueError, match=field):
        to_orm(**values)


def test_from_orm_returns_logical_task_ids_only():
    orm = to_orm("state-1", "task-b", "task-a")

    assert from_orm(orm) == ("task-b", "task-a")


def test_from_orm_rejects_wrong_type():
    with pytest.raises(TypeError, match="DependencyORM"):
        from_orm(object())


def test_mapper_does_not_import_domain_or_application_modules():
    source = Path(__file__).parents[3] / "src/daypilot/persistence/orm_mappers/dependency.py"
    contents = source.read_text(encoding="utf-8")

    assert "daypilot.domain" not in contents
    assert "daypilot.application" not in contents

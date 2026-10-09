"""Mapping for the task dependency ORM row."""

from daypilot.persistence.orm.dependency import DependencyORM


def to_orm(
    state_id: str,
    dependent_task_id: str,
    prerequisite_task_id: str,
) -> DependencyORM:
    """Create a dependency row from logical IDs and aggregate context."""
    for name, value in (
        ("state_id", state_id),
        ("dependent_task_id", dependent_task_id),
        ("prerequisite_task_id", prerequisite_task_id),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")

    return DependencyORM(
        state_id=state_id,
        dependent_task_id=dependent_task_id,
        prerequisite_task_id=prerequisite_task_id,
    )


def from_orm(orm: DependencyORM) -> tuple[str, str]:
    """Extract the logical dependent/prerequisite task IDs from a row."""
    if not isinstance(orm, DependencyORM):
        raise TypeError("orm must be a DependencyORM")
    return orm.dependent_task_id, orm.prerequisite_task_id

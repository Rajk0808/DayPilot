"""Mapping for the goal-to-root-task ORM association row."""

from daypilot.persistence.orm.goal_root_task import GoalRootTaskORM


def to_orm(state_id: str, goal_id: str, task_id: str) -> GoalRootTaskORM:
    """Create an association row from logical IDs and its owning state ID."""
    for name, value in (
        ("state_id", state_id),
        ("goal_id", goal_id),
        ("task_id", task_id),
    ):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")

    return GoalRootTaskORM(
        state_id=state_id,
        goal_id=goal_id,
        task_id=task_id,
    )


def from_orm(orm: GoalRootTaskORM) -> tuple[str, str]:
    """Extract the logical goal/task association from an ORM row."""
    if not isinstance(orm, GoalRootTaskORM):
        raise TypeError("orm must be a GoalRootTaskORM")
    return orm.goal_id, orm.task_id

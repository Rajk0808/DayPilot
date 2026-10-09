"""ORM mapping for the goal-to-root-task association."""

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from daypilot.persistence.orm.base import Base


class GoalRootTaskORM(Base):
    __tablename__ = "goal_root_tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["state_id", "goal_id"],
            ["goals.state_id", "goals.id"],
            name="fk_goal_root_tasks_goal_same_state",
        ),
        ForeignKeyConstraint(
            ["state_id", "task_id"],
            ["tasks.state_id", "tasks.id"],
            name="fk_goal_root_tasks_task_same_state",
        ),
        UniqueConstraint("state_id", "task_id", name="uq_goal_root_tasks_task_per_state"),
    )

    state_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("planner_states.id", ondelete="CASCADE"),
        primary_key=True,
    )
    goal_id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(Text, primary_key=True)

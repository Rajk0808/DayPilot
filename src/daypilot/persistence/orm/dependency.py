"""ORM mapping for task dependency edges."""

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Text
from sqlalchemy.orm import Mapped, mapped_column

from daypilot.persistence.orm.base import Base


class DependencyORM(Base):
    __tablename__ = "dependencies"
    __table_args__ = (
        ForeignKeyConstraint(
            ["state_id", "dependent_task_id"],
            ["tasks.state_id", "tasks.id"],
            name="fk_dependencies_dependent_same_state",
        ),
        ForeignKeyConstraint(
            ["state_id", "prerequisite_task_id"],
            ["tasks.state_id", "tasks.id"],
            name="fk_dependencies_prerequisite_same_state",
        ),
        CheckConstraint(
            "dependent_task_id <> prerequisite_task_id",
            name="ck_dependencies_not_self_referential",
        ),
    )

    state_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("planner_states.id", ondelete="CASCADE"),
        primary_key=True,
    )
    dependent_task_id: Mapped[str] = mapped_column(Text, primary_key=True)
    prerequisite_task_id: Mapped[str] = mapped_column(Text, primary_key=True)

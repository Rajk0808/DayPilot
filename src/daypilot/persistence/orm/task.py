"""ORM mapping for aggregate-scoped tasks and their parent foreign key."""

from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    JSON,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from daypilot.persistence.orm.base import Base


class TaskORM(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["state_id", "parent_task_id"],
            ["tasks.state_id", "tasks.id"],
            name="fk_tasks_parent_same_state",
        ),
        CheckConstraint(
            "parent_task_id IS NULL OR parent_task_id <> id",
            name="ck_tasks_not_own_parent",
        ),
        CheckConstraint(
            "estimated_duration_microseconds >= 0",
            name="ck_tasks_duration_nonnegative",
        ),
    )

    state_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("planner_states.id", ondelete="CASCADE"),
        primary_key=True,
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    scheduling_status: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_duration_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deadline_timestamp_microseconds: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default=text("'{}'"),
    )
    parent_task_id: Mapped[str | None] = mapped_column(Text, nullable=True)

"""ORM mapping for current-plan and observation-retained schedule blocks."""

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from daypilot.persistence.orm.base import Base


class ScheduleBlockORM(Base):
    __tablename__ = "schedule_blocks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["state_id", "task_id"],
            ["tasks.state_id", "tasks.id"],
            name="fk_schedule_blocks_task_same_state",
        ),
        ForeignKeyConstraint(
            ["state_id", "plan_id"],
            ["plans.state_id", "plans.id"],
            name="fk_schedule_blocks_plan_same_state",
        ),
        UniqueConstraint(
            "state_id", "task_id", "id", name="uq_schedule_blocks_state_task_id"
        ),
        CheckConstraint(
            "start_timestamp_microseconds < end_timestamp_microseconds",
            name="ck_schedule_blocks_valid_interval",
        ),
    )

    state_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("planner_states.id", ondelete="CASCADE"),
        primary_key=True,
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(Text, nullable=False)
    plan_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    start_timestamp_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_timestamp_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)

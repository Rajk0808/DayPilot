"""ORM mapping for task observations and their scheduled blocks."""

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


class ObservationORM(Base):
    __tablename__ = "observations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["state_id", "task_id", "schedule_block_id"],
            ["schedule_blocks.state_id", "schedule_blocks.task_id", "schedule_blocks.id"],
            name="fk_observations_schedule_block_same_task_and_state",
        ),
        CheckConstraint(
            "actual_start_timestamp_microseconds < actual_end_timestamp_microseconds",
            name="ck_observations_valid_interval",
        ),
    )

    state_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("planner_states.id", ondelete="CASCADE"),
        primary_key=True,
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    task_id: Mapped[str] = mapped_column(Text, nullable=False)
    schedule_block_id: Mapped[str] = mapped_column(Text, nullable=False)
    actual_start_timestamp_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    actual_end_timestamp_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default=text("'{}'"),
    )

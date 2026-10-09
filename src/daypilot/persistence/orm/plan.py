"""ORM mapping for the single current plan per planner state."""

from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, JSON, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from daypilot.persistence.orm.base import Base


class PlanORM(Base):
    __tablename__ = "plans"
    __table_args__ = (
        UniqueConstraint("state_id", name="uq_plans_one_per_state"),
        CheckConstraint(
            "planning_horizon_microseconds > 0",
            name="ck_plans_horizon_positive",
        ),
        # The primary key is composite; state_id is already the foreign key.
    )

    state_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("planner_states.id", ondelete="CASCADE"),
        primary_key=True,
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    date_timestamp_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    planning_horizon_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default=text("'{}'"),
    )

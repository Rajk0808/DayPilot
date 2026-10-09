"""ORM mapping for calendar events."""

from typing import Any

from sqlalchemy import BigInteger, ForeignKey, JSON, Text, CheckConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from daypilot.persistence.orm.base import Base


class CalendarEventORM(Base):
    __tablename__ = "calendar_events"
    __table_args__ = (
        CheckConstraint(
            "start_timestamp_microseconds < end_timestamp_microseconds",
            name="ck_calendar_events_valid_interval",
        ),
    )

    state_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("planner_states.id", ondelete="CASCADE"),
        primary_key=True,
    )
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    start_timestamp_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_timestamp_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB().with_variant(JSON(), "sqlite"),
        nullable=False,
        server_default=text("'{}'"),
    )

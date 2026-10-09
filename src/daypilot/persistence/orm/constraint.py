"""ORM mapping for persistence-identified constraints."""

from uuid import UUID

from sqlalchemy import BigInteger, ForeignKey, Text, CheckConstraint, text
from sqlalchemy.dialects.postgresql import UUID as PostgreSQLUUID
from sqlalchemy.orm import Mapped, mapped_column

from daypilot.persistence.orm.base import Base


class ConstraintORM(Base):
    __tablename__ = "constraints"
    __table_args__ = (
        CheckConstraint(
            "start_timestamp_microseconds < end_timestamp_microseconds",
            name="ck_constraints_valid_interval",
        ),
    )

    state_id: Mapped[str] = mapped_column(
        Text,
        ForeignKey("planner_states.id", ondelete="CASCADE"),
        primary_key=True,
    )
    constraint_id: Mapped[UUID] = mapped_column(
        PostgreSQLUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    start_timestamp_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_timestamp_microseconds: Mapped[int] = mapped_column(BigInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

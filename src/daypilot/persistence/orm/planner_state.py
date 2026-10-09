"""ORM mapping for the planner state aggregate root."""

from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from daypilot.persistence.orm.base import Base


class PlannerStateORM(Base):
    __tablename__ = "planner_states"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_planner_states_version_positive"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

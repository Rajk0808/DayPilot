"""Task API DTOs, independent of the task domain entity."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TaskCreate(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    priority: Literal["low", "medium", "high", "critical"] = "medium"
    estimated_duration_microseconds: int = Field(default=3_600_000_000, gt=0)
    deadline: datetime | None = None
    status: Literal["not_started", "in_progress", "completed", "blocked", "cancelled"] = "not_started"

    @field_validator("deadline")
    @classmethod
    def deadline_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("deadline must include a timezone")
        return value


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    priority: Literal["low", "medium", "high", "critical"] | None = None
    estimated_duration_microseconds: int | None = Field(default=None, gt=0)
    deadline: datetime | None = None
    status: Literal["not_started", "in_progress", "completed", "blocked", "cancelled"] | None = None

    @field_validator("deadline")
    @classmethod
    def deadline_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("deadline must include a timezone")
        return value


class TaskResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    status: str
    scheduling_status: str
    priority: str | None
    estimated_duration_microseconds: int
    deadline: datetime | None
    parent_id: str | None
    children_ids: list[str]
    metadata: dict[str, object]

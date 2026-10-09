"""Goal API DTOs, independent of the goal domain entity."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class GoalCreate(BaseModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = ""
    deadline: datetime | None = None
    status: str | None = None
    root_task_ids: list[str] = Field(default_factory=list)

    @field_validator("deadline")
    @classmethod
    def deadline_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("deadline must include a timezone")
        return value


class GoalUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    deadline: datetime | None = None
    status: str | None = None

    @field_validator("deadline")
    @classmethod
    def deadline_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("deadline must include a timezone")
        return value


class GoalResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    description: str
    deadline: datetime | None
    status: str | None
    root_task_ids: list[str]

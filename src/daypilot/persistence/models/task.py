from dataclasses import dataclass
from typing import Any


@dataclass
class TaskRecord:
    """Persistence representation of a DayPilot task."""

    id: str
    title: str
    description: str
    status: str
    scheduling_status: str
    priority: str | None
    estimated_duration_microseconds: int
    deadline_timestamp_microseconds: int | None
    metadata: dict[str, Any]
    parent_id: str | None
    children_ids: list[str]

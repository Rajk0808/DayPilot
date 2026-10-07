from dataclasses import dataclass


@dataclass
class GoalRecord:
    id: str
    title: str
    description: str
    deadline_timestamp_microseconds: int | None
    status: str
    root_task_ids: list[str]

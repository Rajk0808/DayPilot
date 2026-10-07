
from dataclasses import dataclass
@dataclass
class ScheduleBlockRecord:
    id: str
    task_id: str
    start_timestamp_microseconds: int
    end_timestamp_microseconds: int
    status: str | None = None

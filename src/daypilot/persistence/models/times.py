
from dataclasses import dataclass
from typing import Any

@dataclass
class CalendarEventRecord:
    id: str
    title: str
    start_timestamp_microseconds: int
    end_timestamp_microseconds: int
    metadata: dict[str, Any]

from dataclasses import dataclass
from typing import Any


@dataclass
class ObservationRecord:
    id: str
    task_id: str
    schedule_block_id: str
    actual_start_timestamp_microseconds: int
    actual_end_timestamp_microseconds: int
    outcome: str
    metadata: dict[str, Any]

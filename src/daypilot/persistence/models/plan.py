from dataclasses import dataclass
from typing import Any


@dataclass
class PlanRecord:
    id: str
    date_timestamp_microseconds: int
    planning_horizon_microseconds: int
    schedule_block_ids: list[str]
    metadata: dict[str, str]

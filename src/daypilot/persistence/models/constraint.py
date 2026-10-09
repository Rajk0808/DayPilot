
from dataclasses import dataclass
from uuid import UUID

@dataclass
class ConstraintRecord:
    constraint_id: UUID
    type: str
    rule_information_start_timestamp_microseconds: int
    rule_information_end_timestamp_microseconds: int
    description: str


from dataclasses import dataclass

@dataclass
class ConstraintRecord:
    type: str
    rule_information_start_timestamp_microseconds: int
    rule_information_end_timestamp_microseconds: int
    description: str

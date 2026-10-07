
from dataclasses import dataclass

@dataclass
class DependencyRecord:
    dependent_task_id: str
    prerequisite_task_id: str

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .task import Task



@dataclass
class Goal:
    id: str
    title: str
    description: str = ""
    deadline: datetime | None = None
    status: object = None
    root_tasks: list[Task] = field(default_factory=list)

    def add_root_task(self, task: Task) -> None:
        if any(existing is task for existing in self.root_tasks):
            raise ValueError("Task is already a root task.")
        if task.parent is not None:
            raise ValueError("Root task must not have a parent.")
        self.root_tasks.append(task)

    def remove_root_task(self, task: Task) -> None:
        for index, existing in enumerate(self.root_tasks):
            if existing is task:
                del self.root_tasks[index]
                task.parent = None
                return
        raise ValueError("Task not found in root tasks.")

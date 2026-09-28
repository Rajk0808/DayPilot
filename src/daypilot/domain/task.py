from __future__ import annotations
from .enums import TaskStatus, Priority
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any


@dataclass(eq=False)
class Task:
    id: str
    title: str
    description: str = ""
    status: TaskStatus | None = None
    priority: Priority | None = None
    parent: Task | None = None
    children: list[Task] = field(default_factory=list)
    estimated_duration: timedelta = timedelta()
    deadline: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def is_atomic(self) -> bool:
        """A task with no children is atomic."""
        return len(self.children) == 0

    def add_child(self, child: Task) -> None:
        """Add a child task to this task."""
        if any(existing is child for existing in self.children):
            raise ValueError("Child task is already a child of this task.")
        if child.parent is not None:
            raise ValueError("Child task must not have a parent.")
        curr = self
        while curr is not None:
            if curr is child:
                raise ValueError("Cannot add a task as a child of its descendant.")
            curr = curr.parent
        child.parent = self
        self.children.append(child)

    def remove_child(self, child: Task) -> None:
        """Remove a child task from this task."""
        for index, existing in enumerate(self.children):
            if existing is child:
                del self.children[index]
                child.parent = None
                return
        raise ValueError("Child task not found.")

    def reparent(self, new_parent: Task | None) -> None:
        """Change the parent of this task."""
        if new_parent is self:
            raise ValueError("A task cannot be its own parent.")
        curr = new_parent
        while curr is not None:
            if curr is self:
                raise ValueError("Cannot reparent to a descendant task.")
            curr = curr.parent
        if self.parent is not None:
            self.parent.remove_child(self)
        self.parent = None
        if new_parent is not None:
            new_parent.add_child(self)
    

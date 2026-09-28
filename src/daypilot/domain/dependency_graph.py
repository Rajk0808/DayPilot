from __future__ import annotations

from .task import Task


class DependencyGraph:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.prerequisites: dict[str, set[str]] = {}
        self.dependents: dict[str, set[str]] = {}

    def register_task(self, task: Task) -> None:
        """Add a task to this graph, keyed by its stable task ID."""
        existing = self.tasks.get(task.id)
        if existing is not None and existing is not task:
            raise ValueError(f"A different task with ID {task.id!r} is already registered.")
        self.tasks[task.id] = task

    def add_dependency(self, dependent: Task, prerequisite: Task) -> None:
        """Record that ``dependent`` requires ``prerequisite`` first."""
        if dependent is prerequisite:
            raise ValueError("A task cannot be dependent on itself.")
        if (self.tasks.get(dependent.id) is not dependent
                or self.tasks.get(prerequisite.id) is not prerequisite):
            raise ValueError("One or both tasks are not registered in this graph.")

        dependent_id = dependent.id
        prerequisite_id = prerequisite.id
        if prerequisite_id in self.prerequisites.get(dependent_id, set()):
            raise ValueError(
                f"{dependent.title} is already dependent on {prerequisite.title}."
            )
        if (self._is_ancestor(dependent, prerequisite)
                or self._is_ancestor(prerequisite, dependent)):
            raise ValueError("A dependency cannot connect tasks in the same task tree.")
        if self._depends_on(prerequisite_id, dependent_id):
            raise ValueError("This dependency would create a cycle.")

        self.prerequisites.setdefault(dependent_id, set()).add(prerequisite_id)
        self.dependents.setdefault(prerequisite_id, set()).add(dependent_id)

    @staticmethod
    def _is_ancestor(ancestor: Task, descendant: Task) -> bool:
        current = descendant.parent
        while current is not None:
            if current is ancestor:
                return True
            current = current.parent
        return False

    def _depends_on(self, task_id: str, target_id: str) -> bool:
        pending = [task_id]
        visited: set[str] = set()
        while pending:
            current = pending.pop()
            if current == target_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            pending.extend(self.prerequisites.get(current, ()))
        return False

    def remove_dependency(self, dependent: Task, prerequisite: Task) -> None:
        dependent_id = dependent.id
        prerequisite_id = prerequisite.id
        if (self.tasks.get(dependent_id) is not dependent
                or self.tasks.get(prerequisite_id) is not prerequisite):
            raise ValueError("One or both tasks are not registered in this graph.")
        if prerequisite_id not in self.prerequisites.get(dependent_id, set()):
            raise ValueError("Dependency does not exist.")

        self.prerequisites[dependent_id].remove(prerequisite_id)
        self.dependents[prerequisite_id].remove(dependent_id)
        if not self.prerequisites[dependent_id]:
            del self.prerequisites[dependent_id]
        if not self.dependents[prerequisite_id]:
            del self.dependents[prerequisite_id]

    def get_prerequisites(self, task: Task) -> list[Task]:
        return [self.tasks[task_id] for task_id in self.prerequisites.get(task.id, ())]

    def get_dependents(self, task: Task) -> list[Task]:
        return [self.tasks[task_id] for task_id in self.dependents.get(task.id, ())]

    def has_dependency(self, dependent: Task, prerequisite: Task) -> bool:
        return prerequisite.id in self.prerequisites.get(dependent.id, set())

    def can_execute(self, task: Task) -> bool:
        if task.id not in self.tasks:
            return False
        
        if not task.is_atomic:
            return False

        if not task.status == "not_started":
            return False

        prereq = self.prerequisites.get(task.id, ())
        for i in prereq:
            if not self.tasks[i].status == "completed":
                return False

        return True

    def get_ready_tasks(self) -> list[Task]:
        return [task for task in self.tasks.values() if self.can_execute(task)]

    def get_execution_order(self) -> list[Task]:
        remaining = {
            task_id: set(self.prerequisites.get(task_id, ()))
            for task_id in self.tasks
        }
        ready = [task_id for task_id, required in remaining.items() if not required]
        order: list[Task] = []

        while ready:
            task_id = ready.pop()
            order.append(self.tasks[task_id])
            for dependent_id in self.dependents.get(task_id, ()):
                remaining[dependent_id].discard(task_id)
                if not remaining[dependent_id]:
                    ready.append(dependent_id)

        if len(order) != len(self.tasks):
            raise ValueError("Dependency graph contains a cycle.")
        return order

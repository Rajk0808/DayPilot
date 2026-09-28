from datetime import timedelta
from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))
from src.daypilot.domain.task import Task


def test_task_without_children_is_atomic():
    task = Task(
        id="task-1",
        title="Study Graphs",
        estimated_duration=timedelta(minutes=60),
    )

    assert task.is_atomic is True


def test_task_with_children_is_composite():
    parent = Task(
        id="task-1",
        title="Study Python",
        estimated_duration=timedelta(minutes=90),
    )
    child = Task(
        id="task-2",
        title="Study OOP",
        estimated_duration=timedelta(minutes=30),
    )

    # Temporary direct setup for the skeleton.
    # Later this should go through parent.add_child(child).
    parent.children.append(child)

    assert parent.is_atomic is False


def test_task_parent_is_optional():
    task = Task(
        id="task-1",
        title="Buy groceries",
        estimated_duration=timedelta(minutes=30),
    )

    assert task.parent is None

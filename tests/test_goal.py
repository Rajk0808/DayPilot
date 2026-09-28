from pathlib import Path
import sys
sys.path.append(str(Path(__file__).parent.parent))
from src.daypilot.domain.goal import Goal

def test_goal_can_start_with_no_root_tasks():
    goal = Goal(
        id="goal-1",
        title="Prepare for Interview",
    )

    assert goal.root_tasks == []


def test_goal_root_tasks_are_a_list():
    goal = Goal(
        id="goal-1",
        title="Prepare for Interview",
    )

    assert isinstance(goal.root_tasks, list)

from datetime import datetime, timedelta, timezone

import pytest

from daypilot.application.goal_service import GoalApplicationService, GoalUpdateRequest
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.goal import Goal
from daypilot.domain.planner import PlannerState
from daypilot.domain.enums import Priority, SchedulingStatus
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task


DATE = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)


def make_state() -> PlannerState:
    return PlannerState([], [], DependencyGraph(), [], [], None, [])


def test_create_goal_validates_and_adds_to_planner_state():
    state = make_state()
    goal = Goal("G", "Goal")

    result = GoalApplicationService().create_goal(goal, state)

    assert result is goal
    assert len(state.goals) == 1
    assert state.goals[0] is goal


def test_remove_goal_validates_and_delegates_to_planner_state():
    state = make_state()
    goal = Goal("G", "Goal")
    state.add_goal(goal)

    result = GoalApplicationService().remove_goal(goal, state)

    assert result is None
    assert state.goals == []


@pytest.mark.parametrize(
    ("method", "goal", "state", "message"),
    [
        ("create_goal", None, make_state(), "Goal cannot be None"),
        ("create_goal", Goal("G", "Goal"), None, "Planner state cannot be None"),
        ("remove_goal", None, make_state(), "Goal cannot be None"),
        ("remove_goal", Goal("G", "Goal"), None, "Planner state cannot be None"),
    ],
)
def test_goal_service_validates_required_inputs(method, goal, state, message):
    with pytest.raises(ValueError, match=message):
        getattr(GoalApplicationService(), method)(goal, state)


def test_create_goal_rejects_same_goal_identity():
    state = make_state()
    goal = Goal("G", "Goal")
    state.add_goal(goal)

    with pytest.raises(ValueError, match="already exists"):
        GoalApplicationService().create_goal(goal, state)


def test_create_goal_rejects_duplicate_goal_id_through_state():
    state = make_state()
    state.add_goal(Goal("G", "Goal"))

    with pytest.raises(ValueError, match="already in the planner state"):
        GoalApplicationService().create_goal(Goal("G", "Lookalike"), state)


def test_remove_goal_requires_exact_goal_identity():
    state = make_state()
    owned = Goal("G", "Goal")
    lookalike = Goal("G", "Goal")
    state.add_goal(owned)

    with pytest.raises(ValueError, match="does not exist"):
        GoalApplicationService().remove_goal(lookalike, state)

    assert state.goals == [owned]
    assert state.goals[0] is owned


def test_change_goal_title_and_description():
    state = make_state()
    goal = Goal("G", "Old title", description="Old description")
    state.add_goal(goal)

    result = GoalApplicationService().change_goal(
        goal,
        state,
        GoalUpdateRequest(title="New title", description="New description"),
    )

    assert result is goal
    assert goal.title == "New title"
    assert goal.description == "New description"


def test_change_goal_deadline_and_status():
    state = make_state()
    goal = Goal("G", "Goal")
    state.add_goal(goal)
    deadline = DATE + timedelta(days=1)

    GoalApplicationService().change_goal(
        goal,
        state,
        GoalUpdateRequest(deadline=deadline, status="active"),
    )

    assert goal.deadline == deadline
    assert goal.status == "active"


def test_change_goal_rejects_empty_update():
    state = make_state()
    goal = Goal("G", "Goal")
    state.add_goal(goal)

    with pytest.raises(ValueError, match="empty"):
        GoalApplicationService().change_goal(goal, state, GoalUpdateRequest())


def test_change_goal_rejects_unknown_or_equal_valued_goal():
    state = make_state()
    owned = Goal("G", "Goal")
    lookalike = Goal("G", "Goal")
    state.add_goal(owned)

    with pytest.raises(ValueError, match="does not exist"):
        GoalApplicationService().change_goal(
            lookalike,
            state,
            GoalUpdateRequest(title="Changed"),
        )


def test_invalid_goal_update_leaves_goal_unchanged():
    state = make_state()
    goal = Goal("G", "Original", description="Description")
    state.add_goal(goal)
    original = (goal.title, goal.description, goal.deadline, goal.status)

    with pytest.raises(ValueError, match="timezone-aware"):
        GoalApplicationService().change_goal(
            goal,
            state,
            GoalUpdateRequest(title="Changed", deadline=datetime(2026, 10, 6, 9)),
        )

    assert (goal.title, goal.description, goal.deadline, goal.status) == original


def test_goal_metadata_update_does_not_change_current_plan():
    task = Task(
        "A",
        "Task",
        priority=Priority.MEDIUM,
        estimated_duration=timedelta(hours=1),
    )
    task.scheduling_status = SchedulingStatus.SCHEDULED
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    plan = Plan("plan", DATE, timedelta(hours=4), [block], {})
    graph = DependencyGraph()
    graph.register_task(task)
    state = PlannerState([], [task], graph, [], [], plan, [])
    goal = Goal("G", "Goal")
    state.add_goal(goal)

    GoalApplicationService().change_goal(
        goal,
        state,
        GoalUpdateRequest(deadline=DATE + timedelta(days=1)),
    )

    assert state.current_plan is plan
    assert state.current_plan.schedule_blocks == [block]

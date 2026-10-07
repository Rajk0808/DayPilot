from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.planner import PlannerState
from daypilot.domain.task import Task
from daypilot.persistence.mappers.planner_state import from_record, to_record
from daypilot.persistence.mappers.task import TaskMappingContext, to_record as task_to_record


def test_planner_state_round_trip_preserves_canonical_tasks():
    task = Task("task", "Task")
    graph = DependencyGraph()
    graph.register_task(task)
    state = PlannerState([], [task], graph, [], [], None, [])
    record = to_record(state)

    context = TaskMappingContext()
    context.reconstruct([task_to_record(task)])
    restored = from_record(
        record,
        context,
        goal_records={},
        dependency_records={},
        calendar_event_records={},
        constraint_records={},
        plan_records={},
        schedule_block_records={},
        observation_records={},
    )

    assert restored.tasks[0] is context.tasks["task"]
    assert restored.dependency_graph.tasks["task"] is context.tasks["task"]

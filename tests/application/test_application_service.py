from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from daypilot.application.application_service import DayPilotApplicationService


DATE = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
END = DATE + timedelta(hours=4)


def make_facade():
    services = {
        "task": Mock(),
        "goal": Mock(),
        "dependency": Mock(),
        "calendar": Mock(),
        "constraint": Mock(),
        "observation": Mock(),
        "hierarchy": Mock(),
        "planning": Mock(),
    }
    facade = DayPilotApplicationService(
        task_service=services["task"],
        goal_service=services["goal"],
        dependency_service=services["dependency"],
        calendar_service=services["calendar"],
        constraint_service=services["constraint"],
        observation_service=services["observation"],
        hierarchy_service=services["hierarchy"],
        planning_service=services["planning"],
    )
    return facade, services


def test_facade_forwards_all_operations_and_returns_service_results():
    facade, services = make_facade()
    state = object()
    task = object()
    goal = object()
    dependency = object()
    event = object()
    constraint = object()
    request = object()
    updates = object()
    parent = object()
    child = object()
    result = object()

    cases = [
        (facade.create_task, services["task"].create_task, {"state": state, "request": request, "planning_start": DATE, "planning_end": END}),
        (facade.remove_task, services["task"].remove_task, {"state": state, "task": task, "planning_start": DATE, "planning_end": END}),
        (facade.change_task, services["task"].change_task, {"state": state, "task": task, "updates": updates, "planning_start": DATE, "planning_end": END}),
        (facade.create_goal, services["goal"].create_goal, {"goal": goal, "state": state}),
        (facade.change_goal, services["goal"].change_goal, {"goal": goal, "state": state, "change_request": updates}),
        (facade.remove_goal, services["goal"].remove_goal, {"goal": goal, "state": state}),
        (facade.add_dependency, services["dependency"].add_dependency, {"state": state, "dependent": task, "prereq": dependency, "planning_start": DATE, "planning_end": END}),
        (facade.remove_dependency, services["dependency"].remove_dependency, {"state": state, "dependent": task, "prereq": dependency, "planning_start": DATE, "planning_end": END}),
        (facade.add_constraint, services["constraint"].add_constraint, {"state": state, "constraint": constraint, "planning_start": DATE, "planning_end": END}),
        (facade.update_constraint, services["constraint"].update_constraint, {"state": state, "constraint": constraint, "changes": updates, "planning_start": DATE, "planning_end": END}),
        (facade.remove_constraint, services["constraint"].remove_constraint, {"state": state, "constraint": constraint, "planning_start": DATE, "planning_end": END}),
        (facade.add_calendar_event, services["calendar"].add_event, {"event": event, "state": state, "planning_start": DATE, "planning_end": END}),
        (facade.remove_calendar_event, services["calendar"].remove_event, {"event": event, "state": state, "planning_start": DATE, "planning_end": END}),
        (facade.update_calendar_event, services["calendar"].update_event, {"event": event, "state": state, "change_request": updates, "planning_start": DATE, "planning_end": END}),
        (facade.record_observation, services["observation"].record_observation, {"request": request, "state": state, "planning_start": DATE, "planning_end": END}),
        (facade.add_child, services["hierarchy"].add_child, {"state": state, "parent": parent, "child": child}),
        (facade.remove_child, services["hierarchy"].remove_child, {"state": state, "parent": parent, "child": child}),
        (facade.replan, services["planning"].replan, {"state": state, "change": dependency, "planning_start": DATE, "planning_end": END}),
        (facade.apply_replanning_result, services["planning"].apply_replanning_result, {"state": state, "result": result}),
    ]

    for facade_method, service_method, kwargs in cases:
        expected = None if facade_method.__name__ == "remove_goal" else object()
        service_method.return_value = expected

        assert facade_method(**kwargs) is expected
        service_method.assert_called_once_with(**kwargs)
        service_method.reset_mock()


def test_facade_propagates_delegated_exception_unchanged():
    facade, services = make_facade()
    failure = RuntimeError("domain/application failure")
    services["planning"].replan.side_effect = failure

    with pytest.raises(RuntimeError) as raised:
        facade.replan(object(), object(), DATE, END)

    assert raised.value is failure


def test_replan_and_apply_are_separate_facade_operations():
    facade, services = make_facade()
    state = object()
    change = object()
    result = object()
    services["planning"].replan.return_value = result
    services["planning"].apply_replanning_result.return_value = result

    assert facade.replan(state, change, DATE, END) is result
    services["planning"].replan.assert_called_once_with(
        state=state,
        change=change,
        planning_start=DATE,
        planning_end=END,
    )
    services["planning"].apply_replanning_result.assert_not_called()

    assert facade.apply_replanning_result(state, result) is result
    services["planning"].apply_replanning_result.assert_called_once_with(
        state=state,
        result=result,
    )

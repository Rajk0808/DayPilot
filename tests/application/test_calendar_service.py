from datetime import datetime, timedelta, timezone

import pytest

from daypilot.application import calendar_service
from daypilot.application.calendar_service import (
    CalendarApplicationService,
    CalendarEventUpdateRequest,
)
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import Priority, SchedulingStatus
from daypilot.domain.planner import PlannerState
from daypilot.domain.schedule import Plan, ScheduleBlock
from daypilot.domain.task import Task
from daypilot.domain.times import CalendarEvent


DATE = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
HORIZON = timedelta(hours=6)


def event(event_id: str = "E", start: datetime = DATE + timedelta(hours=3), end: datetime = DATE + timedelta(hours=4)) -> CalendarEvent:
    return CalendarEvent(event_id, "Event", start, end)


def empty_state(*events: CalendarEvent) -> PlannerState:
    return PlannerState([], [], DependencyGraph(), list(events), [], None, [])


def scheduled_state() -> tuple[PlannerState, Task, CalendarEvent]:
    task = Task(
        "A",
        "Task",
        priority=Priority.MEDIUM,
        estimated_duration=timedelta(hours=1),
    )
    task.scheduling_status = SchedulingStatus.SCHEDULED
    block = ScheduleBlock(task, DATE, DATE + timedelta(hours=1))
    plan = Plan("old", DATE, HORIZON, [block], {})
    graph = DependencyGraph()
    graph.register_task(task)
    calendar_event = event(start=DATE + timedelta(hours=2), end=DATE + timedelta(hours=3))
    return PlannerState([], [task], graph, [calendar_event], [], plan, []), task, calendar_event


def test_add_event_allows_new_event_and_rejects_same_identity_twice():
    state = empty_state()
    new_event = event()
    service = CalendarApplicationService()

    result = service.add_event(new_event, state, DATE, DATE + HORIZON)

    assert new_event in state.calendar_events
    assert result is state.current_plan or result.new_plan is state.current_plan
    with pytest.raises(ValueError, match="already exists"):
        service.add_event(new_event, state, DATE, DATE + HORIZON)


def test_equal_valued_non_owned_event_uses_identity_semantics():
    owned = event()
    lookalike = event()
    state = empty_state(owned)
    service = CalendarApplicationService()

    service.add_event(lookalike, state, DATE, DATE + HORIZON)
    assert state.calendar_events == [owned, lookalike]
    assert state.calendar_events[0] is owned

    with pytest.raises(ValueError, match="does not exist"):
        service.remove_event(event(), state, DATE, DATE + HORIZON)


def test_add_event_overlap_invalidates_affected_block():
    state, task, _ = scheduled_state()
    busy = event(start=DATE + timedelta(minutes=30), end=DATE + timedelta(hours=1, minutes=30))

    result = CalendarApplicationService().add_event(
        busy, state, DATE, DATE + HORIZON
    )

    assert result.invalidated_blocks[0].task is task
    assert busy in state.calendar_events


def test_remove_event_preserves_valid_existing_blocks():
    state, task, calendar_event = scheduled_state()
    old_plan = state.current_plan
    assert old_plan is not None
    old_blocks = list(old_plan.schedule_blocks)

    result = CalendarApplicationService().remove_event(
        calendar_event, state, DATE, DATE + HORIZON
    )

    assert calendar_event not in state.calendar_events
    assert result.invalidated_blocks == []
    assert result.new_plan.schedule_blocks == old_blocks
    assert state.current_plan is result.new_plan
    assert task in state.tasks


def test_remove_unknown_event_is_rejected():
    state = empty_state()

    with pytest.raises(ValueError, match="does not exist"):
        CalendarApplicationService().remove_event(
            event(), state, DATE, DATE + HORIZON
        )


def test_update_request_is_a_dataclass_and_updates_title():
    state = empty_state(event())
    calendar_event = state.calendar_events[0]

    request = CalendarEventUpdateRequest(title="Updated")
    CalendarApplicationService().update_event(
        calendar_event, state, request, DATE, DATE + HORIZON
    )

    assert calendar_event.title == "Updated"


def test_update_event_start_end_and_both_values():
    calendar_event = event()
    state = empty_state(calendar_event)
    service = CalendarApplicationService()
    new_start = DATE + timedelta(hours=1)
    new_end = DATE + timedelta(hours=2)

    service.update_event(
        calendar_event,
        state,
        CalendarEventUpdateRequest(start=new_start),
        DATE,
        DATE + HORIZON,
    )
    assert calendar_event.start == new_start
    assert calendar_event.end == DATE + timedelta(hours=4)

    service.update_event(
        calendar_event,
        state,
        CalendarEventUpdateRequest(start=new_start, end=new_end),
        DATE,
        DATE + HORIZON,
    )
    assert calendar_event.start == new_start
    assert calendar_event.end == new_end


def test_updated_event_uses_post_change_interval_for_invalidation():
    state, task, calendar_event = scheduled_state()
    request = CalendarEventUpdateRequest(
        start=DATE + timedelta(minutes=30),
        end=DATE + timedelta(hours=1, minutes=30),
    )

    result = CalendarApplicationService().update_event(
        calendar_event, state, request, DATE, DATE + HORIZON
    )

    assert result.invalidated_blocks[0].task is task
    assert calendar_event.start == DATE + timedelta(minutes=30)
    assert calendar_event.end == DATE + timedelta(hours=1, minutes=30)


def test_empty_update_is_rejected_without_mutating_event():
    calendar_event = event()
    state = empty_state(calendar_event)
    original = (calendar_event.title, calendar_event.start, calendar_event.end)

    with pytest.raises(ValueError, match="empty"):
        CalendarApplicationService().update_event(
            calendar_event,
            state,
            CalendarEventUpdateRequest(),
            DATE,
            DATE + HORIZON,
        )

    assert (calendar_event.title, calendar_event.start, calendar_event.end) == original


@pytest.mark.parametrize(
    "update_request",
    [
        CalendarEventUpdateRequest(start=datetime(2026, 10, 5, 10)),
        CalendarEventUpdateRequest(end=datetime(2026, 10, 5, 12)),
        CalendarEventUpdateRequest(
            start=DATE + timedelta(hours=4),
            end=DATE + timedelta(hours=3),
        ),
    ],
)
def test_invalid_update_values_leave_event_unchanged(update_request):
    calendar_event = event()
    state = empty_state(calendar_event)
    original = (calendar_event.title, calendar_event.start, calendar_event.end)

    with pytest.raises(ValueError):
        CalendarApplicationService().update_event(
            calendar_event, state, update_request, DATE, DATE + HORIZON
        )

    assert (calendar_event.title, calendar_event.start, calendar_event.end) == original


def test_update_failure_restores_event_and_plan(monkeypatch):
    state, _, calendar_event = scheduled_state()
    old_plan = state.current_plan
    original = (calendar_event.title, calendar_event.start, calendar_event.end)

    def fail_replan(*args, **kwargs):
        raise RuntimeError("planning failed")

    monkeypatch.setattr(calendar_service, "replan", fail_replan)

    with pytest.raises(RuntimeError, match="planning failed"):
        CalendarApplicationService().update_event(
            calendar_event,
            state,
                CalendarEventUpdateRequest(
                    title="Changed",
                    start=DATE + timedelta(hours=4),
                    end=DATE + timedelta(hours=5),
                ),
            DATE,
            DATE + HORIZON,
        )

    assert (calendar_event.title, calendar_event.start, calendar_event.end) == original
    assert state.current_plan is old_plan


def test_commit_failure_restores_event_and_plan(monkeypatch):
    state, _, calendar_event = scheduled_state()
    old_plan = state.current_plan
    original = (calendar_event.title, calendar_event.start, calendar_event.end)

    def fail_commit(*args, **kwargs):
        raise RuntimeError("commit failed")

    monkeypatch.setattr(calendar_service, "apply_replanning_result", fail_commit)

    with pytest.raises(RuntimeError, match="commit failed"):
        CalendarApplicationService().update_event(
            calendar_event,
            state,
            CalendarEventUpdateRequest(title="Changed"),
            DATE,
            DATE + HORIZON,
        )

    assert (calendar_event.title, calendar_event.start, calendar_event.end) == original
    assert state.current_plan is old_plan


def test_add_and_remove_failures_restore_event_state(monkeypatch):
    service = CalendarApplicationService()
    new_event = event()
    add_state = empty_state()

    def fail_replan(*args, **kwargs):
        raise RuntimeError("planning failed")

    monkeypatch.setattr(calendar_service, "replan", fail_replan)
    with pytest.raises(RuntimeError):
        service.add_event(new_event, add_state, DATE, DATE + HORIZON)
    assert new_event not in add_state.calendar_events

    existing = event()
    remove_state = empty_state(existing)
    with pytest.raises(RuntimeError):
        service.remove_event(existing, remove_state, DATE, DATE + HORIZON)
    assert remove_state.calendar_events == [existing]

from dataclasses import dataclass
from datetime import datetime, timezone

from daypilot.domain.enums import PlanningChangeType
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import (
    PlanningChange,
    ReplanningResult,
    apply_replanning_result,
    replan,
)
from daypilot.domain.times import CalendarEvent


@dataclass(frozen=True)
class CalendarEventUpdateRequest:
    title: str | None = None
    start: datetime | None = None
    end: datetime | None = None


@dataclass(frozen=True)
class CalendarApplicationService:
    _UPDATE_FIELDS = ("title", "start", "end")

    @staticmethod
    def _validate_common_request(
            state: PlannerState,
            event: CalendarEvent,
            planning_start: datetime,
            planning_end: datetime,
        ) -> None:
        if state is None:
            raise ValueError("Planner state cannot be None")
        if not isinstance(state, PlannerState):
            raise ValueError("Planner state must be an instance of PlannerState")
        if event is None:
            raise ValueError("Event cannot be None")
        if planning_start is None or planning_end is None:
            raise ValueError("Planning start and end cannot be None")
        if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
            raise ValueError("Planning start and end must be timezone-aware")
        if planning_start >= planning_end:
            raise ValueError("Planning end must be after planning start")

    @staticmethod
    def _require_owned_event(state: PlannerState, event: CalendarEvent) -> None:
        if not any(existing is event for existing in state.calendar_events):
            raise ValueError("Event does not exist in the planner state")

    @staticmethod
    def _validate_proposed_values(
            title: str,
            start: datetime,
            end: datetime,
        ) -> tuple[str, datetime, datetime]:
        if not isinstance(title, str):
            raise ValueError("Event title must be a string")
        if start is None or end is None:
            raise ValueError("Event start and end cannot be None")
        if start.utcoffset() is None or end.utcoffset() is None:
            raise ValueError("Event start and end must be timezone-aware")
        normalized_start = start.astimezone(timezone.utc)
        normalized_end = end.astimezone(timezone.utc)
        if normalized_start >= normalized_end:
            raise ValueError("Event start must be before event end")
        return title, normalized_start, normalized_end

    def add_event(
            self,
            event: CalendarEvent,
            state: PlannerState,
            planning_start: datetime,
            planning_end: datetime,
            ) -> ReplanningResult:
        self._validate_common_request(state, event, planning_start, planning_end)
        if any(existing is event for existing in state.calendar_events):
            raise ValueError("Event already exists in the planner state")

        state.add_calendar_event(event)
        try:
            change = PlanningChange(
                change_type=PlanningChangeType.CALENDAR_EVENT_ADDED,
                metadata={"event": event},
            )
            result = replan(state, change, planning_start, planning_end)
            apply_replanning_result(state, result)
        except Exception:
            state.remove_calendar_event(event)
            raise
        return result

    def remove_event(
            self,
            event: CalendarEvent,
            state: PlannerState,
            planning_start: datetime,
            planning_end: datetime,
            ) -> ReplanningResult:
        self._validate_common_request(state, event, planning_start, planning_end)
        self._require_owned_event(state, event)
        state.remove_calendar_event(event)
        try:
            change = PlanningChange(
                change_type=PlanningChangeType.CALENDAR_EVENT_REMOVED,
                metadata={"event": event},
            )
            result = replan(state, change, planning_start, planning_end)
            apply_replanning_result(state, result)
        except Exception:
            state.add_calendar_event(event)
            raise
        return result

    def update_event(
            self,
            event: CalendarEvent,
            state: PlannerState,
            change_request: CalendarEventUpdateRequest,
            planning_start: datetime,
            planning_end: datetime,
            ) -> ReplanningResult:
        self._validate_common_request(state, event, planning_start, planning_end)
        self._require_owned_event(state, event)
        if change_request is None:
            raise ValueError("Change request cannot be None")

        changed_fields = {
            field for field in self._UPDATE_FIELDS
            if getattr(change_request, field) is not None
        }
        if not changed_fields:
            raise ValueError("Calendar event update cannot be empty")

        new_title = change_request.title if change_request.title is not None else event.title
        new_start = change_request.start if change_request.start is not None else event.start
        new_end = change_request.end if change_request.end is not None else event.end
        validated_title, validated_start, validated_end = self._validate_proposed_values(
            new_title,
            new_start,
            new_end,
        )
        original_values = {
            field: getattr(event, field) for field in self._UPDATE_FIELDS
        }
        try:
            event.title = validated_title
            event.start = validated_start
            event.end = validated_end
            change = PlanningChange(
                change_type=PlanningChangeType.CALENDAR_EVENT_UPDATED,
                metadata={"event": event},
            )
            result = replan(state, change, planning_start, planning_end)
            apply_replanning_result(state, result)
        except Exception:
            for field, value in original_values.items():
                setattr(event, field, value)
            raise
        return result

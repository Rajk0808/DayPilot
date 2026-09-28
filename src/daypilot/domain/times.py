from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .enums import ConstraintType


def _normalize_timestamp(value: datetime) -> datetime:
    """Require a timezone and normalize timestamps to UTC."""
    if value.utcoffset() is None:
        raise ValueError("Timestamps must be timezone-aware.")
    return value.astimezone(timezone.utc)


@dataclass
class CalendarEvent:
    id: str
    title: str
    start: datetime 
    end: datetime 
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validates that the start timestamp occurs before the end timestamp,

        ensuring both are timezone-aware.
        """
        self.start = _normalize_timestamp(self.start)
        self.end = _normalize_timestamp(self.end)

        if self.start >= self.end:
            raise ValueError(
                f"Validation failed: start ({self.start}) must be before end ({self.end})."
            )

@dataclass
class TimeWindow:
    start: datetime 
    end: datetime 

    def __post_init__(self) -> None:
        """Validates that the start timestamp occurs before the end timestamp."""
        self.start = _normalize_timestamp(self.start)
        self.end = _normalize_timestamp(self.end)

        if self.start >= self.end:
            raise ValueError(
                f"Validation failed: start ({self.start}) must be before end ({self.end})."
            )


@dataclass
class Constraint:
    type: ConstraintType
    rule_information: TimeWindow
    description: str = ""


def generate_time_windows(
    day_start: datetime,
    day_end: datetime,
    calendar_events: list[CalendarEvent],
    hard_constraints: list[Constraint],
) -> list[TimeWindow]:
    day = TimeWindow(day_start, day_end)
    if any(constraint.type is not ConstraintType.HARD_CONSTRAINT
           for constraint in hard_constraints):
        raise ValueError("Only hard constraints can be used to generate time windows.")

    busy_intervals: list[tuple[datetime, datetime]] = [
        (event.start, event.end) for event in calendar_events
    ]
    busy_intervals.extend(
        (constraint.rule_information.start, constraint.rule_information.end)
        for constraint in hard_constraints
    )

    # Discard intervals outside the day and clip partial overlaps to its bounds.
    clipped_intervals = [
        (max(start, day.start), min(end, day.end))
        for start, end in busy_intervals
        if start < day.end and end > day.start
    ]
    clipped_intervals.sort(key=lambda interval: interval[0])

    merged_intervals: list[tuple[datetime, datetime]] = []
    for start, end in clipped_intervals:
        if merged_intervals and start <= merged_intervals[-1][1]:
            previous_start, previous_end = merged_intervals[-1]
            merged_intervals[-1] = (previous_start, max(previous_end, end))
        else:
            merged_intervals.append((start, end))

    available_windows: list[TimeWindow] = []
    cursor = day.start
    for busy_start, busy_end in merged_intervals:
        if cursor < busy_start:
            available_windows.append(TimeWindow(cursor, busy_start))
        cursor = max(cursor, busy_end)
    if cursor < day.end:
        available_windows.append(TimeWindow(cursor, day.end))

    return available_windows

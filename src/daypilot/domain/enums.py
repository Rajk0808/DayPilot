from enum import Enum
from tkinter.messagebox import CANCEL


class TaskStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class DependencyType(str, Enum):
    FINISH_TO_START = "finish_to_start"
    START_TO_START = "start_to_start"
    FINISH_TO_FINISH = "finish_to_finish"
    START_TO_FINISH = "start_to_finish"

class ConstraintType(str, Enum):
    HARD_CONSTRAINT = "hard_constraint"
    SOFT_CONSTRAINT = "soft_constraint"

class SchedulingStatus(str, Enum):
    SCHEDULED = "scheduled"
    UNSCHEDULED = "unscheduled"


class SchedulingFailureReason(str, Enum):
    NO_AVAILABLE_WINDOW = "no_available_window"
    INSUFFICIENT_TIME = "insufficient_time"
    DEPENDENCY_BLOCKED = "dependency_blocked"
    INVALID_STATE = "invalid_state"
    ALREADY_SCHEDULED = "already_scheduled"

class ObservationOutcome(str, Enum):
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    CANCELLED = "cancelled"
    NOT_STARTED = "not_started"


class PlanningChangeType(str, Enum):
    TASK_ADDED = "task_added"
    TASK_UPDATED = "task_updated"
    TASK_REMOVED = "task_removed"

    DEPENDENCY_ADDED = "dependency_added"
    DEPENDENCY_REMOVED = "dependency_removed"

    CALENDAR_EVENT_ADDED = "calendar_event_added"
    CALENDAR_EVENT_UPDATED = "calendar_event_updated"
    CALENDAR_EVENT_REMOVED = "calendar_event_removed"

    CONSTRAINT_ADDED = "constraint_added"
    CONSTRAINT_UPDATED = "constraint_updated"
    CONSTRAINT_REMOVED = "constraint_removed"

    OBSERVATION_RECORDED = "observation_recorded"

    PLAN_REPLACED = "plan_replaced"

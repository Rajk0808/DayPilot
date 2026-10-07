from dataclasses import dataclass


@dataclass
class PlannerStateRecord:
    goal_ids: list[str]
    task_ids: list[str]
    dependency_ids: list[str]
    calendar_event_ids: list[str]
    constraint_ids: list[str]
    current_plan_id: str | None
    observation_ids: list[str]

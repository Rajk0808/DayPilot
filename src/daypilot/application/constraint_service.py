from dataclasses import dataclass
from datetime import datetime

from daypilot.domain.replan import apply_replanning_result, replan
from daypilot.domain.enums import PlanningChangeType, ConstraintType
from daypilot.domain.planner import PlannerState
from daypilot.domain.replan import PlanningChange, ReplanningResult
from daypilot.domain.times import Constraint, TimeWindow

@dataclass(frozen=True)
class ConstraintUpdateRequest:
    type: ConstraintType | None = None
    rule_information: TimeWindow | None = None
    description: str | None = None

@dataclass(frozen=True)
class ConstraintApplicationService:
    _UPDATE_FIELDS = ("type", "rule_information", "description")
    """A service for adding constraints to a planner state."""
    def _validate_regular_request(
            self,
            state: PlannerState,
            constraint: Constraint,
            planning_start: datetime,
            planning_end: datetime,
        ) -> None:
        if state is None:
            raise ValueError("Planner state cannot be None")
        if not isinstance(state, PlannerState):
            raise ValueError("Planner state must be an instance of PlannerState")
        if constraint is None:
            raise ValueError("Constraint cannot be None")
        if planning_start is None or planning_end is None:
            raise ValueError("Planning start and end cannot be None")
        if planning_start.utcoffset() is None or planning_end.utcoffset() is None:
            raise ValueError("Planning start and end must be timezone-aware")
        if planning_start >= planning_end:
            raise ValueError("Planning end must be after planning start")
        
    def add_constraint(
            self, 
            state: PlannerState, 
            constraint: Constraint, 
            planning_start: datetime, 
            planning_end: datetime
        ) -> ReplanningResult:
        self._validate_regular_request(state, constraint, planning_start, planning_end)

        state.add_constraint(constraint)

        try:
            changed_planning = PlanningChange(
                change_type=PlanningChangeType.CONSTRAINT_ADDED,
                metadata={"constraint": constraint}
            )

            replan_results = replan(
                planner_state=state,
                change=changed_planning,
                planning_start=planning_start,
                planning_end=planning_end
            )

            apply_replanning_result(planner_state=state, result=replan_results) 
            return replan_results
        except Exception:
            state.remove_constraint(constraint)
            raise


    def remove_constraint(
            self, 
            state: PlannerState, 
            constraint: Constraint, 
            planning_start: datetime, 
            planning_end: datetime
        ) -> ReplanningResult:
        self._validate_regular_request(state, constraint, planning_start, planning_end)
        if not any(existing is constraint for existing in state.constraints):
            raise ValueError("Constraint does not exist in the planner state")
        state.remove_constraint(constraint)

        try:
            changed_planning = PlanningChange(
                change_type=PlanningChangeType.CONSTRAINT_REMOVED,
                metadata={"constraint": constraint}
            )

            replan_results = replan(
                planner_state=state,
                change=changed_planning,
                planning_start=planning_start,
                planning_end=planning_end
            )

            apply_replanning_result(planner_state=state, result=replan_results) 
            return replan_results
        except Exception:
            state.add_constraint(constraint)
            raise

    def update_constraint(
            self,
            state: PlannerState,
            constraint: Constraint,
            changes: ConstraintUpdateRequest,
            planning_start: datetime,
            planning_end: datetime
    ) -> ReplanningResult:

        self._validate_regular_request( state, constraint, planning_start, planning_end)
        if changes is None:
            raise ValueError("Changes cannot be None")
        if not any(existing is constraint for existing in state.constraints):
            raise ValueError("Constraint does not exist in the planner state")
        original_values = {field: getattr(constraint, field) for field in self._UPDATE_FIELDS}
        changed_fields = {
            field
            for field in self._UPDATE_FIELDS
            if getattr(changes, field) is not None
        }
        
        if not changed_fields:
            raise ValueError("Constraint update cannot be empty")
        new_type = changes.type if changes.type is not None else constraint.type
        new_rule_information = (
            changes.rule_information
            if changes.rule_information is not None
            else constraint.rule_information
        )
        new_description = (
            changes.description
            if changes.description is not None
            else constraint.description
        )
        Constraint(new_type, new_rule_information, new_description)
        try:
            for field in changed_fields:
                setattr(constraint, field, getattr(changes, field))

            changed_planning = PlanningChange(
                change_type=PlanningChangeType.CONSTRAINT_UPDATED,
                metadata={"constraint": constraint, "changed_fields": changed_fields}
            )

            replan_results = replan(
                planner_state=state,
                change=changed_planning,
                planning_start=planning_start,
                planning_end=planning_end
            )

            apply_replanning_result(planner_state=state, result=replan_results)
            return replan_results
        except Exception:
            for field, value in original_values.items():
                setattr(constraint, field, value)
            raise

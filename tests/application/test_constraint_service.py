from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from daypilot.application import constraint_service
from daypilot.application.constraint_service import (
    ConstraintApplicationService,
    ConstraintUpdateRequest,
)
from daypilot.domain.dependency_graph import DependencyGraph
from daypilot.domain.enums import ConstraintType
from daypilot.domain.planner import PlannerState
from daypilot.domain.times import Constraint, TimeWindow


DATE = datetime(2026, 10, 5, 9, tzinfo=timezone.utc)
HORIZON = timedelta(hours=6)


def make_constraint() -> Constraint:
    return Constraint(
        ConstraintType.SOFT_CONSTRAINT,
        TimeWindow(DATE + timedelta(hours=1), DATE + timedelta(hours=2)),
        "Original",
    )


def make_state(constraint: Constraint) -> PlannerState:
    return PlannerState([], [], DependencyGraph(), [], [constraint], None, [])


def test_partial_constraint_update_reports_exact_changed_fields(monkeypatch):
    constraint = make_constraint()
    state = make_state(constraint)
    captured = {}
    real_replan = constraint_service.replan

    def capture_replan(*args, **kwargs):
        change = kwargs["change"]
        captured["change"] = change
        return real_replan(*args, **kwargs)

    monkeypatch.setattr(constraint_service, "replan", capture_replan)

    ConstraintApplicationService().update_constraint(
        state,
        constraint,
        ConstraintUpdateRequest(description="Updated"),
        DATE,
        DATE + HORIZON,
    )

    assert captured["change"].metadata["changed_fields"] == {"description"}
    assert constraint.description == "Updated"


def test_invalid_proposed_constraint_is_rejected_before_mutation():
    constraint = make_constraint()
    state = make_state(constraint)
    original = (constraint.type, constraint.rule_information, constraint.description)
    invalid_rule = cast(TimeWindow, object())

    with pytest.raises(ValueError, match="rule information"):
        ConstraintApplicationService().update_constraint(
            state,
            constraint,
            ConstraintUpdateRequest(rule_information=invalid_rule),
            DATE,
            DATE + HORIZON,
        )

    assert (constraint.type, constraint.rule_information, constraint.description) == original

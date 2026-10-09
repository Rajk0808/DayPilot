import ast
from pathlib import Path

from sqlalchemy import BigInteger, CheckConstraint, DateTime, UniqueConstraint, create_engine, inspect
from sqlalchemy.dialects.postgresql import JSONB, UUID as PostgreSQLUUID

from daypilot.persistence.orm import Base


def _primary_key(table):
    return tuple(column.name for column in table.primary_key.columns)


def _foreign_keys(table):
    return {
        tuple(element.parent.name for element in constraint.elements): tuple(
            element.target_fullname for element in constraint.elements
        )
        for constraint in table.foreign_key_constraints
    }


def _unique_constraints(table):
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def _checks(table):
    return {
        " ".join(constraint.sqltext.text.split())
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }


def test_metadata_contains_exactly_the_schema_tables():
    assert set(Base.metadata.tables) == {
        "planner_states",
        "tasks",
        "goals",
        "goal_root_tasks",
        "dependencies",
        "calendar_events",
        "constraints",
        "plans",
        "schedule_blocks",
        "observations",
    }


def test_metadata_creates_all_tables_on_sqlite():
    engine = create_engine("sqlite://")
    try:
        Base.metadata.create_all(engine)
        assert set(inspect(engine).get_table_names()) == set(Base.metadata.tables)
    finally:
        engine.dispose()


def test_primary_keys_match_schema():
    expected = {
        "planner_states": ("id",),
        "tasks": ("state_id", "id"),
        "goals": ("state_id", "id"),
        "goal_root_tasks": ("state_id", "goal_id", "task_id"),
        "dependencies": ("state_id", "dependent_task_id", "prerequisite_task_id"),
        "calendar_events": ("state_id", "id"),
        "constraints": ("state_id", "constraint_id"),
        "plans": ("state_id", "id"),
        "schedule_blocks": ("state_id", "id"),
        "observations": ("state_id", "id"),
    }

    assert {name: _primary_key(table) for name, table in Base.metadata.tables.items()} == expected


def test_columns_and_nullability_match_schema():
    expected = {
        "planner_states": {"id", "version", "created_at", "updated_at"},
        "tasks": {
            "state_id", "id", "title", "description", "status", "scheduling_status",
            "priority", "estimated_duration_microseconds",
            "deadline_timestamp_microseconds", "metadata", "parent_task_id",
        },
        "goals": {
            "state_id", "id", "title", "description",
            "deadline_timestamp_microseconds", "status",
        },
        "goal_root_tasks": {"state_id", "goal_id", "task_id"},
        "dependencies": {"state_id", "dependent_task_id", "prerequisite_task_id"},
        "calendar_events": {
            "state_id", "id", "title", "start_timestamp_microseconds",
            "end_timestamp_microseconds", "metadata",
        },
        "constraints": {
            "state_id", "constraint_id", "type", "start_timestamp_microseconds",
            "end_timestamp_microseconds", "description",
        },
        "plans": {
            "state_id", "id", "date_timestamp_microseconds",
            "planning_horizon_microseconds", "metadata",
        },
        "schedule_blocks": {
            "state_id", "id", "task_id", "plan_id",
            "start_timestamp_microseconds", "end_timestamp_microseconds",
        },
        "observations": {
            "state_id", "id", "task_id", "schedule_block_id",
            "actual_start_timestamp_microseconds", "actual_end_timestamp_microseconds",
            "outcome", "metadata",
        },
    }
    nullable = {
        "planner_states": set(),
        "tasks": {"priority", "deadline_timestamp_microseconds", "parent_task_id"},
        "goals": {"deadline_timestamp_microseconds"},
        "goal_root_tasks": set(),
        "dependencies": set(),
        "calendar_events": set(),
        "constraints": set(),
        "plans": set(),
        "schedule_blocks": {"plan_id"},
        "observations": set(),
    }

    assert set(Base.metadata.tables) == set(expected)
    for table_name, expected_columns in expected.items():
        table = Base.metadata.tables[table_name]
        assert set(table.c.keys()) == expected_columns
        assert {column.name for column in table.columns if column.nullable} == nullable[table_name]


def test_all_child_tables_are_owned_by_planner_state():
    for table_name, table in Base.metadata.tables.items():
        if table_name == "planner_states":
            continue
        state_id = table.c.state_id
        assert state_id.nullable is False
        assert any(
            foreign_key.target_fullname == "planner_states.id"
            and foreign_key.ondelete == "CASCADE"
            for foreign_key in state_id.foreign_keys
        )


def test_task_schema_has_same_state_self_reference_and_no_children_array():
    table = Base.metadata.tables["tasks"]

    assert {
        "state_id", "id", "title", "description", "status", "scheduling_status",
        "priority", "estimated_duration_microseconds",
        "deadline_timestamp_microseconds", "metadata", "parent_task_id",
    } == set(table.c.keys())
    assert _primary_key(table) == ("state_id", "id")
    assert _foreign_keys(table)[("state_id", "parent_task_id")] == (
        "tasks.state_id", "tasks.id"
    )
    assert "children_ids" not in table.c
    assert isinstance(table.c.estimated_duration_microseconds.type, BigInteger)
    assert table.c.deadline_timestamp_microseconds.nullable is True
    assert table.c.priority.nullable is True
    assert "parent_task_id IS NULL OR parent_task_id <> id" in _checks(table)
    assert "estimated_duration_microseconds >= 0" in _checks(table)


def test_goal_root_association_has_composite_foreign_keys_and_uniqueness():
    table = Base.metadata.tables["goal_root_tasks"]

    assert _primary_key(table) == ("state_id", "goal_id", "task_id")
    foreign_keys = _foreign_keys(table)
    assert foreign_keys[("state_id", "goal_id")] == ("goals.state_id", "goals.id")
    assert foreign_keys[("state_id", "task_id")] == ("tasks.state_id", "tasks.id")
    assert ("state_id", "task_id") in _unique_constraints(table)


def test_dependency_uses_composite_task_foreign_keys_and_rejects_self_edge():
    table = Base.metadata.tables["dependencies"]
    foreign_keys = _foreign_keys(table)

    assert _primary_key(table) == ("state_id", "dependent_task_id", "prerequisite_task_id")
    assert foreign_keys[("state_id", "dependent_task_id")] == ("tasks.state_id", "tasks.id")
    assert foreign_keys[("state_id", "prerequisite_task_id")] == ("tasks.state_id", "tasks.id")
    assert "dependent_task_id <> prerequisite_task_id" in _checks(table)


def test_postgresql_specific_types_and_nullable_fields_match_schema():
    states = Base.metadata.tables["planner_states"]
    constraints = Base.metadata.tables["constraints"]
    events = Base.metadata.tables["calendar_events"]
    plans = Base.metadata.tables["plans"]

    assert isinstance(states.c.version.type, BigInteger)
    assert "version > 0" in _checks(states)
    assert isinstance(states.c.created_at.type, DateTime)
    assert states.c.created_at.type.timezone is True
    assert isinstance(constraints.c.constraint_id.type, PostgreSQLUUID)
    assert isinstance(events.c.metadata.type, JSONB)
    assert isinstance(plans.c.metadata.type, JSONB)
    assert constraints.c.constraint_id.server_default is not None
    assert Base.metadata.tables["tasks"].c.deadline_timestamp_microseconds.nullable is True


def test_plan_and_schedule_block_constraints_match_schema():
    plans = Base.metadata.tables["plans"]
    blocks = Base.metadata.tables["schedule_blocks"]
    foreign_keys = _foreign_keys(blocks)

    assert ("state_id",) in _unique_constraints(plans)
    assert foreign_keys[("state_id", "task_id")] == ("tasks.state_id", "tasks.id")
    assert foreign_keys[("state_id", "plan_id")] == ("plans.state_id", "plans.id")
    assert blocks.c.plan_id.nullable is True
    assert "status" not in blocks.c
    assert ("state_id", "task_id", "id") in _unique_constraints(blocks)


def test_observation_reference_uses_same_task_and_state_as_block():
    table = Base.metadata.tables["observations"]
    foreign_keys = _foreign_keys(table)

    assert foreign_keys[("state_id", "task_id", "schedule_block_id")] == (
        "schedule_blocks.state_id",
        "schedule_blocks.task_id",
        "schedule_blocks.id",
    )
    assert "actual_start_timestamp_microseconds < actual_end_timestamp_microseconds" in _checks(table)


def test_all_database_check_constraints_match_schema():
    expected = {
        "planner_states": {"version > 0"},
        "tasks": {
            "estimated_duration_microseconds >= 0",
            "parent_task_id IS NULL OR parent_task_id <> id",
        },
        "goals": set(),
        "goal_root_tasks": set(),
        "dependencies": {"dependent_task_id <> prerequisite_task_id"},
        "calendar_events": {"start_timestamp_microseconds < end_timestamp_microseconds"},
        "constraints": {"start_timestamp_microseconds < end_timestamp_microseconds"},
        "plans": {"planning_horizon_microseconds > 0"},
        "schedule_blocks": {"start_timestamp_microseconds < end_timestamp_microseconds"},
        "observations": {
            "actual_start_timestamp_microseconds < actual_end_timestamp_microseconds"
        },
    }

    assert {name: _checks(table) for name, table in Base.metadata.tables.items()} == expected


def test_orm_package_does_not_import_domain_or_application_code():
    source_root = Path(__file__).parents[3] / "src" / "daypilot" / "persistence" / "orm"
    for source_file in source_root.glob("*.py"):
        tree = ast.parse(source_file.read_text(encoding="utf-8"))
        imported_modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_modules.append(node.module)
        assert not any(
            module.startswith(("daypilot.domain", "daypilot.application"))
            for module in imported_modules
        ), source_file

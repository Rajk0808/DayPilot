"""Alembic environment bound to DayPilot's ORM metadata."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import text

from daypilot.persistence.database import DatabaseSettings, create_database_engine
from daypilot.persistence.orm import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _database_url() -> str:
    return (
        os.environ.get("DAYPILOT_TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or config.get_main_option("sqlalchemy.url")
    )


def run_migrations_offline() -> None:
    context.configure(
        url=_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        context.configure(
            connection=supplied_connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return

    connectable = create_database_engine(DatabaseSettings(_database_url()))
    with connectable.connect() as connection:
        schema = os.environ.get("DAYPILOT_ALEMBIC_SCHEMA")
        if schema:
            if not schema.replace("_", "").isalnum():
                raise ValueError("DAYPILOT_ALEMBIC_SCHEMA must be a simple SQL identifier")
            quoted_schema = connection.dialect.identifier_preparer.quote(schema)
            with connection.begin():
                connection.execute(text(f"SET LOCAL search_path TO {quoted_schema}"))
                context.configure(
                    connection=connection,
                    target_metadata=target_metadata,
                    compare_type=True,
                )
                with context.begin_transaction():
                    context.run_migrations()
            connectable.dispose()
            return
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

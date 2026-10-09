from sqlalchemy.pool import NullPool

from daypilot.persistence.database.config import DatabaseSettings
from daypilot.persistence.database.engine import create_database_engine


def test_engine_is_constructed_without_connecting_or_creating_schema(tmp_path):
    database_path = tmp_path / "daypilot.sqlite"
    settings = DatabaseSettings(database_url=f"sqlite:///{database_path.as_posix()}")

    engine = create_database_engine(settings)
    try:
        assert engine.url.database == database_path.as_posix()
        assert not database_path.exists()
    finally:
        engine.dispose()


def test_transaction_pool_mode_uses_null_pool():
    engine = create_database_engine(
        DatabaseSettings(
            database_url="sqlite:///daypilot.sqlite",
            pool_mode="transaction",
        )
    )
    try:
        assert isinstance(engine.pool, NullPool)
    finally:
        engine.dispose()


def test_pgbouncer_query_hint_is_not_passed_to_the_postgresql_driver():
    engine = create_database_engine(
        DatabaseSettings(
            database_url=(
                "postgresql+psycopg://user:password@localhost/daypilot"
                "?pgbouncer=true&sslmode=require"
            )
        )
    )
    try:
        assert "pgbouncer" not in engine.url.query
        assert engine.url.query["sslmode"] == "require"
    finally:
        engine.dispose()

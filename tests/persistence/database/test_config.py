import pytest

from daypilot.persistence.database.config import DatabaseSettings


def test_settings_are_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/daypilot")
    monkeypatch.setenv("DAYPILOT_ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_ECHO", "true")
    monkeypatch.setenv("DATABASE_POOL_SIZE", "7")
    monkeypatch.setenv("DATABASE_MAX_OVERFLOW", "3")
    monkeypatch.setenv("DATABASE_POOL_MODE", "transaction")

    settings = DatabaseSettings.from_environment()

    assert settings.database_url == "postgresql+psycopg://user:pass@localhost/daypilot"
    assert settings.environment == "test"
    assert settings.echo is True
    assert settings.pool_size == 7
    assert settings.max_overflow == 3
    assert settings.pool_mode == "transaction"


def test_missing_database_url_is_rejected(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(ValueError, match="DATABASE_URL"):
        DatabaseSettings.from_environment()


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_url": ""},
        {"database_url": "not-a-database-url"},
        {"database_url": "mysql://localhost/daypilot"},
        {"pool_size": 0},
        {"max_overflow": -1},
        {"pool_mode": "unknown"},
    ],
)
def test_invalid_settings_are_rejected(overrides):
    values = {"database_url": "sqlite:///daypilot.db"}
    values.update(overrides)

    with pytest.raises(ValueError):
        DatabaseSettings(**values)


def test_invalid_environment_values_are_rejected(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///daypilot.db")
    monkeypatch.setenv("DATABASE_ECHO", "sometimes")

    with pytest.raises(ValueError, match="DATABASE_ECHO"):
        DatabaseSettings.from_environment()

"""Environment-backed settings for the SQLAlchemy database connection."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class DatabaseSettings:
    """Connection settings independent of any DayPilot domain model."""

    database_url: str
    environment: str = "development"
    echo: bool = False
    pool_size: int = 5
    max_overflow: int = 10
    pool_mode: Literal["standard", "transaction"] = "standard"

    def __post_init__(self) -> None:
        if not isinstance(self.database_url, str) or not self.database_url.strip():
            raise ValueError("Database URL must be a non-empty string.")
        try:
            url = make_url(self.database_url)
        except Exception as exc:
            raise ValueError("Database URL must be a valid SQLAlchemy URL.") from exc
        if url.drivername.split("+")[0] not in {"postgresql", "sqlite"}:
            raise ValueError("Database URL must use PostgreSQL or SQLite.")
        if not isinstance(self.environment, str) or not self.environment.strip():
            raise ValueError("Environment must be a non-empty string.")
        if not isinstance(self.echo, bool):
            raise ValueError("Echo must be a boolean.")
        if isinstance(self.pool_size, bool) or not isinstance(self.pool_size, int) or self.pool_size < 1:
            raise ValueError("Pool size must be a positive integer.")
        if isinstance(self.max_overflow, bool) or not isinstance(self.max_overflow, int) or self.max_overflow < 0:
            raise ValueError("Maximum pool overflow must be a non-negative integer.")
        if self.pool_mode not in ("standard", "transaction"):
            raise ValueError("Pool mode must be 'standard' or 'transaction'.")

    @classmethod
    def from_environment(cls) -> DatabaseSettings:
        """Read database settings from environment variables.

        ``DATABASE_URL`` is required. Passwords and provider connection
        strings therefore stay outside source control.
        """
        database_url = os.environ.get("DATABASE_URL")
        if database_url is None:
            raise ValueError("DATABASE_URL environment variable is required.")
        return cls(
            database_url=database_url,
            environment=os.environ.get("DAYPILOT_ENVIRONMENT", "development"),
            echo=_environment_bool("DATABASE_ECHO", default=False),
            pool_size=_environment_int("DATABASE_POOL_SIZE", default=5),
            max_overflow=_environment_int("DATABASE_MAX_OVERFLOW", default=10),
            pool_mode=cast(
                Literal["standard", "transaction"],
                os.environ.get("DATABASE_POOL_MODE", "standard"),
            ),
        )


def _environment_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean value.")


def _environment_int(name: str, *, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc

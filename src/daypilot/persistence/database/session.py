"""SQLAlchemy session factory construction."""

from collections.abc import Callable

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_session_factory(engine: Engine) -> Callable[[], Session]:
    """Return a factory that creates a new SQLAlchemy Session on each call."""
    if not isinstance(engine, Engine):
        raise TypeError("engine must be a SQLAlchemy Engine instance.")
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

"""Shared SQLAlchemy declarative base for persistence ORM tables."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass

"""Persistence-specific errors exposed at the repository boundary."""


class PersistenceError(Exception):
    """Base class for failures raised by persistence implementations."""


class EntityNotFoundError(PersistenceError):
    """Raised when an operation requires an aggregate that is not stored."""


class DuplicateEntityError(PersistenceError):
    """Raised when creating an aggregate with an identity already in use."""


class ConcurrencyError(PersistenceError):
    """Reserved for persistence implementations that detect write conflicts."""

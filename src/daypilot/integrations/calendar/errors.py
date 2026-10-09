"""Errors raised while communicating with a calendar provider."""


class CalendarIntegrationError(RuntimeError):
    """A provider operation failed or returned data DayPilot cannot map."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        super().__init__(f"Calendar provider operation {operation!r} failed.")

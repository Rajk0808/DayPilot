"""UTC timestamp conversion helpers for persistence records."""

from datetime import datetime, timedelta, timezone


UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def datetime_to_timestamp_microseconds(value: datetime) -> int:
    """Convert a timezone-aware datetime to exact UTC epoch microseconds."""
    if value.utcoffset() is None:
        raise ValueError("Timestamp must be timezone-aware.")
    delta = value.astimezone(timezone.utc) - UTC_EPOCH
    return (delta.days * 86_400 + delta.seconds) * 1_000_000 + delta.microseconds


def timestamp_microseconds_to_datetime(value: int) -> datetime:
    """Convert UTC epoch microseconds to a timezone-aware UTC datetime."""
    return UTC_EPOCH + timedelta(microseconds=value)

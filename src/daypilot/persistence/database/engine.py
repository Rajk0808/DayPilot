"""SQLAlchemy engine construction."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

from daypilot.persistence.database.config import DatabaseSettings


def create_database_engine(settings: DatabaseSettings) -> Engine:
    """Create an engine without opening a connection or creating schema.

    Supabase transaction-mode pooler connections use ``NullPool`` because
    server-side connection state cannot be assumed to persist between uses.
    """
    if not isinstance(settings, DatabaseSettings):
        raise TypeError("settings must be a DatabaseSettings instance.")

    options: dict[str, object] = {
        "echo": settings.echo,
        "pool_pre_ping": True,
    }
    url = make_url(settings.database_url)
    pgbouncer = url.query.get("pgbouncer")
    if pgbouncer is not None:
        # ``pgbouncer=true`` appears in some hosted PostgreSQL connection
        # strings, but it is a client compatibility hint, not a libpq option.
        # Remove it before passing the URL to psycopg.
        url = url.difference_update_query(["pgbouncer"])
        enabled = str(pgbouncer).strip().lower() in {"1", "true", "yes", "on"}
        driver = url.drivername.partition("+")[2]
        if enabled and driver in {"", "psycopg"}:
            options["connect_args"] = {"prepare_threshold": None}
    if settings.pool_mode == "transaction":
        options["poolclass"] = NullPool
    elif url.get_backend_name() != "sqlite":
        options["pool_size"] = settings.pool_size
        options["max_overflow"] = settings.max_overflow
    return create_engine(url, **options)

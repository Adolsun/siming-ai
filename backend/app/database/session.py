"""Database session management."""
import contextlib

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker

from ..core.config import get_settings
from .write_coordination import install_sqlite_write_coordination

settings = get_settings()

_connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)
engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    echo=False,
    pool_size=20,
    max_overflow=30,
    pool_timeout=10,
    pool_recycle=300,
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _on_connect(dbapi_connection, connection_record):
    if settings.database_url.startswith("sqlite"):
        import sqlite3
        if hasattr(sqlite3, "Connection"):
            # Apply the wait budget before journal setup: setting WAL can itself
            # briefly contend with another process opening the same database.
            dbapi_connection.execute("PRAGMA busy_timeout=30000")
            # WAL is persistent and normally already configured. A transient
            # reader must not make a new connection fail during startup.
            with contextlib.suppress(sqlite3.OperationalError):
                dbapi_connection.execute("PRAGMA journal_mode=WAL")


database_write_coordinator = install_sqlite_write_coordination(
    engine,
    settings.database_url,
    timeout=30,
)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """Yield a database session for dependency injection."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

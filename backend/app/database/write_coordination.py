"""Cross-process coordination for SQLite write transactions.

SQLite already serializes writers internally, but separate Siming desktop and
MCP processes used to enter write transactions independently and frequently
exhaust the short SQLite busy timeout.  This module adds a crash-safe sidecar
file lock around each write transaction while leaving reads concurrent.
"""

from __future__ import annotations

import os
import re
import threading
import time
from pathlib import Path
from typing import Any, BinaryIO

from sqlalchemy import event
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session


class DatabaseWriteLockTimeout(TimeoutError):
    """Raised when another Siming process holds the database writer lease."""


_registry_guard = threading.Lock()
_process_locks: dict[str, threading.Lock] = {}
_WRITE_LEASE_KEY = "siming_database_write_lease"
_SESSION_CONNECTIONS_KEY = "siming_database_write_connections"
_session_events_installed = False
_WRITE_PREFIXES = {
    "ALTER",
    "ATTACH",
    "CREATE",
    "DELETE",
    "DETACH",
    "DROP",
    "INSERT",
    "REINDEX",
    "REPLACE",
    "TRUNCATE",
    "UPDATE",
    "VACUUM",
}


def _process_lock_for(path: Path) -> threading.Lock:
    key = os.path.normcase(str(path.resolve()))
    with _registry_guard:
        lock = _process_locks.get(key)
        if lock is None:
            lock = threading.Lock()
            _process_locks[key] = lock
        return lock


class DatabaseWriteLease:
    """An acquired process-local and operating-system file lock."""

    def __init__(
        self,
        *,
        lock_file: BinaryIO,
        process_lock: threading.Lock,
    ) -> None:
        self._lock_file = lock_file
        self._process_lock = process_lock
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        try:
            self._unlock_file()
        finally:
            try:
                self._lock_file.close()
            finally:
                self._process_lock.release()

    def _unlock_file(self) -> None:
        self._lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)

    def __enter__(self) -> DatabaseWriteLease:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.release()


class DatabaseWriteCoordinator:
    """Acquire a cross-process lease for a SQLite database write."""

    def __init__(self, database_path: Path, *, timeout: float = 30.0) -> None:
        self.database_path = Path(database_path).expanduser().resolve()
        self.lock_path = self.database_path.with_name(
            f"{self.database_path.name}.siming-write.lock"
        )
        self.timeout = max(float(timeout), 0.1)
        self._process_lock = _process_lock_for(self.lock_path)

    def acquire(self, *, timeout: float | None = None) -> DatabaseWriteLease:
        wait_timeout = self.timeout if timeout is None else max(float(timeout), 0.0)
        deadline = time.monotonic() + wait_timeout
        if not self._process_lock.acquire(timeout=wait_timeout):
            raise DatabaseWriteLockTimeout(self._timeout_message())

        lock_file: BinaryIO | None = None
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_file = self.lock_path.open("a+b", buffering=0)
            lock_file.seek(0, os.SEEK_END)
            if lock_file.tell() == 0:
                lock_file.write(b"\0")
            lock_file.seek(0)

            while True:
                try:
                    self._try_lock_file(lock_file)
                    return DatabaseWriteLease(
                        lock_file=lock_file,
                        process_lock=self._process_lock,
                    )
                except OSError as exc:
                    if time.monotonic() >= deadline:
                        raise DatabaseWriteLockTimeout(
                            self._timeout_message()
                        ) from exc
                    time.sleep(min(0.05, max(deadline - time.monotonic(), 0.005)))
        except Exception:
            if lock_file is not None:
                lock_file.close()
            self._process_lock.release()
            raise

    @staticmethod
    def _try_lock_file(lock_file: BinaryIO) -> None:
        lock_file.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _timeout_message(self) -> str:
        return (
            "Timed out waiting for another Siming process to finish writing "
            f"the database: {self.database_path}"
        )


def sqlite_database_path(database_url: str) -> Path | None:
    """Resolve a file-backed SQLite URL, returning ``None`` for other stores."""

    try:
        url = make_url(database_url)
    except Exception:
        return None
    if not url.drivername.startswith("sqlite"):
        return None
    database = url.database
    if not database or database == ":memory:" or database.startswith("file:"):
        return None
    return Path(database).expanduser().resolve()


def is_write_statement(statement: str) -> bool:
    """Return whether a SQL statement can mutate the SQLite database."""

    normalized = statement.lstrip()
    while normalized.startswith("--") or normalized.startswith("/*"):
        if normalized.startswith("--"):
            newline = normalized.find("\n")
            if newline < 0:
                return False
            normalized = normalized[newline + 1 :].lstrip()
        else:
            end = normalized.find("*/")
            if end < 0:
                return False
            normalized = normalized[end + 2 :].lstrip()
    if not normalized:
        return False

    upper = normalized.upper()
    first_word = re.match(r"[A-Z]+", upper)
    if first_word and first_word.group(0) in _WRITE_PREFIXES:
        return True
    if upper.startswith("WITH"):
        return bool(
            re.search(r"\b(?:INSERT|UPDATE|DELETE|REPLACE)\b", upper, re.IGNORECASE)
        )
    if upper.startswith("PRAGMA"):
        # Read-only PRAGMAs are common; assignments change connection/database state.
        return "=" in upper
    return False


def _release_lease_from_info(info: dict[str, Any]) -> None:
    lease = info.pop(_WRITE_LEASE_KEY, None)
    if isinstance(lease, DatabaseWriteLease):
        lease.release()


def _track_session_connection(
    session: Session,
    transaction: Any,
    connection: Any,
) -> None:
    connections = session.info.setdefault(_SESSION_CONNECTIONS_KEY, set())
    connections.add(connection)


def _release_session_write_leases(session: Session) -> None:
    # A savepoint commit/rollback does not end the outer SQLite transaction.
    if session.in_nested_transaction():
        return
    connections = session.info.pop(_SESSION_CONNECTIONS_KEY, set())
    for connection in connections:
        try:
            _release_lease_from_info(connection.info)
        except Exception:
            # Invalidated connections are released defensively by pool check-in.
            continue


def _install_session_release_events() -> None:
    """Release only after DBAPI commit/rollback, before post-commit dispatchers."""

    global _session_events_installed
    if _session_events_installed:
        return
    event.listen(Session, "after_begin", _track_session_connection, insert=True)
    event.listen(Session, "after_commit", _release_session_write_leases, insert=True)
    event.listen(Session, "after_rollback", _release_session_write_leases, insert=True)
    _session_events_installed = True


def install_sqlite_write_coordination(
    engine: Engine,
    database_url: str,
    *,
    timeout: float = 30.0,
) -> DatabaseWriteCoordinator | None:
    """Install transaction-scoped cross-process write locking on an engine."""

    database_path = sqlite_database_path(database_url)
    if database_path is None:
        return None
    existing = getattr(engine, "_siming_write_coordinator", None)
    if isinstance(existing, DatabaseWriteCoordinator):
        return existing

    coordinator = DatabaseWriteCoordinator(database_path, timeout=timeout)
    engine._siming_write_coordinator = coordinator
    _install_session_release_events()

    @event.listens_for(engine, "before_cursor_execute")
    def _before_cursor_execute(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        executemany: bool,
    ) -> None:
        if not is_write_statement(statement):
            return
        info = connection.info
        if _WRITE_LEASE_KEY not in info:
            info[_WRITE_LEASE_KEY] = coordinator.acquire()

    @event.listens_for(engine.pool, "checkin")
    def _after_checkin(dbapi_connection: Any, connection_record: Any) -> None:
        _release_lease_from_info(connection_record.info)

    return coordinator


__all__ = [
    "DatabaseWriteCoordinator",
    "DatabaseWriteLease",
    "DatabaseWriteLockTimeout",
    "install_sqlite_write_coordination",
    "is_write_statement",
    "sqlite_database_path",
]

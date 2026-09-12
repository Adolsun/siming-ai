"""SQLite backup helpers used before runtime schema migrations."""

from __future__ import annotations

import logging
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from .write_coordination import DatabaseWriteCoordinator

logger = logging.getLogger(__name__)
_SIDECARS = ("-wal", "-shm", "-journal")
_FREE_SPACE_RESERVE = 32 * 1024 * 1024
_AUTOMATIC_REASON = r"pre-(?:[0-9][A-Za-z0-9_-]*|sync-[A-Za-z0-9_-]+)"


def sqlite_database_path(database_url: str) -> Path | None:
    """Return a filesystem path for file-backed SQLite URLs."""
    url = make_url(database_url)
    if url.drivername not in {"sqlite", "sqlite+pysqlite"}:
        return None
    database = url.database
    if not database or database == ":memory:" or url.query.get("mode") == "memory":
        return None
    return Path(database).expanduser().resolve()


def _remove_temporary_backup(path: Path) -> None:
    """Remove only this helper's fixed, lock-protected incomplete snapshot."""
    for candidate in (path, *(path.with_name(path.name + suffix) for suffix in _SIDECARS)):
        candidate.unlink(missing_ok=True)


def _verify_backup(path: Path) -> None:
    # The destination is checkpointed into DELETE journal mode before closing.
    # Immutable read creates no WAL/SHM files beside the completed backup.
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as backup:
        result = backup.execute("PRAGMA integrity_check").fetchall()
        if result != [("ok",)]:
            raise sqlite3.DatabaseError("SQLite backup failed its integrity check")


def _retain_latest_automatic_backup(db_path: Path, latest: Path) -> None:
    """Retire generated pre-upgrade/sync snapshots after publishing a verified one.

    Match the full generated filename, including its database stem and timestamp.
    Explicit/manual backups, other databases and filesystem links are not owned
    by this retention policy.
    """
    pattern = re.compile(
        rf"{re.escape(db_path.stem)}\.{_AUTOMATIC_REASON}\."
        rf"\d{{8}}-\d{{6}}(?:-\d{{6}})?{re.escape(db_path.suffix)}"
        rf"(?:\.tmp)?(?:-wal|-shm|-journal)?"
    )
    root = latest.parent.resolve()
    protected = {latest.name, *(latest.name + suffix for suffix in _SIDECARS)}
    for candidate in root.iterdir():
        if candidate.name in protected or not pattern.fullmatch(candidate.name):
            continue
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if candidate.resolve().parent != root:
                continue
            candidate.unlink()
        except FileNotFoundError:
            continue
        except OSError:
            # A locked historical file must not invalidate the newly verified
            # recovery copy. Report it; the next successful backup tries again.
            logger.warning("Could not retire automatic backup: %s", candidate, exc_info=True)


def backup_sqlite_database(
    database_url: str, *, reason: str = "startup", automatic: bool = False
) -> Path | None:
    """Create a consistent SQLite backup, including committed WAL contents.

    SQLite's online backup API is used instead of copying the main file because
    recently committed data may still live in the write-ahead log. Automatic
    upgrade/sync snapshots retain only the latest verified copy. Explicit/manual
    calls remain independent snapshots.
    """
    db_path = sqlite_database_path(database_url)
    if not db_path or not db_path.exists() or db_path.stat().st_size <= 0:
        return None

    backup_dir = db_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    clean_reason = "".join(ch for ch in reason if ch.isalnum() or ch in {"-", "_"})[:40] or "backup"
    if automatic:
        if not re.fullmatch(_AUTOMATIC_REASON, clean_reason):
            raise ValueError("Automatic backups require an upgrade or sync reason")
    else:
        clean_reason = f"manual-{clean_reason}"
    coordinator = DatabaseWriteCoordinator(
        db_path.with_name(f"{db_path.name}.backup"),
        timeout=60,
    )
    # One reusable temporary path also bounds leftovers after a killed process.
    temporary_path = backup_dir / f".{db_path.name}.backup.tmp"
    with coordinator.acquire():
        _remove_temporary_backup(temporary_path)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f")
        backup_path = backup_dir / f"{db_path.stem}.{clean_reason}.{timestamp}{db_path.suffix}"
        try:
            with closing(sqlite3.connect(db_path.as_uri() + "?mode=ro", uri=True)) as source:
                pages = source.execute("PRAGMA page_count").fetchone()[0]
                page_size = source.execute("PRAGMA page_size").fetchone()[0]
                needed = pages * page_size + _FREE_SPACE_RESERVE
                if shutil.disk_usage(backup_dir).free < needed:
                    raise OSError("Not enough free space for a verified SQLite backup")
                with closing(sqlite3.connect(temporary_path)) as destination:
                    source.backup(destination)
                    mode = destination.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                    if str(mode).lower() != "delete":
                        raise sqlite3.DatabaseError("SQLite backup could not be checkpointed")
            _verify_backup(temporary_path)
            temporary_path.replace(backup_path)
        finally:
            _remove_temporary_backup(temporary_path)
        if automatic:
            _retain_latest_automatic_backup(db_path, backup_path)
        return backup_path

"""SQLite online-backup and recovery guarantees."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.database.backup import backup_sqlite_database


def _url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_backup_includes_committed_wal_rows(tmp_path: Path) -> None:
    source = tmp_path / "story.db"
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE chapters (id TEXT PRIMARY KEY, content TEXT)")
        connection.execute("INSERT INTO chapters VALUES ('c1', 'still in wal')")
        connection.commit()

        backup = backup_sqlite_database(_url(source), reason="wal-test")

        assert backup is not None
        with closing(sqlite3.connect(backup)) as restored:
            assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert restored.execute("SELECT content FROM chapters").fetchone()[0] == "still in wal"
            assert restored.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert not list(backup.parent.glob("*-wal"))
        assert not list(backup.parent.glob("*-shm"))
    finally:
        connection.close()


def test_consecutive_backups_do_not_overwrite_each_other(tmp_path: Path) -> None:
    source = tmp_path / "story.db"
    with closing(sqlite3.connect(source)) as connection:
        connection.execute("CREATE TABLE projects (id TEXT PRIMARY KEY)")
        connection.commit()

    first = backup_sqlite_database(_url(source), reason="repeat")
    second = backup_sqlite_database(_url(source), reason="repeat")

    assert first is not None and second is not None
    assert first != second
    assert first.is_file() and second.is_file()


def _create_story(path: Path, title: str = "Original") -> None:
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, title TEXT)")
        db.execute("INSERT INTO projects VALUES ('p1', ?)", (title,))
        db.commit()


def test_automatic_backups_keep_only_latest_and_preserve_manual_and_other_databases(tmp_path):
    source = tmp_path / "story.db"
    other = tmp_path / "other.db"
    _create_story(source)
    _create_story(other, "Other database")
    # Even a version-shaped reason remains explicit/manual without automatic=True.
    manual = backup_sqlite_database(_url(source), reason="pre-3316")
    other_backup = backup_sqlite_database(_url(other), reason="pre-3316", automatic=True)
    first = backup_sqlite_database(_url(source), reason="pre-3316", automatic=True)
    with closing(sqlite3.connect(source)) as db:
        db.execute("UPDATE projects SET title='Latest snapshot'")
        db.commit()
    latest = backup_sqlite_database(_url(source), reason="pre-sync-project", automatic=True)

    assert latest != first and not first.exists()
    assert manual.is_file() and other_backup.is_file()
    assert list(latest.parent.glob("story.pre-*.db")) == [latest]
    with closing(sqlite3.connect(latest)) as db:
        assert db.execute("SELECT title FROM projects").fetchone()[0] == "Latest snapshot"
    with closing(sqlite3.connect(manual)) as db:
        assert db.execute("SELECT title FROM projects").fetchone()[0] == "Original"


def test_failed_verification_keeps_previous_backup_and_cleans_all_temporary_sidecars(
    tmp_path, monkeypatch
):
    source = tmp_path / "story.db"
    _create_story(source)
    previous = backup_sqlite_database(_url(source), reason="pre-3316", automatic=True)
    previous_bytes = previous.read_bytes()

    def reject(path):
        for suffix in ("-wal", "-shm", "-journal"):
            path.with_name(path.name + suffix).write_bytes(b"failed backup residue")
        raise sqlite3.DatabaseError("verification rejected")

    monkeypatch.setattr("app.database.backup._verify_backup", reject)
    with pytest.raises(sqlite3.DatabaseError, match="verification rejected"):
        backup_sqlite_database(_url(source), reason="pre-3317", automatic=True)
    assert list(previous.parent.iterdir()) == [previous]
    assert previous.read_bytes() == previous_bytes


def test_low_disk_space_does_not_replace_the_recovery_backup(tmp_path, monkeypatch):
    source = tmp_path / "story.db"
    _create_story(source)
    previous = backup_sqlite_database(_url(source), reason="pre-3316", automatic=True)
    previous_bytes = previous.read_bytes()
    monkeypatch.setattr(
        "app.database.backup.shutil.disk_usage", lambda _path: SimpleNamespace(free=1)
    )
    with pytest.raises(OSError, match="Not enough free space"):
        backup_sqlite_database(_url(source), reason="pre-3317", automatic=True)
    assert list(previous.parent.iterdir()) == [previous]
    assert previous.read_bytes() == previous_bytes


def test_next_attempt_cleans_killed_process_temporary_files(tmp_path):
    source = tmp_path / "story.db"
    _create_story(source)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    pending = backup_dir / ".story.db.backup.tmp"
    for suffix in ("", "-wal", "-shm", "-journal"):
        pending.with_name(pending.name + suffix).write_bytes(b"interrupted")
    old = backup_dir / "story.pre-332.20260911-012345-123456.db.tmp"
    for suffix in ("", "-wal", "-shm", "-journal"):
        old.with_name(old.name + suffix).write_bytes(b"legacy interrupted copy")

    latest = backup_sqlite_database(_url(source), reason="pre-3317", automatic=True)
    assert list(backup_dir.iterdir()) == [latest]


def test_parallel_automatic_backups_do_not_race_publication_or_retention(tmp_path):
    source = tmp_path / "story.db"
    _create_story(source)
    with ThreadPoolExecutor(max_workers=4) as workers:
        futures = [
            workers.submit(backup_sqlite_database, _url(source), reason="pre-3317", automatic=True)
            for _ in range(4)
        ]
        paths = [future.result(timeout=10) for future in futures]
    remaining = list((tmp_path / "backups").iterdir())
    assert len(remaining) == 1
    assert remaining[0] in paths
    with closing(sqlite3.connect(remaining[0])) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("SELECT title FROM projects").fetchone()[0] == "Original"


def test_retention_does_not_follow_links_or_remove_directories(tmp_path):
    source = tmp_path / "story.db"
    _create_story(source)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    unrelated = tmp_path / "keep.txt"
    unrelated.write_text("Keep this file", encoding="utf-8")
    link = backup_dir / "story.pre-3316.20260911-010000-123456.db"
    try:
        link.symlink_to(unrelated)
    except OSError:
        pytest.skip("Creating symlinks is not permitted on this host")
    directory = backup_dir / "story.pre-3316.20260911-010000-123457.db"
    directory.mkdir()
    (directory / "keep.txt").write_text("Keep this directory", encoding="utf-8")

    backup_sqlite_database(_url(source), reason="pre-3317", automatic=True)
    assert link.is_symlink()
    assert unrelated.read_text(encoding="utf-8") == "Keep this file"
    assert (directory / "keep.txt").is_file()

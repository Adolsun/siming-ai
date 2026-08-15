"""Tests for cross-process SQLite writer coordination."""

import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from app.database.write_coordination import (
    DatabaseWriteCoordinator,
    DatabaseWriteLockTimeout,
    install_sqlite_write_coordination,
    is_write_statement,
    sqlite_database_path,
)


class DatabaseWriteCoordinationTestCase(unittest.TestCase):
    def test_sql_classifier_keeps_reads_concurrent_and_catches_mutations(self):
        self.assertFalse(is_write_statement("SELECT * FROM novels"))
        self.assertFalse(is_write_statement("PRAGMA busy_timeout"))
        self.assertTrue(is_write_statement("UPDATE novels SET title = ?"))
        self.assertTrue(is_write_statement("/* catalog */ INSERT INTO novels VALUES (?)"))
        self.assertTrue(
            is_write_statement("WITH selected AS (SELECT 1) DELETE FROM novels")
        )

    def test_database_url_resolution_ignores_memory_and_non_sqlite_databases(self):
        self.assertIsNone(sqlite_database_path("sqlite:///:memory:"))
        self.assertIsNone(sqlite_database_path("postgresql://localhost/siming"))
        resolved = sqlite_database_path("sqlite:///relative-siming.db")
        self.assertEqual(resolved, Path("relative-siming.db").resolve())

    def test_second_writer_waits_until_first_writer_releases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "novel_agent.db"
            first = DatabaseWriteCoordinator(path, timeout=2.0)
            second = DatabaseWriteCoordinator(path, timeout=2.0)
            first_lease = first.acquire()
            second_acquired = threading.Event()
            finished = threading.Event()

            def _acquire_second():
                with second.acquire():
                    second_acquired.set()
                finished.set()

            thread = threading.Thread(target=_acquire_second)
            thread.start()
            time.sleep(0.1)
            self.assertFalse(second_acquired.is_set())
            first_lease.release()
            self.assertTrue(second_acquired.wait(1.0))
            self.assertTrue(finished.wait(1.0))
            thread.join(timeout=1.0)

    def test_writer_timeout_is_bounded_and_explicit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "novel_agent.db"
            first = DatabaseWriteCoordinator(path, timeout=1.0)
            second = DatabaseWriteCoordinator(path, timeout=0.1)
            with first.acquire(), self.assertRaises(DatabaseWriteLockTimeout):
                second.acquire()

    def test_independent_engines_serialize_write_transactions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "novel_agent.db"
            url = f"sqlite:///{database.as_posix()}"
            first_engine = create_engine(
                url, connect_args={"check_same_thread": False, "timeout": 1}
            )
            second_engine = create_engine(
                url, connect_args={"check_same_thread": False, "timeout": 1}
            )
            install_sqlite_write_coordination(first_engine, url, timeout=2.0)
            install_sqlite_write_coordination(second_engine, url, timeout=2.0)
            try:
                with first_engine.begin() as connection:
                    connection.execute(
                        text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
                    )

                first_connection = first_engine.connect()
                first_transaction = first_connection.begin()
                first_connection.execute(
                    text("INSERT INTO items(value) VALUES ('first')")
                )
                second_finished = threading.Event()
                errors = []

                def _write_second():
                    try:
                        with second_engine.begin() as connection:
                            connection.execute(
                                text("INSERT INTO items(value) VALUES ('second')")
                            )
                    except Exception as exc:  # pragma: no cover - asserted below
                        errors.append(exc)
                    finally:
                        second_finished.set()

                thread = threading.Thread(target=_write_second)
                thread.start()
                time.sleep(0.1)
                self.assertFalse(second_finished.is_set())

                first_transaction.commit()
                first_connection.close()
                self.assertTrue(second_finished.wait(1.5))
                thread.join(timeout=1.0)
                self.assertEqual(errors, [])

                with first_engine.connect() as connection:
                    count = connection.execute(text("SELECT COUNT(*) FROM items")).scalar_one()
                self.assertEqual(count, 2)
            finally:
                first_engine.dispose()
                second_engine.dispose()

    def test_operating_system_lock_is_released_across_processes(self):
        child_code = r"""
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[3])
from app.database.write_coordination import DatabaseWriteCoordinator

lease = DatabaseWriteCoordinator(Path(sys.argv[1]), timeout=2.0).acquire()
Path(sys.argv[2]).write_text("ready", encoding="utf-8")
sys.stdin.readline()
lease.release()
"""
        backend_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "novel_agent.db"
            ready_path = Path(temp_dir) / "ready"
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-c",
                    child_code,
                    str(database),
                    str(ready_path),
                    str(backend_root),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                deadline = time.monotonic() + 5.0
                while (
                    not ready_path.exists()
                    and process.poll() is None
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.02)

                self.assertTrue(ready_path.exists())
                with self.assertRaises(DatabaseWriteLockTimeout):
                    DatabaseWriteCoordinator(database, timeout=0.15).acquire()

                assert process.stdin is not None
                process.stdin.write("\n")
                process.stdin.flush()
                _, stderr = process.communicate(timeout=5.0)
                self.assertEqual(process.returncode, 0, stderr)

                with DatabaseWriteCoordinator(database, timeout=1.0).acquire():
                    pass
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=3.0)

    def test_post_commit_dispatch_can_open_a_second_writer_without_waiting(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "novel_agent.db"
            url = f"sqlite:///{database.as_posix()}"
            first_engine = create_engine(url, connect_args={"check_same_thread": False})
            second_engine = create_engine(url, connect_args={"check_same_thread": False})
            install_sqlite_write_coordination(first_engine, url, timeout=0.3)
            install_sqlite_write_coordination(second_engine, url, timeout=0.3)
            FirstSession = sessionmaker(bind=first_engine)
            SecondSession = sessionmaker(bind=second_engine)
            try:
                with first_engine.begin() as connection:
                    connection.execute(
                        text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
                    )

                def _dispatch_after_commit(session):
                    with SecondSession() as dispatched:
                        dispatched.execute(
                            text("INSERT INTO items(value) VALUES ('dispatched')")
                        )
                        dispatched.commit()

                event.listen(FirstSession, "after_commit", _dispatch_after_commit)
                try:
                    with FirstSession() as authoring:
                        authoring.execute(
                            text("INSERT INTO items(value) VALUES ('authoring')")
                        )
                        authoring.commit()
                finally:
                    event.remove(FirstSession, "after_commit", _dispatch_after_commit)

                with first_engine.connect() as connection:
                    values = connection.execute(
                        text("SELECT value FROM items ORDER BY id")
                    ).scalars().all()
                self.assertEqual(values, ["authoring", "dispatched"])
            finally:
                first_engine.dispose()
                second_engine.dispose()

    def test_nested_savepoint_does_not_release_outer_writer_lease(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "novel_agent.db"
            url = f"sqlite:///{database.as_posix()}"
            first_engine = create_engine(url, connect_args={"check_same_thread": False})
            second_engine = create_engine(url, connect_args={"check_same_thread": False})
            install_sqlite_write_coordination(first_engine, url, timeout=0.2)
            install_sqlite_write_coordination(second_engine, url, timeout=0.1)
            FirstSession = sessionmaker(bind=first_engine)
            SecondSession = sessionmaker(bind=second_engine)
            try:
                with first_engine.begin() as connection:
                    connection.execute(
                        text("CREATE TABLE items (id INTEGER PRIMARY KEY, value TEXT)")
                    )

                with FirstSession() as authoring, authoring.begin():
                    with authoring.begin_nested():
                        authoring.execute(
                            text("INSERT INTO items(value) VALUES ('nested')")
                        )
                    with SecondSession() as competing, self.assertRaises(
                        DatabaseWriteLockTimeout
                    ):
                        competing.execute(
                            text("INSERT INTO items(value) VALUES ('too-early')")
                        )

                with SecondSession() as after_outer_commit:
                    after_outer_commit.execute(
                        text("INSERT INTO items(value) VALUES ('after-commit')")
                    )
                    after_outer_commit.commit()
            finally:
                first_engine.dispose()
                second_engine.dispose()


if __name__ == "__main__":
    unittest.main()

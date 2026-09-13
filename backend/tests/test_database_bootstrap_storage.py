"""Startup must not multiply full database copies when clients reconnect."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from app.database.bootstrap import bootstrap_database


@pytest.mark.parametrize(
    ("current", "head"),
    [
        ("400_future_schema", "300a36_outline_projection_identity"),
        ("300a36_outline_projection_identity", "300a35_relationship_integrity"),
        ("300a19_runtime_readiness", "300a17_chapter_sort_order"),
    ],
)
def test_incompatible_revision_reconnects_do_not_create_backups(
    tmp_path, monkeypatch, current, head
):
    path = tmp_path / "story.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES (?)", (current,))
        db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, title TEXT)")
        db.execute("INSERT INTO projects VALUES ('p1', 'Preserve this story')")
        db.commit()
    before = path.read_bytes()
    monkeypatch.setattr("app.database.bootstrap._head_revision", lambda _config: head)
    url = f"sqlite:///{path.as_posix()}"
    engine = create_engine(url)
    try:
        results = [bootstrap_database(engine, database_url=url) for _ in range(3)]
    finally:
        engine.dispose()

    assert all(result.read_only for result in results)
    assert all(result.schema_revision == current for result in results)
    assert all(result.backup_path is None for result in results)
    assert not list((tmp_path / "backups").glob("*"))
    assert path.read_bytes() == before


def test_stdio_mcp_reconnect_to_future_database_never_copies_it(tmp_path: Path):
    path = tmp_path / "story.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
        db.execute("INSERT INTO alembic_version VALUES ('400_future_schema')")
        db.commit()
    env = _isolated_environment(tmp_path, path)
    script = Path(__file__).resolve().parents[2] / "scripts" / "moshu-mcp-server.py"
    for _ in range(3):
        result = subprocess.run(
            [sys.executable, str(script), "--permission-pack", "readonly_collaboration"],
            input='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
            cwd=tmp_path,
            timeout=20,
        )
        assert result.returncode != 0
        assert "Update Siming and the configured MCP command" in result.stderr
        assert not list((tmp_path / "backups").glob("*"))
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (
            "400_future_schema",
        )


def _isolated_environment(root: Path, path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        DATABASE_URL=f"sqlite:///{path.as_posix()}",
        SIMING_HOME=str(root),
        MOSHU_HOME=str(root),
        NOVEL_AGENT_HOME=str(root),
        SIMING_CONTENT_ROOT=str(root / "projects"),
        SIMING_KEY_FILE=str(root / ".crypto_key"),
        MOSHU_KEY_FILE=str(root / ".crypto_key"),
        NOVEL_AGENT_KEY_FILE=str(root / ".crypto_key"),
        MOSHU_DISABLE_AUTO_MCP_SETUP="1",
        SIMING_ENABLE_LOCAL_RUNTIME="0",
        PYTHONIOENCODING="utf-8",
    )
    return env


def test_parallel_mcp_startups_share_one_migration_backup(tmp_path: Path):
    path = tmp_path / "story.db"
    with closing(sqlite3.connect(path)) as db:
        db.execute("CREATE TABLE projects (id TEXT PRIMARY KEY, title TEXT)")
        db.execute("INSERT INTO projects VALUES ('p1', 'Keep across migration')")
        db.commit()
    env = _isolated_environment(tmp_path, path)
    program = """
import json, time
from dataclasses import asdict
from app.database import bootstrap
from app.database.session import engine
original_backup = bootstrap.backup_sqlite_database
def slow_backup(*args, **kwargs):
    result = original_backup(*args, **kwargs)
    time.sleep(0.3)
    return result
bootstrap.backup_sqlite_database = slow_backup
try:
    print(json.dumps(asdict(bootstrap.bootstrap_database(refresh_current_metadata=False))))
finally:
    engine.dispose()
"""
    processes = []
    try:
        for _ in range(3):
            processes.append(
                subprocess.Popen(
                    [sys.executable, "-c", program],
                    env=env,
                    cwd=Path(__file__).resolve().parents[1],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
            )
        results = []
        for process in processes:
            stdout, stderr = process.communicate(timeout=45)
            assert process.returncode == 0, stderr
            results.append(json.loads(stdout.strip().splitlines()[-1]))
        assert all(not result["read_only"] for result in results), results
        assert [result["mode"] for result in results].count("migrated") == 1
        assert [result["mode"] for result in results].count("ready") == 2
        assert len(list((tmp_path / "backups").glob("*.db"))) == 1
        with closing(sqlite3.connect(path)) as db:
            assert db.execute("SELECT title FROM projects WHERE id='p1'").fetchone() == (
                "Keep across migration",
            )
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=10)

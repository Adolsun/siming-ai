"""Regression tests for the single canonical cataloging launcher."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    APIConfig,
    AgentRun,
    Base,
    CatalogingChapterRun,
    Chapter,
    OperationRun,
    OutlineNode,
    Project,
)
from app.services.cataloging.launcher import (
    AUTO_CHAPTER_WRITE_SOURCE,
    create_and_queue_cataloging_job,
    resolve_write_cataloging_route,
)
from app.services.workspace.tools.chapters import create_chapter, update_chapter


def _database():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def test_unmanaged_mcp_write_creates_api_free_canonical_job():
    engine, db = _database()
    try:
        db.add_all([
            Project(id="project-1", title="Test Novel"),
            Chapter(id="chapter-1", project_id="project-1", title="第一章", content="正文", word_count=2),
        ])
        db.commit()

        job, launch = create_and_queue_cataloging_job(
            db,
            "project-1",
            ["chapter-1"],
            backend_override="external_agent",
            trigger_source=AUTO_CHAPTER_WRITE_SOURCE,
            run_now=True,
        )

        assert job.execution_backend == "external_agent"
        assert job.model is None
        assert job.model_source == "chapter_write:external_agent"
        assert launch["worker_queued"] is False
        assert launch["next_action"] == "continue_external_cataloging"
        assert db.query(CatalogingChapterRun).filter_by(job_id=job.id).one().chapter_id == "chapter-1"
        operation = db.query(OperationRun).filter_by(id=job.operation_id).one()
        assert operation.title == "《第一章》自动建档"
        assert operation.tool_mode == "auto_chapter_write:external_agent"
        assert "立即生成下一章可能影响上下文质量" in operation.current_message
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_new_write_job_cancels_only_superseded_write_job_for_same_chapter():
    engine, db = _database()
    try:
        db.add_all([
            Project(id="project-1", title="Test Novel"),
            Chapter(id="chapter-1", project_id="project-1", title="第一章", content="正文", word_count=2),
        ])
        db.commit()
        first, _ = create_and_queue_cataloging_job(
            db,
            "project-1",
            ["chapter-1"],
            backend_override="external_agent",
            trigger_source=AUTO_CHAPTER_WRITE_SOURCE,
            run_now=False,
        )
        second, launch = create_and_queue_cataloging_job(
            db,
            "project-1",
            ["chapter-1"],
            backend_override="external_agent",
            trigger_source=AUTO_CHAPTER_WRITE_SOURCE,
            run_now=False,
        )

        db.refresh(first)
        assert first.status == "cancelled"
        assert second.status == "queued"
        assert launch["superseded_job_ids"] == [first.id]
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_managed_cli_route_reuses_the_calling_cli_provider():
    engine, db = _database()
    try:
        db.add_all([
            Project(id="project-1", title="Test Novel"),
            OutlineNode(
                id="outline-1",
                project_id="project-1",
                title="第一章",
                node_type="chapter",
            ),
        ])
        run = AgentRun(project_id="project-1", client_name="opencode_cli", source="internal_cli")
        db.add(run)
        db.add(APIConfig(
            provider="opencode_cli",
            provider_type="local_cli",
            api_key_encrypted="",
            default_model="opencode/deepseek-v4-flash-free",
        ))
        db.commit()

        model, backend, provider = resolve_write_cataloging_route(
            db,
            {
                "_context_execution_route": "external_mcp",
                "_source_agent_run_id": run.id,
            },
            project_id="project-1",
        )

        assert model == "opencode_cli:opencode/deepseek-v4-flash-free"
        assert backend == "local_cli_agent"
        assert provider == "opencode_cli"
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_external_run_cannot_spoof_managed_cli_cataloging_route():
    engine, db = _database()
    try:
        db.add(Project(id="project-1", title="Test Novel"))
        run = AgentRun(project_id="project-1", client_name="opencode_cli", source="mcp")
        db.add(run)
        db.add(APIConfig(
            provider="opencode_cli",
            provider_type="local_cli",
            api_key_encrypted="",
            default_model="opencode/deepseek-v4-flash-free",
        ))
        db.commit()

        model, backend, provider = resolve_write_cataloging_route(
            db,
            {
                "_context_execution_route": "external_mcp",
                "_source_agent_run_id": run.id,
            },
            project_id="project-1",
        )

        assert model is None
        assert backend == "external_agent"
        assert provider is None
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_workspace_create_and_content_update_launch_the_canonical_job():
    engine, db = _database()
    try:
        db.add_all([
            Project(id="project-1", title="Test Novel"),
            OutlineNode(
                id="outline-1",
                project_id="project-1",
                title="第一章",
                node_type="chapter",
            ),
        ])
        db.commit()
        launch = {
            "job_id": "cataloging-job-1",
            "auto_started": True,
            "worker_queued": True,
            "next_action": "background_cataloging",
        }
        with patch(
            "app.services.workspace.tools.chapters.create_and_queue_cataloging_job",
            return_value=(MagicMock(id="cataloging-job-1"), launch),
        ) as start:
            created = asyncio.run(create_chapter(db, "project-1", {
                "title": "第一章",
                "content": "门外响起三声叩门。",
                "outline_node_id": "outline-1",
                "skip_style_repair": True,
                "_cataloging_model": "deepseek:test-model",
            }))
            chapter_id = created["data"]["chapter_id"]
            assert created["data"]["cataloging_job"]["job_id"] == "cataloging-job-1"
            assert start.call_count == 1
            assert start.call_args.args[2] == [chapter_id]
            assert start.call_args.kwargs["trigger_source"] == AUTO_CHAPTER_WRITE_SOURCE

            updated = asyncio.run(update_chapter(db, "project-1", {
                "chapter_id": chapter_id,
                "content": "门外响起三声叩门，院中无人应答。",
                "rewrite": True,
                "skip_style_repair": True,
                "_cataloging_model": "deepseek:test-model",
            }))
            assert updated["data"]["cataloging_job"]["job_id"] == "cataloging-job-1"
            assert start.call_count == 2
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()

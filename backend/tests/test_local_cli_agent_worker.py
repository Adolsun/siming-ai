"""Tests for Siming-managed local CLI agent worker contracts."""

import os
import asyncio
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pathlib import Path

from app.database.models import APIConfig, AgentRun, AgentRunEvent, Base, Chapter, Project
from app.services.external_agent.run_service import create_run, update_run_status
from app.services.cataloging.local_cli_agent import _task_text, _turn_stage
from app.services.cataloging.orchestrator import create_cataloging_job
from app.services.local_cli_agent_worker import (
    _extract_opencode_session_id,
    _opencode_recovery_args,
    _run_cli_process,
    start_local_cli_agent_worker,
    write_task_file,
)
from app.services.workspace.registry import registry
from app.services.workspace.tools.local_cli_agent import wait_local_cli_agent_run


class LocalCLIAgentWorkerTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_root = os.environ.get("MOSHU_CONTENT_ROOT")
        os.environ["MOSHU_CONTENT_ROOT"] = self.tmp.name
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        self.Session = sessionmaker(bind=engine)
        self.db = self.Session()

    def tearDown(self):
        self.db.close()
        if self.old_root is None:
            os.environ.pop("MOSHU_CONTENT_ROOT", None)
        else:
            os.environ["MOSHU_CONTENT_ROOT"] = self.old_root
        self.tmp.cleanup()

    def _project(self) -> Project:
        project = Project(title="中文小说", description="测试")
        self.db.add(project)
        self.db.flush()
        return project

    def test_task_file_defines_read_mirror_and_mcp_write_boundary(self):
        project = self._project()
        task_file = write_task_file(
            self.db,
            project,
            run_id="run-1",
            user_request="给第一章建档",
            task_type="cataloging",
            provider="claude_cli",
        )

        text = task_file.read_text(encoding="utf-8")
        self.assertIn(f'project_id="{project.id}"', text)
        self.assertIn("The database is the only authoritative source.", text)
        self.assertIn("The project folder is a read-only mirror", text)
        self.assertIn("Every write/delete/update must use Siming MCP tools", text)
        self.assertIn('phase="merged"', text)
        self.assertIn("Do not call `save_external_cataloging_facts`", text)
        self.assertIn("Preserve the source novel language", text)

    def test_worker_requires_local_cli_config(self):
        project = self._project()
        result = start_local_cli_agent_worker(
            self.db,
            project.id,
            user_request="测试",
            task_type="general",
        )
        self.assertEqual(result["status"], "skipped")
        self.assertIn("CLI", result["detail"])

    def test_registry_exposes_local_cli_agent_tool(self):
        tool = registry.get("start_local_cli_agent_run")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.tool_type, "scheduler")
        self.assertEqual(tool.estimated_cost, "local_cli")
        wait_tool = registry.get("wait_local_cli_agent_run")
        self.assertIsNotNone(wait_tool)
        self.assertEqual(wait_tool.tool_type, "scheduler")

    def test_wait_worker_fails_writing_run_with_only_orphan_mirror_file(self):
        project = self._project()
        folder = Path(self.tmp.name) / "project"
        chapters_dir = folder / "chapters"
        chapters_dir.mkdir(parents=True)
        project.folder_path = str(folder)
        self.db.commit()
        run = create_run(
            self.db,
            project.id,
            source="internal_cli",
            client_name="custom_cli",
            title="writing",
        )
        orphan = chapters_dir / "0001-orphan.md"
        orphan.write_text(
            "---\n"
            '{"id":"orphan-1","title":"Orphan Chapter","word_count":2,"current_version":1}\n'
            "---\n\n"
            "orphan content",
            encoding="utf-8",
        )
        update_run_status(self.db, run.id, "completed", summary="custom_cli completed")

        result = asyncio.run(wait_local_cli_agent_run(
            self.db,
            project.id,
            {
                "run_id": run.id,
                "task_type": "writing",
                "timeout_seconds": 1,
                "poll_seconds": 0.01,
            },
        ))

        self.assertEqual(result["status"], "error")
        self.assertIn("数据库", result["detail"])
        orphans = result["data"]["validation"]["orphan_chapter_files"]
        self.assertEqual(orphans[0]["path"], "chapters/0001-orphan.md")

    def test_wait_worker_rejects_preexisting_chapter_for_target_outline(self):
        project = self._project()
        old_time = datetime.utcnow() - timedelta(minutes=5)
        chapter = Chapter(
            project_id=project.id,
            outline_node_id="outline-1",
            title="Existing Chapter",
            content="existing content",
            created_at=old_time,
            updated_at=old_time,
        )
        self.db.add(chapter)
        self.db.commit()
        run = create_run(
            self.db,
            project.id,
            source="internal_cli",
            client_name="opencode_cli",
            title="writing",
        )
        update_run_status(self.db, run.id, "completed", summary="opencode_cli completed")

        result = asyncio.run(wait_local_cli_agent_run(
            self.db,
            project.id,
            {
                "run_id": run.id,
                "task_type": "writing",
                "outline_node_id": "outline-1",
                "timeout_seconds": 1,
                "poll_seconds": 0.01,
            },
        ))

        self.assertEqual(result["status"], "error")
        self.assertEqual(result["data"]["validation"]["chapters"], [])

    def test_start_worker_enables_opencode_warn_logs(self):
        project = self._project()
        self.db.add(APIConfig(
            provider="opencode_cli",
            provider_type="local_cli",
            api_key_encrypted="",
            default_model="opencode/deepseek-v4-flash-free",
            cli_command="opencode",
            cli_args='["run","--pure","{prompt}"]',
            is_global_default=True,
        ))
        self.db.commit()
        created_coroutines = []

        def capture_task(coroutine):
            created_coroutines.append(coroutine)

            class DummyTask:
                pass

            return DummyTask()

        with unittest.mock.patch(
            "app.services.local_cli_agent_worker.asyncio.create_task",
            side_effect=capture_task,
        ):
            result = start_local_cli_agent_worker(
                self.db,
                project.id,
                user_request="test",
                task_type="general",
            )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(created_coroutines), 1)
        coroutine = created_coroutines[0]
        try:
            args = coroutine.cr_frame.f_locals["args"]
            self.assertEqual(args[:4], ["--print-logs", "--log-level", "WARN", "run"])
            self.assertEqual(args[args.index("--file") + 1], result["data"]["task_file"])
            self.assertEqual(args[args.index("--dir") + 1], result["data"]["project_folder"])
            self.assertIn(result["data"]["run_id"], args[args.index("--title") + 1])
        finally:
            coroutine.close()

    def test_opencode_recovery_continues_same_session_without_reusing_title(self):
        output = '{"type":"text","sessionID":"ses-writing-2","part":{"text":"chapter"}}'
        self.assertEqual(_extract_opencode_session_id(output), "ses-writing-2")

        args = [
            "run",
            "--format",
            "json",
            "--file",
            "task.md",
            "--title",
            "Siming writing run-2",
            "initial prompt",
        ]
        recovered = _opencode_recovery_args(
            args,
            original_prompt="initial prompt",
            session_id="ses-writing-2",
        )

        self.assertEqual(recovered[recovered.index("--session") + 1], "ses-writing-2")
        self.assertNotIn("--title", recovered)
        self.assertNotIn("initial prompt", recovered)
        self.assertIn("create_chapter", recovered[-1])

    def test_worker_auto_continues_opencode_writing_session_without_a_chapter(self):
        project = self._project()
        run = create_run(
            self.db,
            project.id,
            source="internal_cli",
            client_name="opencode_cli",
            title="writing",
        )
        self.db.commit()

        class DummyProcess:
            returncode = 0

        spawn = unittest.mock.AsyncMock(side_effect=[DummyProcess(), DummyProcess()])
        communicate = unittest.mock.AsyncMock(side_effect=[
            (b'{"type":"text","sessionID":"ses-writing-2"}', b""),
            (b'{"type":"step_finish","sessionID":"ses-writing-2"}', b""),
        ])
        with (
            unittest.mock.patch(
                "app.services.local_cli_agent_worker.SessionLocal",
                self.Session,
            ),
            unittest.mock.patch(
                "app.services.local_cli_agent_worker.asyncio.create_subprocess_exec",
                spawn,
            ),
            unittest.mock.patch(
                "app.services.local_cli_agent_worker.communicate_with_cli_quota_detection",
                communicate,
            ),
            unittest.mock.patch(
                "app.services.local_cli_agent_worker._has_fresh_writing_chapter",
                return_value=False,
            ),
        ):
            asyncio.run(_run_cli_process(
                run_id=run.id,
                project_id=project.id,
                provider="opencode_cli",
                command="opencode",
                args=["run", "--title", "Siming writing run-2", "initial prompt"],
                stdin_text=None,
                cwd=self.tmp.name,
                task_type="writing",
                prompt="initial prompt",
            ))

        self.assertEqual(spawn.await_count, 2)
        recovery_args = list(spawn.await_args_list[1].args[1:])
        self.assertEqual(recovery_args[recovery_args.index("--session") + 1], "ses-writing-2")
        self.assertNotIn("--title", recovery_args)
        self.db.expire_all()
        refreshed = self.db.query(AgentRun).filter(AgentRun.id == run.id).first()
        self.assertEqual(refreshed.status, "completed")
        self.assertTrue(any(event.event_type == "recovery_started" for event in refreshed.events))

    def test_cataloging_task_reads_chapter_file_and_writes_through_mcp(self):
        project = self._project()
        chapter = Chapter(
            project_id=project.id,
            title="第一章 旧门",
            content="这段正文不应被复制进 CLI 任务文件。",
        )
        self.db.add(chapter)
        self.db.commit()
        job = create_cataloging_job(
            self.db,
            project.id,
            "auto",
            "opencode_cli:opencode/deepseek-v4-flash-free",
            [chapter.id],
            execution_backend="local_cli_agent",
        )
        run = job.chapter_runs[0]
        project_folder = Path(self.tmp.name) / "project"
        chapter_file = project_folder / "chapters" / "0001.md"

        task = _task_text(
            job=job,
            run=run,
            agent_run_id="agent-run-1",
            provider="opencode_cli",
            project=project,
            project_folder=project_folder,
            chapter=chapter,
            chapter_file=chapter_file,
            stage="merged",
        )

        self.assertIn(str(chapter_file), task)
        self.assertIn("include_content=false", task)
        self.assertIn("include_context_indexes=false", task)
        self.assertIn('phase="merged"', task)
        self.assertIn("save_external_cataloging_candidates", task)
        self.assertIn("Do not call `save_external_cataloging_facts`", task)
        self.assertIn("所有事实、候选和应用操作必须调用 Siming MCP 工具", task)
        self.assertIn("report_agent_progress", task)
        self.assertNotIn(chapter.content, task)
        self.assertEqual(_turn_stage(run, "auto"), "merged")

        run.status = "facts_saved"
        self.assertEqual(_turn_stage(run, "auto"), "candidates")
        run.status = "awaiting_confirmation"
        self.assertEqual(_turn_stage(run, "auto"), "apply")

    def test_worker_marks_run_failed_when_cli_reports_quota(self):
        project = self._project()
        run = create_run(
            self.db,
            project.id,
            source="internal_cli",
            client_name="custom_cli",
            title="quota test",
        )
        self.db.commit()

        with unittest.mock.patch("app.services.local_cli_agent_worker.SessionLocal", self.Session):
            asyncio.run(_run_cli_process(
                run_id=run.id,
                project_id=project.id,
                provider="custom_cli",
                command=sys.executable,
                args=["-c", "print('HTTP 429 Too Many Requests: quota exceeded')"],
                stdin_text=None,
                cwd=self.tmp.name,
            ))

        self.db.expire_all()
        refreshed = self.db.query(AgentRun).filter(AgentRun.id == run.id).first()
        event = (
            self.db.query(AgentRunEvent)
            .filter(AgentRunEvent.run_id == run.id, AgentRunEvent.status == "error")
            .order_by(AgentRunEvent.sequence.desc())
            .first()
        )
        self.assertEqual(refreshed.status, "failed")
        self.assertIn("额度/限额", refreshed.summary)
        self.assertIn("额度/限额", event.message)

    def test_worker_aborts_retrying_quota_process_before_timeout(self):
        project = self._project()
        run = create_run(
            self.db,
            project.id,
            source="internal_cli",
            client_name="custom_cli",
            title="retrying quota test",
        )
        self.db.commit()
        code = (
            "import time; "
            "print('Free usage exceeded, subscribe to Go [retrying in 9h 28m attempt #1]', flush=True); "
            "time.sleep(5)"
        )

        started = time.monotonic()
        with unittest.mock.patch("app.services.local_cli_agent_worker.SessionLocal", self.Session):
            asyncio.run(_run_cli_process(
                run_id=run.id,
                project_id=project.id,
                provider="custom_cli",
                command=sys.executable,
                args=["-c", code],
                stdin_text=None,
                cwd=self.tmp.name,
            ))

        self.assertLess(time.monotonic() - started, 3)
        self.db.expire_all()
        refreshed = self.db.query(AgentRun).filter(AgentRun.id == run.id).first()
        event = (
            self.db.query(AgentRunEvent)
            .filter(AgentRunEvent.run_id == run.id, AgentRunEvent.status == "error")
            .order_by(AgentRunEvent.sequence.desc())
            .first()
        )
        self.assertEqual(refreshed.status, "failed")
        self.assertIn("Free usage exceeded", refreshed.summary)
        self.assertIn("Free usage exceeded", event.message)

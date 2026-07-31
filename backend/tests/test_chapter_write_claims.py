"""Regression tests for durable chapter-write reservations."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    AssistantRun,
    AssistantRunStep,
    Base,
    Chapter,
    ChapterWriteClaim,
    OperationRun,
    OutlineNode,
    Project,
)
from app.services.agent.planner import build_plan_from_intent, detect_intent
from app.services.operation_runtime import activate_operation
from app.services.workspace.idempotency import (
    acquire_chapter_write_claim,
    check_idempotency,
    complete_chapter_write_claim,
    fail_chapter_write_claim,
)
from app.services.workspace.run_recovery import resume_run
from app.services.workspace.tools.chapters import create_chapter, update_chapter


class ChapterWriteClaimTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)
        self.db = self.Session()
        self.project = Project(title="幂等写章测试")
        self.db.add(self.project)
        self.db.flush()
        self.outline = OutlineNode(
            project_id=self.project.id,
            node_type="chapter",
            title="第一章 测试",
        )
        self.db.add(self.outline)
        self.db.commit()

    def tearDown(self) -> None:
        self.db.close()
        Base.metadata.drop_all(bind=self.engine)
        self.engine.dispose()

    def test_running_claim_blocks_then_failed_claim_can_be_reacquired(self) -> None:
        key = f"create_chapter:{self.project.id}:{self.outline.id}"
        target_key = f"project:{self.project.id}:outline:{self.outline.id}"
        first = acquire_chapter_write_claim(
            self.db, project_id=self.project.id, target_key=target_key, idempotency_key=key
        )
        second = acquire_chapter_write_claim(
            self.db, project_id=self.project.id, target_key=target_key, idempotency_key=key
        )

        self.assertEqual(first["state"], "acquired")
        self.assertEqual(second["state"], "running")
        self.assertEqual(second["result"]["status"], "blocked")

        fail_chapter_write_claim(
            self.db,
            first["claim_id"],
            first["claim_token"],
            error="network interrupted",
        )
        retry = acquire_chapter_write_claim(
            self.db, project_id=self.project.id, target_key=target_key, idempotency_key=key
        )
        self.assertEqual(retry["state"], "acquired")
        self.assertNotEqual(first["claim_token"], retry["claim_token"])

        self.assertFalse(complete_chapter_write_claim(
            self.db,
            first["claim_id"],
            first["claim_token"],
            chapter_id="stale-chapter",
            result={"status": "ok"},
        ))
        claim = self.db.get(ChapterWriteClaim, retry["claim_id"])
        self.db.refresh(claim)
        self.assertEqual(claim.status, "running")
        self.assertEqual(claim.claim_token, retry["claim_token"])

    def test_target_mutex_blocks_a_different_rewrite_request(self) -> None:
        target_key = f"project:{self.project.id}:outline:{self.outline.id}"
        first = acquire_chapter_write_claim(
            self.db,
            project_id=self.project.id,
            target_key=target_key,
            idempotency_key=f"rewrite_chapter:{self.project.id}:{self.outline.id}:request-1",
        )
        second = acquire_chapter_write_claim(
            self.db,
            project_id=self.project.id,
            target_key=target_key,
            idempotency_key=f"rewrite_chapter:{self.project.id}:{self.outline.id}:request-2",
        )

        self.assertEqual(first["state"], "acquired")
        self.assertEqual(second["state"], "running")
        self.assertEqual(second["claim_id"], first["claim_id"])

    def test_same_operation_can_continue_its_reserved_target(self) -> None:
        operation = OperationRun(source_kind="test", source_id="claim-owner", title="claim")
        self.db.add(operation)
        self.db.flush()
        run = AssistantRun(project_id=self.project.id, operation_id=operation.id)
        self.db.add(run)
        self.db.commit()
        target_key = f"project:{self.project.id}:outline:{self.outline.id}"

        with activate_operation(operation.id):
            first = acquire_chapter_write_claim(
                self.db,
                project_id=self.project.id,
                target_key=target_key,
                idempotency_key=f"rewrite_chapter:{self.project.id}:{self.outline.id}:same-owner",
            )
            continued = acquire_chapter_write_claim(
                self.db,
                project_id=self.project.id,
                target_key=target_key,
                idempotency_key=f"rewrite_chapter:{self.project.id}:{self.outline.id}:same-owner",
            )

        self.assertEqual(continued["state"], "acquired")
        self.assertEqual(continued["claim_id"], first["claim_id"])
        self.assertEqual(continued["claim_token"], first["claim_token"])

    async def test_repeated_create_returns_the_same_non_empty_chapter(self) -> None:
        args = {
            "title": "第一章 测试",
            "content": "这是一次完整且可保存的章节正文。",
            "outline_node_id": self.outline.id,
            "skip_style_repair": True,
        }
        first = await create_chapter(self.db, self.project.id, args)
        second = await create_chapter(self.db, self.project.id, args)

        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(first["data"]["chapter_id"], second["data"]["chapter_id"])
        self.assertEqual(
            self.db.query(Chapter)
            .filter(Chapter.project_id == self.project.id, Chapter.outline_node_id == self.outline.id)
            .count(),
            1,
        )
        claim = self.db.query(ChapterWriteClaim).one()
        self.assertEqual(claim.status, "completed")

    async def test_existing_empty_chapter_is_filled_instead_of_duplicated(self) -> None:
        empty = Chapter(
            project_id=self.project.id,
            outline_node_id=self.outline.id,
            title="第一章 测试",
            content="",
            word_count=0,
        )
        self.db.add(empty)
        self.db.commit()
        empty_id = empty.id

        result = await create_chapter(
            self.db,
            self.project.id,
            {
                "title": "第一章 测试",
                "content": "AI 生成的有效正文。",
                "outline_node_id": self.outline.id,
                "skip_style_repair": True,
            },
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["data"]["chapter_id"], empty_id)
        self.assertTrue(result["data"]["reused_empty_chapter"])
        self.assertEqual(self.db.query(Chapter).count(), 1)
        self.assertGreater(self.db.get(Chapter, empty_id).word_count, 0)

    async def test_rewrite_request_retries_once_without_duplicate_version(self) -> None:
        chapter = Chapter(
            project_id=self.project.id,
            outline_node_id=self.outline.id,
            title=self.outline.title,
            content="初始正文",
            word_count=4,
            current_version=1,
        )
        self.db.add(chapter)
        self.db.commit()

        first_args = {
            "outline_node_id": self.outline.id,
            "content": "第一次重写后的完整正文。",
            "rewrite": True,
            "rewrite_request_id": "rewrite-request-1",
            "skip_style_repair": True,
        }
        first = await update_chapter(self.db, self.project.id, first_args)
        self.db.commit()
        replay = await update_chapter(self.db, self.project.id, first_args)
        self.db.commit()

        self.db.refresh(chapter)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["data"]["current_version"], 2)
        self.assertTrue(replay["data"]["idempotent_replay"])
        self.assertEqual(chapter.current_version, 2)
        self.assertEqual(self.db.query(Chapter).count(), 1)

        second = await update_chapter(self.db, self.project.id, {
            **first_args,
            "content": "第二次明确重写后的正文。",
            "rewrite_request_id": "rewrite-request-2",
        })
        self.db.commit()
        self.db.refresh(chapter)
        self.assertEqual(second["data"]["current_version"], 3)
        self.assertEqual(chapter.current_version, 3)
        self.assertEqual(self.db.query(Chapter).count(), 1)

    def test_rewrite_intent_uses_update_chapter_but_normal_write_does_not(self) -> None:
        quality_intent = detect_intent("用质量模式重写第一章正文")
        self.assertIsNotNone(quality_intent)
        self.assertTrue(quality_intent["rewrite"])
        quality_plan = build_plan_from_intent(
            quality_intent,
            outline_node_id=self.outline.id,
        )
        self.assertEqual(quality_plan.steps["create_chapter"].tool, "update_chapter")
        self.assertTrue(quality_plan.steps["create_chapter"].args["rewrite"])

        fast_intent = detect_intent("重写本章")
        self.assertTrue(fast_intent["rewrite"])
        fast_plan = build_plan_from_intent(fast_intent, outline_node_id=self.outline.id)
        self.assertEqual(fast_plan.steps["create_chapter"].tool, "update_chapter")

        normal_intent = detect_intent("写第一章正文")
        self.assertFalse(normal_intent["rewrite"])
        normal_plan = build_plan_from_intent(normal_intent, outline_node_id=self.outline.id)
        self.assertEqual(normal_plan.steps["create_chapter"].tool, "create_chapter")

    async def test_existing_non_empty_chapter_wins_over_older_empty_duplicate(self) -> None:
        empty = Chapter(
            project_id=self.project.id,
            outline_node_id=self.outline.id,
            title="第一章 测试",
            content="",
            word_count=0,
        )
        existing = Chapter(
            project_id=self.project.id,
            outline_node_id=self.outline.id,
            title="第一章 已有正文",
            content="这是已经保存的正文。",
            word_count=10,
        )
        self.db.add_all([empty, existing])
        self.db.commit()

        result = await create_chapter(
            self.db,
            self.project.id,
            {
                "title": "第一章 测试",
                "content": "不应覆盖或制造第二份正文。",
                "outline_node_id": self.outline.id,
                "skip_style_repair": True,
            },
        )

        self.assertEqual(result["data"]["chapter_id"], existing.id)
        self.assertEqual(self.db.get(Chapter, empty.id).content, "")
        self.assertEqual(self.db.query(Chapter).count(), 2)

    async def test_chapter_and_completed_claim_roll_back_together(self) -> None:
        from unittest.mock import patch

        with (
            patch(
                "app.services.workspace.tools.chapters.commit_session",
                side_effect=RuntimeError("commit boundary failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "commit boundary failed"),
        ):
            await create_chapter(
                self.db,
                self.project.id,
                {
                    "title": "第一章 测试",
                    "content": "这段正文必须和幂等完成状态一起提交。",
                    "outline_node_id": self.outline.id,
                    "skip_style_repair": True,
                },
            )

        self.assertEqual(self.db.query(Chapter).count(), 0)
        claim = self.db.query(ChapterWriteClaim).one()
        self.assertEqual(claim.status, "failed")

    async def test_blank_ai_content_never_creates_a_chapter(self) -> None:
        result = await create_chapter(
            self.db,
            self.project.id,
            {
                "title": "第一章 测试",
                "content": "   ",
                "outline_node_id": self.outline.id,
                "skip_style_repair": True,
            },
        )
        self.assertEqual(result["status"], "error")
        self.assertEqual(self.db.query(Chapter).count(), 0)
        self.assertEqual(self.db.query(ChapterWriteClaim).one().status, "failed")

    async def test_plan_injected_claim_is_used_without_operation_context(self) -> None:
        key = f"create_chapter:{self.project.id}:{self.outline.id}"
        target_key = f"project:{self.project.id}:outline:{self.outline.id}"
        reservation = acquire_chapter_write_claim(
            self.db,
            project_id=self.project.id,
            target_key=target_key,
            idempotency_key=key,
        )

        result = await create_chapter(
            self.db,
            self.project.id,
            {
                "title": self.outline.title,
                "content": "由已预占计划安全写入的正文。",
                "outline_node_id": self.outline.id,
                "skip_style_repair": True,
                "_chapter_target_key": target_key,
                "_chapter_idempotency_key": key,
                "_chapter_claim_id": reservation["claim_id"],
                "_chapter_claim_token": reservation["claim_token"],
            },
        )

        self.assertEqual(result["status"], "ok")
        claim = self.db.get(ChapterWriteClaim, reservation["claim_id"])
        self.assertEqual(claim.status, "completed")

    async def test_invalid_injected_claim_never_writes(self) -> None:
        key = f"create_chapter:{self.project.id}:{self.outline.id}"
        target_key = f"project:{self.project.id}:outline:{self.outline.id}"
        reservation = acquire_chapter_write_claim(
            self.db,
            project_id=self.project.id,
            target_key=target_key,
            idempotency_key=key,
        )

        result = await create_chapter(
            self.db,
            self.project.id,
            {
                "title": self.outline.title,
                "content": "不得写入的正文。",
                "outline_node_id": self.outline.id,
                "skip_style_repair": True,
                "_chapter_target_key": target_key,
                "_chapter_idempotency_key": key,
                "_chapter_claim_id": reservation["claim_id"],
                "_chapter_claim_token": "stale-token",
            },
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(self.db.query(Chapter).count(), 0)

    async def test_forged_internal_keys_cannot_bypass_canonical_target_mutex(self) -> None:
        canonical_key = f"create_chapter:{self.project.id}:{self.outline.id}"
        canonical_target = f"project:{self.project.id}:outline:{self.outline.id}"
        acquire_chapter_write_claim(
            self.db,
            project_id=self.project.id,
            target_key=canonical_target,
            idempotency_key=canonical_key,
        )

        result = await create_chapter(
            self.db,
            self.project.id,
            {
                "title": self.outline.title,
                "content": "伪造内部键也不得绕过同一大纲的占用。",
                "outline_node_id": self.outline.id,
                "skip_style_repair": True,
                "_chapter_target_key": "project:forged:outline:other",
                "_chapter_idempotency_key": "create_chapter:forged:other",
            },
        )

        self.assertEqual(result["status"], "blocked")
        self.assertEqual(self.db.query(Chapter).count(), 0)

    def test_completed_claim_replay_is_pinned_to_claim_chapter(self) -> None:
        first = Chapter(
            project_id=self.project.id,
            outline_node_id=self.outline.id,
            title="第一章 正确章节",
            content="正确正文",
            word_count=4,
        )
        second = Chapter(
            project_id=self.project.id,
            title="第二章 错误回放目标",
            content="另一份正文",
            word_count=5,
        )
        self.db.add_all([first, second])
        self.db.commit()
        key = f"create_chapter:{self.project.id}:{self.outline.id}"
        reservation = acquire_chapter_write_claim(
            self.db,
            project_id=self.project.id,
            target_key=f"project:{self.project.id}:outline:{self.outline.id}",
            idempotency_key=key,
        )
        self.assertTrue(complete_chapter_write_claim(
            self.db,
            reservation["claim_id"],
            reservation["claim_token"],
            chapter_id=first.id,
            result={
                "tool": "create_chapter",
                "status": "ok",
                "data": {"chapter_id": second.id, "title": second.title},
            },
        ))
        self.db.commit()

        replay = check_idempotency(self.db, self.project.id, key)

        self.assertEqual(replay["data"]["chapter_id"], first.id)
        self.assertEqual(replay["data"]["title"], first.title)

    async def test_cancelled_durable_operation_fences_final_create(self) -> None:
        operation = OperationRun(
            source_kind="assistant",
            source_id="cancel-fence",
            title="cancel fence",
            status="running",
        )
        self.db.add(operation)
        self.db.flush()
        run = AssistantRun(project_id=self.project.id, operation_id=operation.id)
        self.db.add(run)
        self.db.commit()
        key = f"create_chapter:{self.project.id}:{self.outline.id}"
        target = f"project:{self.project.id}:outline:{self.outline.id}"
        with activate_operation(operation.id):
            reservation = acquire_chapter_write_claim(
                self.db,
                project_id=self.project.id,
                target_key=target,
                idempotency_key=key,
            )
            operation.status = "cancelled"
            self.db.commit()
            self.assertFalse(complete_chapter_write_claim(
                self.db,
                reservation["claim_id"],
                reservation["claim_token"],
                chapter_id="must-not-complete",
                result={"status": "ok"},
            ))
            with self.assertRaises(asyncio.CancelledError):
                await create_chapter(
                    self.db,
                    self.project.id,
                    {
                        "title": self.outline.title,
                        "content": "取消后绝不能写入的正文。",
                        "outline_node_id": self.outline.id,
                        "skip_style_repair": True,
                        "_chapter_claim_id": reservation["claim_id"],
                        "_chapter_claim_token": reservation["claim_token"],
                    },
                )

        self.assertEqual(self.db.query(Chapter).count(), 0)
        claim = self.db.get(ChapterWriteClaim, reservation["claim_id"])
        self.assertEqual(claim.status, "cancelled")

    async def test_workspace_update_never_blanks_existing_chapter(self) -> None:
        chapter = Chapter(
            project_id=self.project.id,
            outline_node_id=self.outline.id,
            title=self.outline.title,
            content="保留正文",
            word_count=4,
        )
        self.db.add(chapter)
        self.db.commit()

        result = await update_chapter(
            self.db,
            self.project.id,
            {"chapter_id": chapter.id, "content": "   ", "skip_style_repair": True},
        )

        self.assertEqual(result["status"], "error")
        self.db.refresh(chapter)
        self.assertEqual(chapter.content, "保留正文")

    def test_historical_step_replay_requires_existing_non_empty_chapter(self) -> None:
        key = f"create_chapter:{self.project.id}:{self.outline.id}:legacy"
        run = AssistantRun(project_id=self.project.id, status="completed")
        self.db.add(run)
        self.db.flush()
        step = AssistantRunStep(
            run_id=run.id,
            project_id=self.project.id,
            tool="create_chapter",
            status="ok",
            idempotency_key=key,
            result_json='{"tool":"create_chapter","status":"ok","data":{"chapter_id":"missing"}}',
        )
        self.db.add(step)
        self.db.commit()

        self.assertIsNone(check_idempotency(self.db, self.project.id, key))

    async def test_create_rejects_missing_cross_project_and_non_chapter_outlines(self) -> None:
        volume = OutlineNode(
            project_id=self.project.id,
            node_type="volume",
            title="第一卷",
        )
        other_project = Project(title="另一作品")
        self.db.add_all([volume, other_project])
        self.db.flush()
        foreign_chapter = OutlineNode(
            project_id=other_project.id,
            node_type="chapter",
            title="第一章 外部",
        )
        self.db.add(foreign_chapter)
        self.db.commit()

        for outline_id in (None, volume.id, foreign_chapter.id):
            result = await create_chapter(self.db, self.project.id, {
                "title": "第一章 非法目标",
                "content": "不得保存的正文",
                "outline_node_id": outline_id,
                "skip_style_repair": True,
            })
            self.assertEqual(result["status"], "error")
        self.assertEqual(self.db.query(Chapter).count(), 0)

    @patch("app.services.workspace.run_recovery.execute_workspace_action", new_callable=AsyncMock)
    async def test_interrupted_assistant_step_can_resume(self, execute: AsyncMock) -> None:
        execute.return_value = {"tool": "test_tool", "status": "ok", "detail": "resumed"}
        run = AssistantRun(project_id=self.project.id, status="interrupted")
        self.db.add(run)
        self.db.flush()
        step = AssistantRunStep(
            run_id=run.id,
            project_id=self.project.id,
            tool="test_tool",
            status="interrupted",
            request_json="{}",
        )
        self.db.add(step)
        self.db.commit()

        results = await resume_run(self.db, run.id)

        self.assertEqual(len(results), 1)
        self.db.refresh(run)
        self.assertEqual(run.status, "completed")


if __name__ == "__main__":
    unittest.main()

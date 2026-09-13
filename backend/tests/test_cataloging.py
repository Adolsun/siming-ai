"""Regression tests for the project cataloging service layer."""

import asyncio
import json
import os
import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import ValidationError
from app.database.models import (
    AgentRun,
    Base,
    CatalogingApplyLog,
    CatalogingCandidate,
    CatalogingChapterRun,
    CatalogingFact,
    CatalogingJob,
    Chapter,
    ChapterGovernanceReview,
    ChapterSummary,
    Character,
    CharacterAIConfig,
    CharacterAlias,
    CharacterRelationship,
    CharacterTimeline,
    CharacterVersion,
    ContentSyncJob,
    Foreshadowing,
    NarrativeDebt,
    OutlineNode,
    OperationRun,
    Project,
    WorldbuildingEntry,
    WorldbuildingTimeline,
)
from tests.cataloging_plan_fixtures import apply_fixture_plan as apply_candidates_for_run, complete_fixture_plan
from app.services.cataloging.candidate_io import candidate_has_usable_summary, candidate_payload
from app.services.cataloging.candidate_validation import inspect_candidate_coverage
from app.services.cataloging.archive_reader import read_cataloging_archive
from app.services.cataloging.constants import CATALOGING_STAGE_MAX_ATTEMPTS
from app.services.context_builders import _build_world_context
from app.services.cataloging.job_control import (
    cancel_job,
    first_blocking_run,
    mark_run_skipped,
    pause_job,
    reconcile_cataloging_operation_projections,
    refresh_job_progress,
    reset_run_for_retry,
    resume_job,
)
from app.services.cataloging.manual_ops import create_manual_candidate, has_usable_chapter_summary, recover_failed_run_for_review
from app.services.cataloging.orchestrator import create_cataloging_job
from app.services.cataloging.projection import job_to_dict
from app.services.cataloging import orchestrator as cataloging_orchestrator
from app.services.cataloging.background_compactor import merge_background
from app.services.cataloging.merge import merge_text
from app.services.cataloging.worldbuilding_ops import _normalize_dimension
from app.services.character_merge_service import build_character_merge_preview, find_duplicate_character_candidates, merge_characters
from app.routers.cataloging import recover_current_cataloging_chapter


def complete_summary_payload(
    summary_text: str,
    *,
    scene_count: int = 1,
    characters: list[str] | None = None,
    worldbuilding: list[str] | None = None,
    relationships: list[dict] | None = None,
    character_profiles: list[str] | None = None,
    narrative_state: dict | None = None,
    **extra,
) -> dict:
    return {
        "summary_text": summary_text,
        "scenes": ["fixture scene"] * scene_count,
        "character_bindings": [], "worldbuilding_bindings": [],
        "coverage_manifest": {
            "scene_count": scene_count,
            "characters": characters or [],
            "worldbuilding": worldbuilding or [],
            "relationships": relationships or [],
            "character_profiles": character_profiles or [],
        },
        "narrative_state": narrative_state or {
            "events": [],
            "timeline_events": [],
            "foreshadowing_planted": [],
            "foreshadowing_resolved": [],
            "storyline_progress": [],
            "new_storylines": [],
            "reader_known_facts": [],
            "character_known_facts": [],
            "unresolved_actions": [],
        },
        "narrative_review": {
            "source": "provided",
            "outcome": "assessed",
            "evidence": "test fixture",
        },
        **extra,
    }


class CatalogingServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def test_job_history_paginates_past_twenty_without_cross_project_rows(self):
        from datetime import datetime
        from app.routers.cataloging import list_cataloging_jobs

        with self.Session() as db:
            project = Project(title="Long catalog history")
            other = Project(title="Other owner")
            db.add_all([project, other])
            db.flush()
            same_time = datetime(2026, 8, 31, 12, 0)
            identities = [f"job-{number:03}" for number in range(45)]
            db.add_all([CatalogingJob(id=identity, project_id=project.id, created_at=same_time)
                        for identity in identities])
            db.add(CatalogingJob(id="other-job", project_id=other.id, created_at=same_time))
            db.commit()
            received = []
            offset = 0
            page_sizes = []
            while True:
                page = list_cataloging_jobs(project.id, db, limit=20, offset=offset).data
                self.assertEqual(page["total"], 45)
                self.assertTrue(all(row["project_id"] == project.id for row in page["items"]))
                received.extend(row["id"] for row in page["items"])
                page_sizes.append(len(page["items"]))
                if page["next_offset"] is None:
                    break
                self.assertGreater(page["next_offset"], offset)
                offset = page["next_offset"]
            self.assertEqual(page_sizes, [20, 20, 5])
            self.assertEqual(received, sorted(identities, reverse=True))
            empty = list_cataloging_jobs(project.id, db, limit=20, offset=60).data
            self.assertEqual(empty["items"], [])
            self.assertEqual(empty["total"], 45)
            self.assertIsNone(empty["next_offset"])

    def test_job_projection_includes_authoritative_operation_activity(self):
        from datetime import datetime

        with self.Session() as db:
            project = Project(title="Visible catalog progress")
            db.add(project)
            db.flush()
            operation = OperationRun(
                id="operation-1",
                source_kind="cataloging",
                source_id="job-1",
                project_id=project.id,
                title="Catalog chapter",
                phase="candidates",
                current_message="模型进程仍在计算",
                process_metrics_json={"alive": True},
                last_activity_at=datetime(2026, 8, 31, 12, 34, 56),
            )
            job = CatalogingJob(
                id="job-1",
                project_id=project.id,
                status="running",
                operation_id=operation.id,
            )
            db.add_all([operation, job])
            db.commit()

            payload = job_to_dict(job)
            self.assertEqual(payload["current_stage"], "candidates")
            self.assertEqual(payload["current_message"], "模型进程仍在计算")
            self.assertTrue(payload["process_alive"])
            self.assertEqual(payload["last_activity_at"], "2026-08-31T12:34:56+00:00")

    def test_generated_target_ids_are_recorded_for_new_cataloging_rows(self):
        db = self.Session()
        try:
            project = Project(title="Generated ID lifecycle")
            db.add(project)
            db.flush()
            chapter = Chapter(
                project_id=project.id,
                title="Chapter One",
                content="The role crosses the old border.",
            )
            character = Character(
                project_id=project.id,
                name="Timeline role",
                role_type="supporting",
            )
            world = WorldbuildingEntry(
                project_id=project.id,
                dimension="geography",
                title="Old border",
                content="A disputed frontier.",
            )
            db.add_all([chapter, character, world])
            db.commit()

            job = create_cataloging_job(db, project.id, "auto", None, [chapter.id])
            run = job.chapter_runs[0]
            candidates = [
                CatalogingCandidate(
                    job_id=job.id,
                    chapter_run_id=run.id,
                    project_id=project.id,
                    chapter_id=chapter.id,
                    item_type="chapter_summary",
                    raw_payload=json.dumps(
                        {
                            "summary_text": "The role crosses the old border.",
                            "key_events": ["Crossed the border"],
                        }
                    ),
                ),
                CatalogingCandidate(
                    job_id=job.id,
                    chapter_run_id=run.id,
                    project_id=project.id,
                    chapter_id=chapter.id,
                    item_type="character_timeline",
                    raw_payload=json.dumps(
                        {
                            "name": character.name,
                            "event_description": "Crossed the old border.",
                        }
                    ),
                ),
                CatalogingCandidate(
                    job_id=job.id,
                    chapter_run_id=run.id,
                    project_id=project.id,
                    chapter_id=chapter.id,
                    item_type="worldbuilding_timeline",
                    raw_payload=json.dumps(
                        {
                            "title": world.title,
                            "event_description": "The border opened for one night.",
                        }
                    ),
                ),
            ]
            db.add_all(candidates)
            db.commit()

            events = apply_candidates_for_run(db, job, run)

            self.assertEqual(
                [event["type"] for event in events],
                ["candidate_applied"] * 4,
            )
            target_rows = {
                "chapter_summary": db.query(ChapterSummary).one(),
                "character_timeline": db.query(CharacterTimeline).one(),
                "worldbuilding_timeline": db.query(WorldbuildingTimeline).one(),
            }
            for candidate in candidates:
                with self.subTest(item_type=candidate.item_type):
                    self.assertEqual(
                        candidate.target_id,
                        target_rows[candidate.item_type].id,
                    )
                    log = (
                        db.query(CatalogingApplyLog)
                        .filter(CatalogingApplyLog.candidate_id == candidate.id)
                        .one()
                    )
                    self.assertEqual(log.target_id, target_rows[candidate.item_type].id)
        finally:
            db.close()

    def test_reconciles_completed_cataloging_job_into_task_center_projection(self):
        db = self.Session()
        try:
            project = Project(title="Projection repair")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="第1章", content="正文")
            db.add(chapter)
            db.flush()
            operation = OperationRun(
                source_kind="cataloging",
                source_id="cataloging-repair",
                project_id=project.id,
                title="作品建档 · 1 章",
                status="running",
                health_status="disconnected",
                progress_mode="determinate",
                progress_current=0,
                progress_total=1,
            )
            db.add(operation)
            db.flush()
            job = CatalogingJob(
                id="cataloging-repair",
                project_id=project.id,
                operation_id=operation.id,
                status="completed",
                total_chapters=1,
                completed_chapters=1,
                execution_mode="auto",
            )
            db.add(job)
            db.flush()
            db.add(CatalogingChapterRun(
                job_id=job.id,
                project_id=project.id,
                chapter_id=chapter.id,
                status="completed",
                chapter_order=0,
            ))
            db.commit()

            self.assertEqual(reconcile_cataloging_operation_projections(db), 1)
            db.commit()
            db.refresh(operation)

            self.assertEqual(operation.status, "completed")
            self.assertEqual(operation.health_status, "active")
            self.assertEqual(operation.progress_current, 1)
            self.assertEqual(operation.progress_total, 1)
            self.assertEqual((operation.result_json or {}).get("outcome"), "completed_with_tools")
            self.assertIsNotNone(operation.completed_at)
        finally:
            db.close()

    def test_apply_candidates_updates_project_knowledge(self):
        db = self.Session()
        try:
            project = Project(title="Cataloging Project")
            db.add(project)
            db.flush()
            chapter = Chapter(
                project_id=project.id,
                title="第1章 开端",
                content="张三来到青云宗。",
            )
            db.add_all([
                chapter,
                Character(project_id=project.id, name="李四", background="青云宗弟子。"),
            ])
            db.commit()

            job = create_cataloging_job(db, project.id, "auto", None, [])
            run = job.chapter_runs[0]
            for item_type, payload in [
                ("chapter_summary", {"summary_text": "张三来到青云宗。", "key_events": ["张三抵达青云宗"]}),
                ("outline_create", {"title": "第1章 开端", "node_type": "chapter", "summary": "张三来到青云宗。", "character_ids": ["11111111-1111-4111-8111-111111111111"]}),
                ("outline_create", {"title": "第1章 开端-场景1 入宗门", "node_type": "section", "summary": "张三进入青云宗山门。", "scene_number": 1, "character_ids": ["11111111-1111-4111-8111-111111111111"]}),
                ("character_create", {
                    "name": "张三",
                    "client_id": "11111111-1111-4111-8111-111111111111",
                    "role_type": "protagonist",
                    "appearance": "原文未明示，按当前表现推定：少年修士，衣着朴素。",
                    "personality": "谨慎敏锐。",
                    "background": "初到青云宗。",
                    "abilities": ["观察灵气异常"],
                    "tone_style": "沉稳",
                    "catchphrases": ["先看清楚"],
                    "emotion_tendency": "克制",
                    "custom_system_prompt": "扮演张三时保持谨慎、克制，先观察局势再行动。",
                    "current_location": "青云宗",
                }),
                ("character_relationship", {"source_name": "张三", "target_name": "李四", "relationship_type": "同门", "description": "李四接引张三入宗。"}),
                ("worldbuilding_create", {"dimension": "geography", "title": "青云宗", "content": "修行宗门。"}),
                ("chapter_link", {"character_names": ["张三"], "worldbuilding_titles": ["青云宗"], "outline_title": "第1章 开端"}),
            ]:
                db.add(CatalogingCandidate(
                    job_id=job.id,
                    chapter_run_id=run.id,
                    project_id=project.id,
                    chapter_id=chapter.id,
                    item_type=item_type,
                    raw_payload=json.dumps(payload, ensure_ascii=False),
                ))
            db.commit()

            events = apply_candidates_for_run(db, job, run)

            self.assertEqual([event["type"] for event in events], ["candidate_applied"] * 7)
            self.assertEqual(db.query(Character).count(), 2)
            self.assertEqual(db.query(WorldbuildingEntry).count(), 1)
            self.assertEqual(db.query(CharacterRelationship).count(), 1)
            self.assertEqual(db.query(OutlineNode).count(), 3)
            volume = db.query(OutlineNode).filter(OutlineNode.node_type == "volume").one()
            chapter_node = db.query(OutlineNode).filter(OutlineNode.node_type == "chapter").one()
            self.assertEqual(chapter_node.parent_id, volume.id)
            section = db.query(OutlineNode).filter(OutlineNode.node_type == "section").first()
            self.assertEqual(section.parent_id, chapter_node.id)
            self.assertIsNotNone(chapter.summary)
            self.assertEqual(chapter.summary.summary_text, "张三来到青云宗。")
            self.assertIsNotNone(chapter.outline_node_id)
            character = db.query(Character).filter(Character.name == "张三").first()
            self.assertEqual(character.appearance, "原文未明示，按当前表现推定：少年修士，衣着朴素。")
            self.assertEqual(json.loads(character.abilities), ["观察灵气异常"])
            config = db.query(CharacterAIConfig).filter(CharacterAIConfig.character_id == character.id).first()
            self.assertEqual(config.tone_style, "沉稳")
            self.assertEqual(json.loads(config.catchphrases), ["先看清楚"])
            self.assertIn("谨慎", config.custom_system_prompt)
        finally:
            db.close()

    def test_retry_failed_run_clears_candidates_and_resets_job(self):
        db = self.Session()
        try:
            project = Project(title="Retry Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="Retry Chapter", content="content")
            db.add(chapter)
            db.commit()

            job = create_cataloging_job(db, project.id, "auto", None, [])
            run = job.chapter_runs[0]
            run.status = "failed"
            run.error = "parse failed"
            job.status = "paused_on_failure"
            job.blocked_chapter_id = run.chapter_id
            db.add(CatalogingCandidate(
                job_id=job.id,
                chapter_run_id=run.id,
                project_id=project.id,
                chapter_id=chapter.id,
                item_type="chapter_summary",
                raw_payload=json.dumps({"summary_text": "old"}, ensure_ascii=False),
            ))
            db.commit()

            reset_run_for_retry(db, job, first_blocking_run(db, job))
            db.commit()

            self.assertEqual(run.status, "pending")
            self.assertIsNone(run.error)
            self.assertEqual(job.status, "running")
            self.assertIsNone(job.blocked_chapter_id)
            self.assertEqual(db.query(CatalogingCandidate).count(), 0)
        finally:
            db.close()


    def test_archive_reader_includes_complete_character_and_worldbuilding_details(self):
        db = self.Session()
        try:
            project = Project(title="Context Project")
            db.add(project)
            db.flush()
            previous = Chapter(project_id=project.id, title="Previous", content="previous")
            current = Chapter(project_id=project.id, title="Current", content="current")
            character = Character(
                project_id=project.id,
                name="Hero",
                role_type="protagonist",
                appearance="plain robe",
                personality="careful",
                background="escaped from the old sect",
                abilities=json.dumps(["array reading"], ensure_ascii=False),
                life_status="alive",
                current_location="valley",
                realm_or_level="foundation",
                mental_state="focused",
                active_conflict="must seal the gate",
                abilities_state="cannot use full power",
                items_or_assets="jade token",
            )
            entry = WorldbuildingEntry(
                project_id=project.id,
                dimension="power_system",
                title="Array Rules",
                content="Arrays require anchor stones and fail when anchors are corrupted.",
            )
            db.add_all([previous, current, character, entry])
            db.flush()
            db.add(CharacterAIConfig(
                character_id=character.id,
                tone_style="calm",
                catchphrases=json.dumps(["wait"], ensure_ascii=False),
                custom_system_prompt="Keep the hero calm and tactical.",
            ))
            db.commit()

            person = asyncio.run(read_cataloging_archive(db, project.id, {"kind": "character", "ids": [character.id]}))["data"]["items"][0]
            world = asyncio.run(read_cataloging_archive(db, project.id, {"kind": "worldbuilding", "ids": [entry.id]}))["data"]["items"][0]
            self.assertEqual(person["background"], "escaped from the old sect")
            self.assertEqual(person["mental_state"], "focused")
            self.assertEqual(person["items_or_assets"], "jade token")
            self.assertEqual(person["active_conflict"], "must seal the gate")
            self.assertEqual(person["ai_config"]["tone_style"], "calm")
            self.assertEqual(world["content"], "Arrays require anchor stones and fail when anchors are corrupted.")
        finally:
            db.close()

    def test_world_context_selects_relevant_entries_beyond_initial_sort_window(self):
        db = self.Session()
        try:
            project = Project(title="World Context Project")
            db.add(project)
            db.flush()
            for index in range(40):
                db.add(WorldbuildingEntry(
                    project_id=project.id,
                    dimension="culture",
                    title=f"无关习俗{index}",
                    content="普通年节礼仪，与当前归寂谷剧情无关。",
                    sort_order=index,
                ))
            late_entry = WorldbuildingEntry(
                project_id=project.id,
                dimension="power_system",
                title="归寂谷黄泉回路",
                content="归寂谷可以用黄泉回路引导死气，但会受到归墟阵灵石余量限制。",
                sort_order=999,
            )
            outline = OutlineNode(
                project_id=project.id,
                node_type="chapter",
                title="第151章 旧档藏线",
                summary="特昂糖在归寂谷查看旧档，追查黄泉回路与归墟阵灵石消耗。",
                sort_order=151,
            )
            db.add_all([late_entry, outline])
            db.commit()

            context = _build_world_context(
                db,
                project.id,
                outline.id,
                query_context="继续写归寂谷黄泉回路和归墟阵灵石倒计时",
            )

            self.assertIn("归寂谷黄泉回路", context)
            self.assertIn("已从 41 条世界观中筛选", context)
        finally:
            db.close()


    def test_background_merge_compacts_repeated_history(self):
        chapter = Chapter(title="Chapter 9")
        existing = (
            "As heir, Mira guarded the valley.\n\n"
            "《Chapter 8》：As heir, Mira guarded the valley.\n\n"
            "She once hid under a false name."
        )
        incoming = "As heir, Mira guarded the valley. She revealed the false name to protect her sect."

        merged = merge_background(existing, incoming, chapter, limit=140)

        self.assertLessEqual(len(merged), 140)
        self.assertEqual(merged.count("As heir"), 1)
        self.assertNotIn("《Chapter 8》", merged)
        self.assertIn("false name", merged)

    def test_background_merge_rewrite_replaces_every_contained_fragment(self):
        chapter = Chapter(title="空出的排期")
        existing = (
            "栏目负责人交办综述稿；"
            "周芷确认三份材料不能独立证明18:50；"
            "她拒稿并让出排期；"
            "组织者无法说明模板的原始依据"
        )
        incoming = (
            "栏目负责人交办综述稿，周芷确认三份材料不能独立证明18:50，"
            "她拒稿并让出排期；她转去公开演练，组织者无法说明模板的原始依据"
        )

        merged = merge_background(existing, incoming, chapter, limit=1000)

        self.assertEqual(merged.count("周芷确认三份材料不能独立证明18:50"), 1)
        self.assertEqual(merged.count("她拒稿并让出排期"), 1)
        self.assertEqual(merged.count("组织者无法说明模板的原始依据"), 1)

    def test_merge_text_replaces_same_chapter_section_and_keeps_later_sections(self):
        chapter = Chapter(title="第二章")
        existing = "谨慎\n\n《第二章》：旧版变化\n\n《第三章》：后续变化"

        merged = merge_text(existing, "新版变化", chapter)

        self.assertEqual(merged.count("《第二章》"), 1)
        self.assertNotIn("旧版变化", merged)
        self.assertIn("《第二章》：新版变化", merged)
        self.assertIn("《第三章》：后续变化", merged)

    def test_merge_text_removes_exact_fragments_from_cumulative_world_update(self):
        chapter = Chapter(title="模板上的18:50")
        existing = (
            "用途：通信值班场所。"
            "环境：单层值班台与蓝白灯光。"
            "进入条件：内部证据调阅需审批。"
        )
        incoming = (
            "用途：港务调度通信值班场所。"
            "环境：单层值班台与蓝白灯光。"
            "进入条件：内部证据调阅需审批。"
            "本章新增：2015年3月通知的收文单位包含本值班室。"
        )

        merged = merge_text(existing, incoming, chapter)

        self.assertEqual(merged.count("环境：单层值班台与蓝白灯光"), 1)
        self.assertEqual(merged.count("进入条件：内部证据调阅需审批"), 1)
        self.assertIn("《模板上的18:50》：用途：港务调度通信值班场所", merged)
        self.assertIn("本章新增：2015年3月通知", merged)

    def test_merge_text_same_chapter_shorter_rewrite_removes_old_contribution(self):
        chapter = Chapter(title="第二章")
        existing = "作者基线。\n\n《第二章》：旧事实一。旧事实二。"

        merged = merge_text(existing, "修订后只保留事实一。", chapter)

        self.assertEqual(merged, "作者基线。\n\n《第二章》：修订后只保留事实一。")
        self.assertNotIn("旧事实二", merged)

    def test_character_state_omits_unchanged_fields_without_losing_the_card(self):
        db = self.Session()
        try:
            project = Project(title="Sparse State Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="Reply", content="Mira agrees to meet.")
            character = Character(
                project_id=project.id,
                name="Mira",
                appearance="Short hair, a repaired watch strap and ink on her sleeve.",
                age="29",
                background="A reporter with three years of experience.",
                personality="Patient and precise.",
                current_location="Office",
                current_goal="Wait for a reply",
                items_or_assets="Notebook and the signed receipt",
            )
            db.add_all([chapter, character])
            db.commit()
            preserved_fields = (
                "appearance", "age", "background", "personality", "current_location", "items_or_assets",
            )
            before = {field: getattr(character, field) for field in preserved_fields}
            job = create_cataloging_job(db, project.id, "auto", None, [])
            run = job.chapter_runs[0]
            db.add(CatalogingCandidate(
                job_id=job.id, chapter_run_id=run.id, project_id=project.id,
                chapter_id=chapter.id, item_type="character_state_update",
                raw_payload=json.dumps({"id": character.id, "name": "Mira", "current_goal": "Attend the agreed meeting"}),
            ))
            db.commit()

            apply_candidates_for_run(db, job, run)
            db.expire_all()

            self.assertEqual({field: getattr(character, field) for field in preserved_fields}, before)
            self.assertEqual(character.current_goal, "Attend the agreed meeting")
            self.assertEqual(character.last_seen_chapter_id, chapter.id)
            version = db.query(CharacterVersion).filter(CharacterVersion.character_id == character.id).one()
            self.assertIn("当前目标", version.change_summary)
            self.assertNotIn("外貌", version.change_summary)
            self.assertNotIn("年龄/时间状态", version.change_summary)
        finally:
            db.close()

    def test_rest_and_workspace_apply_share_terminal_state_and_mirror_outbox(self):
        from app.routers.cataloging import apply_pending_cataloging as apply_via_rest
        from app.services.workspace.tools.cataloging import (
            apply_pending_cataloging as apply_via_workspace,
        )

        db = self.Session(autoflush=False)
        db.info["siming_skip_content_sync_dispatch"] = True

        def prepare(label: str):
            project = Project(title=f"Transport parity {label}")
            db.add(project)
            db.flush()
            chapter = Chapter(
                project_id=project.id,
                title=f"第1章 {label}",
                content="林舟打开档案，确认记录仍然有效。",
                current_version=1,
                cataloging_required=True,
            )
            db.add(chapter)
            db.flush()
            planned_outline = OutlineNode(
                project_id=project.id,
                node_type="chapter",
                title=chapter.title,
                summary="作者规划摘要",
                planned_summary="作者规划摘要",
                status="pending",
                sort_order=1,
            )
            db.add(planned_outline)
            db.flush()
            chapter.outline_node_id = planned_outline.id
            operation = OperationRun(
                source_kind="cataloging",
                source_id=f"transport-{label}",
                project_id=project.id,
                title=f"作品建档 {label}",
                status="waiting_user",
                progress_mode="determinate",
                progress_current=0,
                progress_total=1,
            )
            db.add(operation)
            db.flush()
            agent_run = AgentRun(
                project_id=project.id,
                source="internal",
                title=f"建档 Agent {label}",
                operation_id=operation.id,
                status="waiting_confirmation",
            )
            db.add(agent_run)
            db.flush()
            job = CatalogingJob(
                project_id=project.id,
                status="waiting_confirmation",
                execution_mode="manual",
                execution_backend="external_agent",
                agent_run_id=agent_run.id,
                operation_id=operation.id,
                current_chapter_id=chapter.id,
                blocked_chapter_id=chapter.id,
                total_chapters=1,
            )
            db.add(job)
            db.flush()
            run = CatalogingChapterRun(
                job_id=job.id,
                project_id=project.id,
                chapter_id=chapter.id,
                chapter_version=1,
                status="awaiting_confirmation",
                chapter_order=0,
            )
            db.add(run)
            db.flush()
            create_manual_candidate(
                db,
                job,
                run,
                "chapter_summary",
                complete_summary_payload(
                    "林舟确认档案记录仍然有效。",
                    scene_count=1,
                ),
                "accepted",
            )
            create_manual_candidate(
                db,
                job,
                run,
                "outline_create",
                {
                    "character_ids": [],
                    "title": chapter.title,
                    "node_type": "chapter",
                    "summary": "林舟确认档案记录仍然有效。",
                },
                "accepted",
            )
            return project, chapter, job, run, agent_run, operation

        try:
            rest = prepare("REST")
            workspace = prepare("Workspace")
            db.commit()

            rest_response = asyncio.run(apply_via_rest(rest[0].id, rest[2].id, db))
            workspace_response = asyncio.run(
                apply_via_workspace(db, workspace[0].id, {"job_id": workspace[2].id})
            )
            db.flush()

            self.assertEqual(rest_response.code, 0)
            self.assertEqual(workspace_response["status"], "ok")
            self.assertEqual(
                rest_response.data["run"]["status"],
                workspace_response["data"]["run"]["status"],
            )
            self.assertIn(rest_response.data["run"]["status"], {"completed", "completed_with_warnings"})

            for project, chapter, job, run, agent_run, operation in (rest, workspace):
                for entity in (chapter, job, run, agent_run, operation):
                    db.refresh(entity)
                self.assertEqual(job.status, "completed")
                self.assertEqual(job.completed_chapters, 1)
                self.assertIsNotNone(job.completed_at)
                self.assertIsNone(job.current_chapter_id)
                self.assertIsNone(job.blocked_chapter_id)
                self.assertFalse(chapter.cataloging_required)
                outline = db.query(OutlineNode).filter(
                    OutlineNode.id == chapter.outline_node_id
                ).one()
                self.assertEqual(outline.status, "completed")
                self.assertEqual(outline.planned_summary, "作者规划摘要")
                self.assertEqual(agent_run.status, "completed")
                self.assertIsNotNone(agent_run.completed_at)
                self.assertEqual(operation.status, "completed")
                self.assertEqual(operation.progress_current, 1)
                self.assertEqual(
                    (operation.result_json or {}).get("outcome"),
                    "completed_with_tools",
                )
                sync_jobs = db.query(ContentSyncJob).filter(
                    ContentSyncJob.project_id == project.id,
                    ContentSyncJob.target == "project",
                ).all()
                self.assertEqual(len(sync_jobs), 1)
                self.assertEqual(sync_jobs[0].source, "cataloging_apply")
        finally:
            db.close()


    def test_character_state_replaces_current_fields_and_versions_are_descriptive(self):
        db = self.Session()
        try:
            project = Project(title="State Project")
            db.add(project)
            db.flush()
            chapter = Chapter(
                project_id=project.id,
                title="第二章 吐纳",
                content="Mira三岁半，换上练功短衫，左臂仍有绷带，随后走到庭院。",
            )
            character = Character(
                project_id=project.id,
                name="Mira",
                appearance="三岁幼女，穿旧外袍。",
                age="三岁《第一章》：三岁半",
                current_location="Hall《第一章》：Courtyard",
                current_goal="Wait for orders",
            )
            db.add_all([chapter, character])
            db.commit()

            job = create_cataloging_job(db, project.id, "auto", None, [])
            run = job.chapter_runs[0]
            db.add(CatalogingCandidate(
                job_id=job.id,
                chapter_run_id=run.id,
                project_id=project.id,
                chapter_id=chapter.id,
                item_type="character_state_update",
                raw_payload=json.dumps({
                    "name": "Mira",
                    "appearance": "三岁半幼女，换上练功短衫，左臂仍有绷带。",
                    "appearance_before": "三岁幼女，穿旧外袍。",
                    "appearance_evidence": "Mira三岁半，换上练功短衫，左臂仍有绷带",
                    "age": "三岁半",
                    "age_before": "三岁《第一章》：三岁半",
                    "age_evidence": "Mira三岁半",
                    "current_location": "Courtyard",
                    "current_goal": "Learn breathing",
                }, ensure_ascii=False),
            ))
            db.commit()

            apply_candidates_for_run(db, job, run)

            self.assertEqual(character.age, "三岁半")
            self.assertEqual(character.appearance, "三岁半幼女，换上练功短衫，左臂仍有绷带。")
            self.assertEqual(character.current_location, "Courtyard")
            self.assertEqual(character.current_goal, "Learn breathing")
            version = (
                db.query(CharacterVersion)
                .filter(CharacterVersion.character_id == character.id)
                .order_by(CharacterVersion.version_number.desc())
                .first()
            )
            self.assertIn("外貌", version.change_summary)
            self.assertIn("年龄/时间状态", version.change_summary)
            self.assertIn("当前位置", version.change_summary)
            self.assertIn("当前目标", version.change_summary)
            self.assertNotIn("角色档案更新", version.change_summary)
        finally:
            db.close()

    def test_model_supplied_canonical_names_and_aliases_remain_separate_fields(self):
        db = self.Session()
        try:
            project = Project(title="Alias Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="第二章 吐纳", content="糖糖在陆家见到爷爷。")
            db.add(chapter)
            db.commit()

            job = create_cataloging_job(db, project.id, "auto", None, [])
            run = job.chapter_runs[0]
            for index, payload in enumerate([
                {"name": "特昂糖", "aliases": ["陆糖", "糖糖"], "role_type": "protagonist"},
                {"name": "特昂糖", "current_location": "陆家府邸"},
                {"name": "陆老爷子", "aliases": ["爷爷"], "role_type": "mentor",
                 "background": "陆家长辈，负责教导特昂糖吐纳。"},
            ]):
                db.add(CatalogingCandidate(
                    job_id=job.id,
                    chapter_run_id=run.id,
                    project_id=project.id,
                    chapter_id=chapter.id,
                    item_type="character_state_update" if payload.get("current_location") else "character_create",
                    raw_payload=json.dumps(payload, ensure_ascii=False),
                    sort_order=index,
                ))
            db.commit()

            apply_candidates_for_run(db, job, run)

            characters = db.query(Character).order_by(Character.name.asc()).all()
            self.assertEqual(len(characters), 2)
            sugar = next(item for item in characters if item.name == "特昂糖")
            elder = next(item for item in characters if item.name == "陆老爷子")
            self.assertEqual(sugar.current_location, "陆家府邸")
            sugar_aliases = [item.alias for item in db.query(CharacterAlias).filter(CharacterAlias.character_id == sugar.id).all()]
            elder_aliases = [item.alias for item in db.query(CharacterAlias).filter(CharacterAlias.character_id == elder.id).all()]
            self.assertIn("陆糖", sugar_aliases)
            self.assertNotIn("特昂糖/陆糖", sugar_aliases)
            self.assertIn("糖糖", sugar_aliases)
            self.assertIn("爷爷", elder_aliases)
        finally:
            db.close()

    def test_character_merge_candidate_marks_alias_and_merges_background(self):
        db = self.Session()
        try:
            project = Project(title="Merge Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="Reveal", content="Black Cloak is the Master.")
            primary = Character(project_id=project.id, name="Master", background="Controls the hidden net.")
            secondary = Character(project_id=project.id, name="Black Cloak", background="Met the rebels in disguise.")
            db.add_all([chapter, primary, secondary])
            db.commit()

            job = create_cataloging_job(db, project.id, "auto", None, [])
            run = job.chapter_runs[0]
            db.add(CatalogingCandidate(
                job_id=job.id,
                chapter_run_id=run.id,
                project_id=project.id,
                chapter_id=chapter.id,
                item_type="character_merge_candidate",
                raw_payload=json.dumps({
                    "primary_name": "Master",
                    "secondary_name": "Black Cloak",
                    "aliases": ["Black Cloak", "the voice behind the net"],
                    "reason": "Both command the same rebel contact.",
                    "background_append": "以黑袍人身份接触叛徒，随后暴露为幕后主使。",
                }, ensure_ascii=False),
            ))
            db.commit()

            events = apply_candidates_for_run(db, job, run)

            self.assertEqual(events[0]["type"], "candidate_applied")
            self.assertIn("Met the rebels", primary.background)
            self.assertIn("黑袍人身份", primary.background)
            self.assertEqual(secondary.role_type, "merged_alias")
            self.assertIn("合并到", secondary.background)
            aliases = db.query(CharacterAlias).filter(CharacterAlias.character_id == primary.id).all()
            self.assertIn("Black Cloak", [alias.alias for alias in aliases])
        finally:
            db.close()

    def test_manual_character_merge_preview_and_apply_moves_links(self):
        db = self.Session()
        try:
            project = Project(title="Manual Merge Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="第三章", content="爷爷就是陆老爷子。")
            primary = Character(
                project_id=project.id,
                name="陆老爷子",
                role_type="mentor",
                background="陆家长辈。",
                appearance="白发老者。",
                personality="沉稳。",
            )
            secondary = Character(
                project_id=project.id,
                name="爷爷",
                role_type="mentor",
                background="教导特昂糖吐纳。",
                appearance="坐在太师椅上的老人。",
                personality="慈祥。",
            )
            db.add_all([chapter, primary, secondary])
            db.flush()
            from app.database.models import ChapterCharacter, CharacterRelationship, CharacterTimeline
            db.add_all([
                CharacterAlias(project_id=project.id, character_id=primary.id, alias="爷爷", alias_type="alias", description="旧称呼"),
                ChapterCharacter(chapter_id=chapter.id, character_id=secondary.id, appearance_type="出场", description="爷爷教导糖糖"),
                CharacterTimeline(character_id=secondary.id, chapter_id=chapter.id, event_description="决定教特昂糖吐纳", event_type="decision"),
                CharacterRelationship(project_id=project.id, character_a_id=secondary.id, character_b_id=primary.id, relationship_type="同一人", description="称呼不同"),
            ])
            db.commit()

            duplicates = find_duplicate_character_candidates(db, project.id)
            self.assertTrue(any(item["primary"]["id"] == primary.id and item["secondary"]["id"] == secondary.id for item in duplicates))

            preview = build_character_merge_preview(db, project.id, primary.id, secondary.id, {"aliases": ["爷爷"]})
            self.assertEqual(preview["stats"]["secondary_chapter_appearances"], 1)
            self.assertIn("爷爷", preview["aliases"])
            self.assertIn("手动合并", preview["merged_preview"]["appearance"])

            merge_characters(db, project.id, primary.id, secondary.id, {"aliases": ["爷爷"], "confidence_reason": "同一人物不同称呼"})
            db.commit()

            self.assertEqual(secondary.role_type, "merged_alias")
            self.assertEqual(db.query(ChapterCharacter).filter(ChapterCharacter.character_id == secondary.id).count(), 0)
            self.assertEqual(db.query(ChapterCharacter).filter(ChapterCharacter.character_id == primary.id).count(), 1)
            self.assertEqual(db.query(CharacterTimeline).filter(CharacterTimeline.character_id == primary.id).count(), 1)
            self.assertEqual(db.query(CharacterRelationship).filter(CharacterRelationship.character_a_id == secondary.id).count(), 0)
            aliases = [item.alias for item in db.query(CharacterAlias).filter(CharacterAlias.character_id == primary.id).all()]
            self.assertIn("爷爷", aliases)
        finally:
            db.close()


    def test_skip_and_cancel_update_job_state(self):
        db = self.Session()
        try:
            project = Project(title="Control Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="Control Chapter", content="content")
            db.add(chapter)
            db.commit()

            job = create_cataloging_job(db, project.id, "manual", None, [])
            run = job.chapter_runs[0]
            run.status = "awaiting_confirmation"
            job.status = "waiting_confirmation"
            job.blocked_chapter_id = run.chapter_id
            db.commit()

            mark_run_skipped(db, job, first_blocking_run(db, job))
            db.commit()

            self.assertEqual(run.status, "skipped_by_user")
            self.assertEqual(job.status, "running")
            self.assertIsNone(job.blocked_chapter_id)
            self.assertEqual(job.context_integrity, "skipped_chapter")

            cancel_job(job)
            db.commit()

            self.assertEqual(job.status, "cancelled")
            self.assertIsNone(job.current_chapter_id)
            self.assertIsNone(job.blocked_chapter_id)
            self.assertIsNotNone(job.completed_at)
        finally:
            db.close()

    def test_manual_repair_can_recover_failed_run_for_review(self):
        db = self.Session()
        try:
            project = Project(title="Repair Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="Repair Chapter", content="content")
            db.add(chapter)
            db.commit()

            job = create_cataloging_job(db, project.id, "manual", None, [])
            run = job.chapter_runs[0]
            run.status = "failed"
            run.error = "bad jsonl"
            job.status = "paused_on_failure"
            job.blocked_chapter_id = run.chapter_id
            db.commit()

            self.assertFalse(has_usable_chapter_summary(db, run))
            create_manual_candidate(db, job, run, "chapter_summary",
                complete_summary_payload("manual summary", key_events=["fixed"]), "edited")
            self.assertTrue(has_usable_chapter_summary(db, run))

            recover_failed_run_for_review(db, job, run)
            db.commit()

            self.assertEqual(run.status, "awaiting_confirmation")
            self.assertIsNone(run.error)
            self.assertEqual(job.status, "waiting_confirmation")
            self.assertEqual(job.blocked_chapter_id, run.chapter_id)
        finally:
            db.close()


    def test_recover_current_endpoint_keeps_incomplete_raw_output_failed(self):
        db = self.Session()
        try:
            project = Project(title="Incomplete Endpoint Recovery Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="第一章", content="只有摘要。")
            db.add(chapter)
            db.commit()
            job = create_cataloging_job(db, project.id, "manual", "deepseek:test", [])
            run = job.chapter_runs[0]
            run.status = "failed"
            run.raw_output = "=== CANDIDATE RESOLUTION ===\n" + json.dumps({
                "type": "chapter_summary",
                "summary_text": "只有摘要。",
            }, ensure_ascii=False)
            job.status = "paused_on_failure"
            job.blocked_chapter_id = run.chapter_id
            db.commit()

            with self.assertRaises(ValidationError) as raised:
                recover_current_cataloging_chapter(project.id, job.id, db)

            self.assertIn("chapter_summary", str(raised.exception))
            self.assertEqual(run.status, "failed")
            self.assertEqual(
                db.query(CatalogingCandidate).filter(
                    CatalogingCandidate.chapter_run_id == run.id,
                ).count(),
                0,
            )
        finally:
            db.close()

    def test_refresh_job_progress_flushes_pending_run_status(self):
        db = self.Session()
        try:
            project = Project(title="Progress Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="Progress Chapter", content="content")
            db.add(chapter)
            db.commit()

            job = create_cataloging_job(db, project.id, "manual", None, [])
            run = job.chapter_runs[0]
            run.status = "completed"

            refresh_job_progress(db, job)

            self.assertEqual(job.completed_chapters, 1)
        finally:
            db.close()

    def test_pause_and_resume_job(self):
        db = self.Session()
        try:
            project = Project(title="Pause Project")
            db.add(project)
            db.flush()
            chapter = Chapter(project_id=project.id, title="Pause Chapter", content="content")
            db.add(chapter)
            db.commit()

            job = create_cataloging_job(db, project.id, "auto", None, [])
            pause_job(job)
            self.assertEqual(job.status, "paused")
            resume_job(job)
            self.assertEqual(job.status, "running")
            self.assertIsNone(job.error)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()

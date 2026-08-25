from __future__ import annotations

import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    Base,
    Chapter,
    Character,
    Foreshadowing,
    NarrativeCheckpoint,
    NarrativeDebt,
    NarrativeGovernanceEvent,
    OutlineNode,
    Project,
)
from app.modules.continuity.infrastructure.governance import SqlAlchemyNarrativeGovernanceCommands
from app.modules.story.infrastructure.chapter_evidence import SqlAlchemyChapterEvidenceReader
from app.services.chapter_service import ensure_current_snapshot
from app.services.narrative_governance import (
    apply_governance_candidates,
    checkpoint_diff,
    create_narrative_checkpoint,
    governance_context,
    governance_dashboard,
    mark_governance_items_stale_for_chapter,
    record_chapter_governance_review,
    restore_narrative_checkpoint,
    upsert_causal_edge,
    upsert_foreshadowing,
    upsert_narrative_debt,
    verify_chapter_governance_review,
)


class NarrativeGovernanceTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        self.db = sessionmaker(bind=engine)()
        self.db.add(Project(id="p1", title="治理测试"))
        self.db.add(OutlineNode(id="o1", project_id="p1", title="第一章", node_type="chapter"))
        self.db.add(Chapter(id="c1", project_id="p1", outline_node_id="o1", title="第一章", content="正文", current_version=1))
        self.db.add(Character(id="char1", project_id="p1", name="林舟"))
        self.db.commit()

    def tearDown(self):
        self.db.close()

    @staticmethod
    def governance_commands() -> SqlAlchemyNarrativeGovernanceCommands:
        return SqlAlchemyNarrativeGovernanceCommands(SqlAlchemyChapterEvidenceReader())

    def test_foreshadowing_deduplicates_and_transitions(self):
        first = upsert_foreshadowing(self.db, "p1", {"title": "断剑上的血纹", "importance": "high", "source_chapter_id": "c1"})
        second = upsert_foreshadowing(self.db, "p1", {"title": "断剑上的血纹", "status": "deferred", "target_chapter_number": 3})
        self.db.commit()
        self.assertEqual(first.id, second.id)
        self.assertEqual(self.db.query(Foreshadowing).count(), 1)
        self.assertEqual(second.status, "deferred")

    def test_verified_close_requires_repair_then_review_evidence(self):
        hook = upsert_foreshadowing(
            self.db,
            "p1",
            {
                "title": "断剑血纹",
                "source_chapter_id": "c1",
                "evidence": "第一章首次出现无法解释的血纹",
            },
        )
        self.db.commit()
        commands = self.governance_commands()

        with self.assertRaisesRegex(ValueError, "必须先提交复检"):
            commands.update_status(
                self.db,
                "p1",
                "foreshadowings",
                hook.id,
                {
                    "status": "fulfilled",
                    "resolved_chapter_id": "c1",
                    "resolution_note": "正文已经解释血纹来源",
                    "verification_note": "复读后确认线索完整闭合",
                },
            )

        pending = commands.update_status(
            self.db,
            "p1",
            "foreshadowings",
            hook.id,
            {
                "status": "pending_review",
                "resolved_chapter_id": "c1",
                "resolution_note": "正文已经解释血纹来源",
                    "resolution_evidence": "第一章末尾由铸剑师说明来源",
            },
        )
        self.assertEqual(pending["status"], "pending_review")
        self.assertEqual(pending["evidence"], "第一章首次出现无法解释的血纹")
        self.assertEqual(pending["resolution_evidence"], "第一章末尾由铸剑师说明来源")

        closed = commands.update_status(
            self.db,
            "p1",
            "foreshadowings",
            hook.id,
            {
                "status": "fulfilled",
                "resolved_chapter_id": "c1",
                "resolution_note": "正文已经解释血纹来源",
                "resolution_evidence": "第一章末尾由铸剑师说明来源",
                "verification_note": "复读前后文后确认没有遗漏",
                "closed_by": "user",
            },
        )
        self.assertEqual(closed["status"], "fulfilled")
        self.assertEqual(closed["resolved_chapter_version"], 1)
        self.assertIsNotNone(closed["verified_at"])
        events = self.db.query(NarrativeGovernanceEvent).filter(
            NarrativeGovernanceEvent.item_id == hook.id
        ).all()
        self.assertEqual([event.to_status for event in events], ["open", "pending_review", "fulfilled"])

    def test_model_resolution_requires_stable_identity_and_never_auto_closes(self):
        self.db.add(
            Chapter(
                id="c2",
                project_id="p1",
                title="第二章",
                content="巡夜人说明脚步来源。",
                current_version=3,
            )
        )
        hook = upsert_foreshadowing(
            self.db,
            "p1",
            {"title": "门后的三声脚步", "source_chapter_id": "c1"},
        )
        self.db.commit()

        with self.assertRaisesRegex(ValueError, "resolves_item_id"):
            apply_governance_candidates(
                self.db,
                "p1",
                [{
                    "type": "foreshadowing",
                    "title": "脚步声已经解释",
                    "status": "fulfilled",
                    "resolved_chapter_id": "c2",
                }],
                chapter_id="c2",
            )

        items = apply_governance_candidates(
            self.db,
            "p1",
            [{
                "type": "foreshadowing",
                "title": "脚步声来自巡夜人",
                "status": "fulfilled",
                "resolves_item_id": hook.id,
                "resolved_chapter_id": "c2",
                "resolution_note": "巡夜人当面说明了脚步来源",
            }],
            chapter_id="c2",
        )
        self.db.commit()

        self.assertEqual(len(items), 1)
        self.assertEqual(self.db.query(Foreshadowing).count(), 1)
        stored = self.db.query(Foreshadowing).filter(Foreshadowing.id == hook.id).one()
        self.assertEqual(stored.title, "门后的三声脚步")
        self.assertEqual(stored.source_chapter_id, "c1")
        self.assertEqual(stored.resolved_chapter_id, "c2")
        self.assertEqual(stored.resolved_chapter_version, 3)
        self.assertEqual(stored.status, "pending_review")

    def test_wrong_status_for_item_type_is_rejected(self):
        edge = upsert_causal_edge(self.db, "p1", {"cause": "A", "effect": "B"})
        self.db.commit()
        commands = self.governance_commands()
        with self.assertRaisesRegex(ValueError, "不支持目标状态"):
            commands.update_status(
                self.db,
                "p1",
                "causal-edges",
                edge.id,
                {"status": "deferred", "target_chapter_number": 3},
            )

    def test_candidate_cannot_reopen_a_closed_item_by_repeating_its_title(self):
        hook = upsert_foreshadowing(self.db, "p1", {"title": "已经闭环的钟声"})
        hook.status = "fulfilled"
        self.db.commit()

        with self.assertRaisesRegex(ValueError, "必须先由用户重新打开"):
            apply_governance_candidates(
                self.db,
                "p1",
                [{"type": "foreshadowing", "title": "已经闭环的钟声", "status": "open"}],
                chapter_id="c1",
            )

        self.db.rollback()
        stored = self.db.query(Foreshadowing).filter(Foreshadowing.id == hook.id).one()
        self.assertEqual(stored.status, "fulfilled")

    def test_causal_edge_and_debt_rank_ahead_in_context(self):
        upsert_foreshadowing(self.db, "p1", {"title": "普通线索", "importance": "low"})
        edge = upsert_causal_edge(self.db, "p1", {"cause": "宗门毁约", "effect": "主角失去盟军", "strength": 0.9})
        debt = upsert_narrative_debt(self.db, "p1", {"title": "必须回应盟军背叛", "priority": "critical", "linked_causal_edge_id": edge.id})
        self.db.commit()
        context = governance_context(self.db, "p1", limit=2)
        self.assertIn(debt.title, context)
        self.assertIn(edge.effect, context)
        self.assertNotIn("普通线索", context)

    def test_candidate_batch_covers_all_structured_types(self):
        items = apply_governance_candidates(self.db, "p1", [
            {"type": "foreshadowing", "title": "门后脚步"},
            {"type": "causal_edge", "cause": "敲门", "effect": "守卫惊醒", "strength": 0.8},
            {"type": "narrative_debt", "title": "解释来客身份", "priority": "high"},
            {"type": "character_state", "character_id": "char1", "current_goal": "查明来客"},
            {"type": "quality_metric", "chapter_id": "c1", "plot_tension": 72, "character_consistency": 58, "warnings": ["角色反应偏弱"]},
        ], chapter_id="c1")
        self.db.commit()
        self.assertEqual(len(items), 5)
        dashboard = governance_dashboard(self.db, "p1")
        self.assertEqual(dashboard["counts"]["open_foreshadowings"], 1)
        self.assertEqual(len(dashboard["character_states"]), 1)
        self.assertFalse(dashboard["quality_metrics"][0]["passed"])

    def test_checkpoint_diff_and_atomic_state_restore(self):
        hook = upsert_foreshadowing(self.db, "p1", {"title": "旧伏笔", "importance": "high"})
        chapter = self.db.query(Chapter).filter(Chapter.id == "c1").one()
        ensure_current_snapshot(self.db, chapter)
        checkpoint = create_narrative_checkpoint(self.db, "p1", chapter=chapter, label="第一版")
        self.db.commit()
        hook.status = "fulfilled"
        chapter.content = "修改后的正文"
        chapter.current_version = 2
        upsert_narrative_debt(self.db, "p1", {"title": "新增债务"})
        self.db.commit()
        diff = checkpoint_diff(self.db, "p1", checkpoint.id)
        self.assertEqual(len(diff["changes"]["foreshadowings"]["changed"]), 1)
        self.assertEqual(len(diff["changes"]["narrative_debts"]["added"]), 1)
        restore_narrative_checkpoint(self.db, "p1", checkpoint.id)
        self.db.commit()
        restored = self.db.query(Foreshadowing).one()
        self.assertEqual(restored.status, "open")
        self.assertEqual(self.db.query(NarrativeDebt).count(), 0)
        restored_chapter = self.db.query(Chapter).filter(Chapter.id == "c1").one()
        self.assertEqual(restored_chapter.content, "正文")
        checkpoints = self.db.query(NarrativeCheckpoint).order_by(NarrativeCheckpoint.sequence).all()
        self.assertEqual(len(checkpoints), 2)
        self.assertEqual(checkpoints[-1].trigger_type, "pre_restore_safety")

    def test_chapter_change_invalidates_items_and_review_proof(self):
        hook = upsert_foreshadowing(
            self.db,
            "p1",
            {"title": "窗台上的灰", "source_chapter_id": "c1"},
        )
        chapter = self.db.query(Chapter).filter(Chapter.id == "c1").one()
        review = record_chapter_governance_review(
            self.db,
            "p1",
            chapter,
            source="llm",
            findings_count=1,
            evidence="已检查本章叙事状态",
        )
        verify_chapter_governance_review(
            self.db,
            "p1",
            review.id,
            evidence="人工复核确认本章检查完整",
        )
        chapter.current_version = 2
        changed = mark_governance_items_stale_for_chapter(
            self.db,
            "p1",
            "c1",
            reason="正文已保存为 v2，需要重新检查",
        )
        self.db.commit()

        self.assertEqual(changed, 2)
        self.assertEqual(hook.status, "stale")
        self.assertEqual(review.status, "stale")
        dashboard = governance_dashboard(self.db, "p1")
        self.assertEqual(dashboard["chapter_reviews"][0]["status"], "stale")
        self.assertIsNone(dashboard["chapter_reviews"][0]["id"])
        self.assertEqual(dashboard["coverage"]["gaps"], 1)

    def test_explicit_zero_findings_is_not_treated_as_missing_review(self):
        chapter = self.db.query(Chapter).filter(Chapter.id == "c1").one()
        record_chapter_governance_review(
            self.db,
            "p1",
            chapter,
            source="llm",
            findings_count=0,
            evidence="已显式检查，未发现新增治理事项",
        )
        self.db.commit()

        dashboard = governance_dashboard(self.db, "p1")
        self.assertEqual(dashboard["chapter_reviews"][0]["status"], "assessed")
        self.assertEqual(dashboard["chapter_reviews"][0]["findings_count"], 0)
        self.assertEqual(dashboard["coverage"]["assessed_chapters"], 1)
        self.assertEqual(dashboard["coverage"]["gaps"], 0)

    def test_risk_and_due_views(self):
        upsert_foreshadowing(self.db, "p1", {"title": "高风险伏笔", "importance": "critical", "target_chapter_number": 2})
        upsert_causal_edge(self.db, "p1", {"cause": "A", "effect": "B", "strength": 0.2})
        self.db.commit()
        self.assertEqual(len(governance_dashboard(self.db, "p1", chapter_id="c1", view="due")["foreshadowings"]), 1)
        risk = governance_dashboard(self.db, "p1", view="risk")
        self.assertEqual(len(risk["foreshadowings"]), 1)
        self.assertEqual(len(risk["causal_edges"]), 0)


if __name__ == "__main__":
    unittest.main()

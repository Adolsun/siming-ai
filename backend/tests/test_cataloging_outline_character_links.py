"""Cataloging must persist the selected identities and all authored character changes."""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import Base, Chapter, Character, CharacterVersion, OutlineNode, Project
from app.services.cataloging.applier import apply_candidates_for_run
from app.services.cataloging.candidate_store import create_candidate_from_raw
from app.services.cataloging.candidate_validation import inspect_candidate_coverage
from tests.test_cataloging_reconciliation import _candidate, _new_run, _summary


def _database():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_new_character_ids_bind_chapter_and_scenes_and_all_profile_fields_survive():
    with _database() as db:
        project = Project(id="p", title="建档关联")
        chapter = Chapter(
            id="chapter", project_id="p", title="第一章", content="旧身份。新增经历。"
        )
        existing = Character(
            id="existing", project_id="p", name="甲", background="旧身份。", personality="谨慎"
        )
        db.add_all([project, chapter, existing])
        db.commit()
        job, run = _new_run(db, project, chapter)
        new_id = str(uuid4())
        rows = [
            (
                "chapter_summary",
                _summary(
                    "甲在城中遇到乙，一起核对旧卷上的记录，并逐项确定下一步调查所需的证物以及交接时间。"
                ),
            ),
            (
                "outline_create",
                {
                    "node_type": "chapter",
                    "title": chapter.title,
                    "summary": "遇见乙",
                    "character_ids": [],
                },
            ),
            (
                "outline_create",
                {
                    "node_type": "section",
                    "scene_number": 1,
                    "title": "会面",
                    "summary": "核对证物",
                    "characters": ["甲", "乙"],
                    "character_ids": [existing.id, new_id],
                },
            ),
            ("character_create", {"client_id": new_id, "name": "乙", "background": "城中管事"}),
            (
                "character_update",
                {
                    "id": existing.id,
                    "name": existing.name,
                    "background_before": "旧身份。",
                    "background": "旧身份。新增经历。",
                    "personality": "谨慎而果断",
                    "profile": {"voice": "慢而稳"},
                },
            ),
            (
                "character_state_update",
                {
                    "id": existing.id,
                    "name": existing.name,
                    "current_goal": "找到证人",
                    "mental_state": "保持警惕",
                },
            ),
            (
                "chapter_link",
                {
                    "characters": [
                        {"name": "甲", "appearance_type": "出场"},
                        {"name": "乙", "appearance_type": "提及"},
                    ]
                },
            ),
        ]
        for order, (kind, payload) in enumerate(rows):
            _candidate(db, job, run, kind, payload, order)
        db.flush()
        events = apply_candidates_for_run(db, job, run)
        assert all(event["type"] == "candidate_applied" for event in events), events
        db.commit()
        db.expire_all()
        assert existing.current_version == 3
        assert existing.background == "旧身份。新增经历。"
        assert existing.personality == "谨慎而果断"
        assert existing.current_goal == "找到证人" and existing.mental_state == "保持警惕"
        assert existing.profile_json["voice"] == "慢而稳"
        assert db.query(CharacterVersion).filter_by(character_id=existing.id).count() == 2
        nodes = (
            db.query(OutlineNode).filter(OutlineNode.node_type.in_(["chapter", "section"])).all()
        )
        assert len(nodes) == 2
        for node in nodes:
            assert {link.character_id for link in node.linked_characters} == {existing.id, new_id}
        # Losing a persisted relation must prevent a "complete" coverage verdict.
        section = next(node for node in nodes if node.node_type == "section")
        section.linked_characters.clear()
        db.flush()
        coverage = inspect_candidate_coverage(run.candidates, db=db, project_id=project.id)
        assert any("大纲人物绑定未完成写入" in error for error in coverage.persistence_missing)


@pytest.mark.parametrize("value", [None, "甲", ["甲"], ["foreign"]])
def test_missing_names_and_foreign_ids_cannot_silently_drop_links(value):
    with _database() as db:
        project = Project(id="p", title="本作品")
        other = Project(id="other", title="另一作品")
        chapter = Chapter(id="chapter", project_id="p", title="第一章", content="正文")
        db.add_all(
            [project, other, chapter, Character(id="foreign", project_id="other", name="甲")]
        )
        db.commit()
        job, run = _new_run(db, project, chapter)
        candidate = _candidate(
            db,
            job,
            run,
            "outline_create",
            {
                "node_type": "chapter",
                "title": "拒绝写入",
                "summary": "不能留下部分内容",
                "character_ids": value,
            },
            0,
        )
        db.flush()
        events = apply_candidates_for_run(db, job, run)
        assert events[0]["type"] == "candidate_apply_failed"
        assert candidate.status == "apply_failed"
        assert db.query(OutlineNode).count() == 0


def test_retired_name_field_is_rejected_during_candidate_ingestion():
    with _database() as db:
        project = Project(id="p", title="结构校验")
        chapter = Chapter(id="chapter", project_id="p", title="第一章", content="正文")
        db.add_all([project, chapter])
        db.commit()
        job, run = _new_run(db, project, chapter)
        result = create_candidate_from_raw(
            db,
            job,
            run,
            {
                "type": "outline_create",
                "node_type": "chapter",
                "title": "第一章",
                "summary": "正文",
                "related_characters": ["甲"],
            },
            0,
        )
        assert "character_ids" in result["error"]
        assert "candidate" not in result

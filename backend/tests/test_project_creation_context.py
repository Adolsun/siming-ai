"""Creation constraints stay authoritative after a project is created."""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.models import NovelCreationSession, Project
from app.database.session import Base
from app.services.content_store import MANIFEST_NAME, write_project_manifest
from app.services.project_creation_context import resolve_project_creation_session
from app.services.workspace.tools.projects import (
    get_project_creation_brief,
    get_project_info,
    update_project_creation_brief,
)


def _creation_draft(*, target_words: int, target_chapters: int) -> dict:
    form = {
        "brief": "一部长篇东方幻想小说",
        "genre": "东方幻想",
        "target_words": target_words,
        "target_chapters": target_chapters,
        "opening_chapters": 3,
    }
    return {
        "form": form,
        "selected_concept_id": "concept-1",
        "stages": {
            "constraints": {"status": "confirmed", "data": form},
            "concepts": {
                "status": "confirmed",
                "data": {
                    "selected_concept_id": "concept-1",
                    "options": [
                        {
                            "id": "concept-1",
                            "title": "万象归墟",
                            "logline": "凡人以记录对抗世界遗忘。",
                        }
                    ],
                },
            },
            "characters": {"status": "generated", "data": {}},
            "world_style": {"status": "pending", "data": None},
        },
    }


def _db() -> tuple[object, Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return engine, Session(engine)


def test_project_tool_and_manifest_expose_authoritative_creation_constraints(tmp_path):
    engine, db = _db()
    try:
        project = Project(id="project-created", title="万象归墟", folder_path=str(tmp_path))
        creation = NovelCreationSession(
            id="creation-authoritative",
            created_project_id=project.id,
            status="completed",
            revision=9,
            draft_json=_creation_draft(target_words=2_500_000, target_chapters=1_000),
        )
        db.add_all([project, creation])
        db.commit()

        result = asyncio.run(get_project_info(db, project.id, {}))
        context = result["data"]["creation"]
        assert context["creation_session_id"] == creation.id
        assert context["constraints"]["target_words"] == 2_500_000
        assert context["constraints"]["target_chapters"] == 1_000
        assert context["confirmed_artifacts"] == ["constraints", "concepts"]
        assert "constraints" not in context["pending_artifacts"]
        assert set(context["pending_artifacts"]) == {"characters", "world_style"}

        write_project_manifest(db, project)
        manifest = json.loads((tmp_path / MANIFEST_NAME).read_text(encoding="utf-8"))
        assert manifest["creation"] == context
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_source_session_that_created_another_project_cannot_leak():
    engine, db = _db()
    try:
        source = Project(id="source-project", title="原作品")
        created = Project(id="new-project", title="新作品")
        leaked = NovelCreationSession(
            id="creation-for-new-project",
            source_project_id=source.id,
            created_project_id=created.id,
            status="completed",
            draft_json=_creation_draft(target_words=2_500_000, target_chapters=1_000),
        )
        in_place = NovelCreationSession(
            id="source-in-place-draft",
            source_project_id=source.id,
            status="reviewing",
            draft_json=_creation_draft(target_words=600_000, target_chapters=240),
        )
        db.add_all([source, created, leaked, in_place])
        db.commit()

        resolved = resolve_project_creation_session(
            db,
            source.id,
            requested_session_id=leaked.id,
        )
        assert resolved is not None
        assert resolved.id == in_place.id
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def test_imported_project_can_create_and_update_an_authoritative_creation_brief():
    engine, db = _db()
    try:
        project = Project(
            id="imported-project",
            title="导入作品",
            description="一部已写到第二卷的修仙长篇",
            writing_style="natural",
        )
        db.add(project)
        db.commit()

        before = asyncio.run(get_project_creation_brief(db, project.id, {}))
        assert before["status"] == "ok"
        assert before["data"]["creation"] is None

        updated = asyncio.run(update_project_creation_brief(db, project.id, {
            "constraints": {
                "target_words": 2_500_000,
                "target_chapters": 1_000,
                "writing_style": "克制、冷峻，以动作和细节推进",
                "special_requirements": ["信息必须跨章一致", "升级必须有代价"],
            },
            "creative_direction": {
                "selected": {
                    "title": "经脉迷局",
                    "logline": "穿越者以现代实验方法破解家族修炼体系。",
                    "core_conflict": "求真与宗族秩序冲突",
                },
            },
            "world_style": {
                "tone": "家族权谋与修炼实验并行",
                "prose_style": "少解释，多可验证细节",
            },
        }))

        assert updated["status"] == "ok"
        assert set(updated["data"]["changed_artifacts"]) == {"constraints", "concepts", "world_style"}
        context = updated["data"]["creation"]
        assert context["constraints"]["target_words"] == 2_500_000
        assert context["constraints"]["target_chapters"] == 1_000
        assert context["creative_direction"]["selected"]["title"] == "经脉迷局"
        assert context["world_style"]["tone"] == "家族权谋与修炼实验并行"
        assert project.custom_style_prompt == "克制、冷峻，以动作和细节推进"
        assert db.query(NovelCreationSession).filter_by(created_project_id=project.id).count() == 1

        # A second update reuses the same project-linked session.
        second = asyncio.run(update_project_creation_brief(db, project.id, {
            "constraints": {"target_chapters": 1_200},
        }))
        assert second["data"]["creation_session_id"] == updated["data"]["creation_session_id"]
        assert second["data"]["creation"]["constraints"]["target_chapters"] == 1_200
        assert db.query(NovelCreationSession).filter_by(created_project_id=project.id).count() == 1
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()

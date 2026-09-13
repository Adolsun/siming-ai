"""End-to-end checks for cataloging character and source coverage."""
from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    Base,
    CatalogingCandidate,
    CatalogingFact,
    Chapter,
    Character,
    CharacterAlias,
    CharacterRelationship,
    CharacterTimeline,
    Project,
    WorldbuildingEntry,
    WorldbuildingTimeline,
)
from app.services.cataloging.candidate_validation import (
    candidate_coverage_review_message,
    inspect_candidate_coverage,
)
from app.services.cataloging.character_ops import (
    apply_character_create,
    apply_character_relationship,
)
from app.services.cataloging.orchestrator import (
    create_cataloging_job,
)
from app.services.cataloging.snapshots import character_snapshot


def database():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def summary_payload(**manifest):
    return {
        "summary_text": "本章事实摘要。",
        "coverage_manifest": {
            "scene_count": 1,
            "characters": [],
            "worldbuilding": [],
            "relationships": [],
            "character_profiles": [],
            **manifest,
        },
        "narrative_state": {
            "events": [],
            "foreshadowing_planted": [],
            "foreshadowing_resolved": [],
            "storyline_progress": [],
            "unresolved_actions": [],
        },
        "narrative_review": {"source": "provided", "outcome": "assessed"},
    }


def candidate(db, job, run, chapter, item_type, payload, sort_order=0):
    row = CatalogingCandidate(
        job_id=job.id,
        chapter_run_id=run.id,
        project_id=chapter.project_id,
        chapter_id=chapter.id,
        item_type=item_type,
        raw_payload=json.dumps(payload, ensure_ascii=False),
        sort_order=sort_order,
    )
    db.add(row)
    db.flush()
    return row










def test_persistence_coverage_errors_are_presented_in_chinese():
    engine, db = database()
    try:
        project = Project(id="project-1", title="错误提示")
        chapter = Chapter(id="chapter-1", project_id=project.id, title="第一章", content="张三出现。")
        db.add_all([project, chapter])
        db.commit()
        job = create_cataloging_job(db, project.id, "auto", "deepseek:test", [chapter.id])
        run = job.chapter_runs[0]
        db.add(CatalogingFact(
            job_id=job.id,
            chapter_run_id=run.id,
            project_id=project.id,
            chapter_id=chapter.id,
            fact_type="character_fact",
            raw_payload=json.dumps({
                "name": "张三",
                "archive_identity": "stable_character",
                "stable_profile_change": False,
            }, ensure_ascii=False),
            status="active",
        ))
        rows = [
            candidate(db, job, run, chapter, "chapter_summary", summary_payload()),
            candidate(db, job, run, chapter, "outline_create", {
                "character_ids": [],
                "node_type": "chapter", "title": chapter.title, "summary": "张三出现。",
            }, 1),
        ]

        message = candidate_coverage_review_message(
            inspect_candidate_coverage(rows, db=db, project_id=project.id)
        )

        assert "章节摘要少于40个非空白字符" in message
        assert "source characters missing" not in message
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
















def test_relationship_applier_never_manufactures_blank_character_cards():
    engine, db = database()
    try:
        project = Project(id="project-1", title="关系引用")
        chapter = Chapter(id="chapter-1", project_id=project.id, title="第一章", content="甲拜乙为师。")
        db.add_all([project, chapter])
        db.commit()
        job = create_cataloging_job(db, project.id, "auto", "deepseek:test", [chapter.id])
        run = job.chapter_runs[0]
        row = candidate(db, job, run, chapter, "character_relationship", {
            "source_name": "甲",
            "target_name": "乙",
            "relationship_type": "师徒",
        })

        with pytest.raises(ValueError, match="chapter_summary"):
            apply_character_relationship(db, row, chapter, json.loads(row.raw_payload))

        assert db.query(Character).count() == 0
        assert db.query(CharacterRelationship).count() == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_relationship_applier_updates_existing_directed_pair_when_type_changes():
    engine, db = database()
    try:
        project = Project(id="project-1", title="关系更新")
        chapter = Chapter(
            id="chapter-1",
            project_id=project.id,
            title="第一章",
            content="甲与乙从临时协作变成调查搭档。",
        )
        source = Character(id="character-a", project_id=project.id, name="甲")
        target = Character(id="character-b", project_id=project.id, name="乙")
        relationship = CharacterRelationship(
            id="relationship-1",
            project_id=project.id,
            character_a_id=source.id,
            character_b_id=target.id,
            relationship_type="协作",
            description="两人临时协作。",
        )
        db.add_all([project, chapter, source, target, relationship])
        db.commit()
        job = create_cataloging_job(db, project.id, "auto", "deepseek:test", [chapter.id])
        run = job.chapter_runs[0]
        row = candidate(db, job, run, chapter, "character_relationship", {
            "source_name": "甲",
            "target_name": "乙",
            "relationship_type": "调查搭档",
            "description": "两人共同核验证据。",
        })

        from tests.cataloging_plan_fixtures import complete_fixture_plan
        complete_fixture_plan(db, job, run)
        result = apply_character_relationship(db, row, chapter, json.loads(row.raw_payload))
        db.flush()

        relationships = db.query(CharacterRelationship).all()
        assert len(relationships) == 1
        assert relationships[0].id == "relationship-1"
        assert relationships[0].relationship_type == "调查搭档"
        assert "共同核验证据" in relationships[0].description
        assert result["target_id"] == "relationship-1"
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()

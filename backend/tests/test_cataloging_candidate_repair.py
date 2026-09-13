"""Regression tests for the core cumulative cataloging repair path."""
from __future__ import annotations

import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (
    Base,
    CatalogingCandidate,
    CatalogingFact,
    Chapter,
    Character,
    OutlineNode,
    Project,
    WorldbuildingEntry,
    WorldbuildingTimeline,
)
from app.services.cataloging.candidate_store import create_candidate_from_raw
from app.services.cataloging.applier import apply_candidates_for_run
from app.services.cataloging.outline_ops import apply_outline
from app.services.cataloging.candidate_validation import (
    candidate_coverage_error_message,
    candidate_coverage_should_retry,
    inspect_candidate_coverage,
)
from app.services.cataloging.orchestrator import (
    create_cataloging_job,
)


def database():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine)()


def summary_payload(**manifest):
    return {
        "summary_text": "本章完成了可验证的连续性变化。",
        "scenes": ["场景" for _ in range(manifest.get("scene_count", 1))],
        "character_bindings": [], "worldbuilding_bindings": [],
        "coverage_manifest": {
            "scene_count": 1,
            "characters": [],
            "worldbuilding": [],
            "relationships": [],
            "character_profiles": [],
            **manifest,
        },
        "narrative_state": {
            "events": [{"title": "本章事件", "description": "事件已经发生"}],
            "timeline_events": [],
            "foreshadowing_planted": [],
            "foreshadowing_resolved": [],
            "storyline_progress": [],
            "new_storylines": [],
            "reader_known_facts": [],
            "character_known_facts": [],
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
        status="pending",
    )
    db.add(row)
    db.flush()
    return row


def base_rows(db, job, run, chapter, **manifest):
    return [
        candidate(
            db,
            job,
            run,
            chapter,
            "chapter_summary",
            summary_payload(**manifest),
        ),
        candidate(
            db,
            job,
            run,
            chapter,
            "outline_create",
            {
                "character_ids": [],
                "node_type": "chapter",
                "title": chapter.title,
                "summary": "本章结构摘要。",
            },
            1,
        ),
    ]




def test_existing_unchanged_worldbuilding_requires_link_not_fake_update():
    engine, db = database()
    try:
        project = Project(id="project-1", title="既有设定引用")
        chapter = Chapter(
            id="chapter-1",
            project_id=project.id,
            title="第一章",
            content="系统再次出现。",
        )
        entry = WorldbuildingEntry(
            project_id=project.id,
            dimension="power_system",
            title="系统",
            content="既有设定。",
        )
        db.add_all([project, chapter, entry])
        db.commit()
        job = create_cataloging_job(
            db,
            project.id,
            "auto",
            "deepseek:test",
            [chapter.id],
        )
        run = job.chapter_runs[0]
        rows = base_rows(db, job, run, chapter, worldbuilding=["系统"])
        rows.append(
            candidate(
                db,
                job,
                run,
                chapter,
                "chapter_link",
                {
                    "worldbuilding_titles": ["系统"],
                    "description": "本章关键引用",
                },
                2,
            )
        )

        coverage = inspect_candidate_coverage(
            rows,
            db=db,
            project_id=project.id,
        )

        assert coverage.is_complete is True
        assert coverage.worldbuilding_candidate_count == 1
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()








def test_real_missing_identity_is_retryable_and_reported_exactly():
    engine, db = database()
    try:
        project = Project(id="project-1", title="定向补缺")
        chapter = Chapter(
            id="chapter-1",
            project_id=project.id,
            title="第一章",
            content="系统启动归墟。",
        )
        db.add_all([project, chapter])
        db.commit()
        job = create_cataloging_job(
            db,
            project.id,
            "auto",
            "deepseek:test",
            [chapter.id],
        )
        run = job.chapter_runs[0]
        rows = base_rows(
            db,
            job,
            run,
            chapter,
            worldbuilding=["系统", "归墟"],
        )
        rows.extend(
            [
                candidate(
                    db,
                    job,
                    run,
                    chapter,
                    "worldbuilding_create",
                    {
                        "title": "系统",
                        "dimension": "power_system",
                        "content": "负责引导探索。",
                    },
                    2,
                ),
                candidate(
                    db,
                    job,
                    run,
                    chapter,
                    "chapter_link",
                    {"worldbuilding_titles": ["系统", "归墟"]},
                    3,
                ),
            ]
        )

        coverage = inspect_candidate_coverage(
            rows,
            db=db,
            project_id=project.id,
        )
        message = candidate_coverage_error_message(coverage)

        assert coverage.is_complete is False
        assert candidate_coverage_should_retry(coverage) is True
        assert "归墟" in message
        assert "缺少世界观候选或既有设定关联" in message
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()




def test_incremental_section_retry_updates_same_scene_number_instead_of_duplicating():
    engine, db = database()
    try:
        project = Project(id="project-scene-retry", title="场景候选去重")
        chapter = Chapter(
            id="chapter-scene-retry",
            project_id=project.id,
            title="第一章",
            content="正文。",
        )
        db.add_all([project, chapter])
        db.commit()
        job = create_cataloging_job(
            db,
            project.id,
            "auto",
            "deepseek:test",
            [chapter.id],
        )
        run = job.chapter_runs[0]
        create_candidate_from_raw(db, job, run, {"type": "chapter_summary", **summary_payload(scene_count=4)}, 0)


        first = create_candidate_from_raw(
            db,
            job,
            run,
            {
                "character_ids": [],
                "type": "outline_create",
                "node_type": "section",
                "scene_number": 4,
                "title": "第一章 / 播发与说明",
                "summary": "首次场景摘要。",
                "purpose": "推进播发流程",
                "entry_state": "稿件待发",
                "exit_state": "稿件播发",
            },
            1,
        )
        second = create_candidate_from_raw(
            db,
            job,
            run,
            {
                "character_ids": [],
                "type": "outline_create",
                "node_type": "section",
                "scene_number": 4,
                "title": "第一章 / 播发与补发函",
                "summary": "重试后的完整场景摘要。",
                "purpose": "落实播发与补发函",
                "entry_state": "稿件待发",
                "exit_state": "加注与补发函落地",
            },
            2,
        )

        assert first.get("candidate") is not None
        assert second.get("updated") is True
        rows = db.query(CatalogingCandidate).filter_by(chapter_run_id=run.id, item_type="outline_create").all()
        assert len(rows) == 1
        payload = json.loads(rows[0].raw_payload)
        assert payload["scene_number"] == 4
        assert payload["title"] == "第一章 / 播发与补发函"
        assert payload["summary"] == "重试后的完整场景摘要。"
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_section_apply_reuses_cataloged_scene_number_when_retry_changes_title():
    engine, db = database()
    try:
        project = Project(id="project-scene-apply", title="场景投影去重")
        volume = OutlineNode(
            id="volume-1",
            project_id=project.id,
            node_type="volume",
            title="第一卷",
        )
        chapter_outline = OutlineNode(
            id="outline-chapter-1",
            project_id=project.id,
            parent_id=volume.id,
            node_type="chapter",
            title="第一章",
        )
        chapter = Chapter(
            id="chapter-scene-apply",
            project_id=project.id,
            outline_node_id=chapter_outline.id,
            title="第一章",
            content="正文。",
        )
        existing = OutlineNode(
            id="section-scene-4",
            project_id=project.id,
            parent_id=chapter_outline.id,
            node_type="section",
            title="第一章 / 播发与说明",
            source_chapter_id=chapter.id,
            cataloging_status="cataloged",
            metadata_json={"scene_number": 4},
        )
        db.add_all([project, volume, chapter_outline, chapter, existing])
        db.commit()
        job = create_cataloging_job(
            db,
            project.id,
            "auto",
            "deepseek:test",
            [chapter.id],
        )
        run = job.chapter_runs[0]
        row = candidate(
            db,
            job,
            run,
            chapter,
            "outline_create",
            {
                "character_ids": [],
                "node_type": "section",
                "scene_number": 4,
                "title": "第一章 / 播发与补发函",
                "summary": "更新后的场景摘要。",
                "purpose": "落实播发与补发函",
                "entry_state": "稿件待发",
                "exit_state": "补发函落地",
            },
            1,
        )

        result = apply_outline(
            db,
            row,
            chapter,
            json.loads(row.raw_payload),
            True,
        )
        db.flush()

        assert result["target_id"] == existing.id
        assert db.query(OutlineNode).filter_by(
            project_id=project.id,
            source_chapter_id=chapter.id,
            node_type="section",
        ).count() == 1
        assert existing.title == "第一章 / 播发与补发函"
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()




def test_worldbuilding_update_rejects_foreign_or_missing_exact_id_before_staging():
    engine, db = database()
    try:
        project = Project(id="project-world-id", title="世界观 ID 校验")
        chapter = Chapter(
            id="chapter-world-id",
            project_id=project.id,
            title="第一章",
            content="正文。",
        )
        db.add_all([project, chapter])
        db.commit()
        job = create_cataloging_job(
            db,
            project.id,
            "auto",
            "deepseek:test",
            [chapter.id],
        )
        run = job.chapter_runs[0]

        result = create_candidate_from_raw(
            db,
            job,
            run,
            {
                "type": "worldbuilding_update",
                "id": "missing-world-id",
                "title": "不存在的设定",
                "content": "不得写入。",
            },
            1,
        )

        assert result.get("bad_line")
        assert "目标 ID 不存在或不属于当前作品" in result["error"]
        assert db.query(CatalogingCandidate).filter_by(chapter_run_id=run.id).count() == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


def test_worldbuilding_update_and_timeline_reject_inactive_exact_ids_before_staging():
    engine, db = database()
    try:
        project = Project(id="project-world-inactive", title="停用世界观 ID 校验")
        chapter = Chapter(
            id="chapter-world-inactive",
            project_id=project.id,
            title="第一章",
            content="正文仍提到旧称，但该词条已由作者停用。",
        )
        entry = WorldbuildingEntry(
            id="retired-world-id",
            project_id=project.id,
            title="旧版错误地点",
            dimension="geography",
            content="已经停用的错误条目。",
            status="superseded",
        )
        db.add_all([project, chapter, entry])
        db.commit()
        job = create_cataloging_job(
            db,
            project.id,
            "auto",
            "deepseek:test",
            [chapter.id],
        )
        run = job.chapter_runs[0]

        raws = [
            {
                "type": "worldbuilding_update",
                "id": entry.id,
                "title": entry.title,
                "content": "不得重新写入。",
            },
            {
                "type": "worldbuilding_timeline",
                "id": entry.id,
                "title": entry.title,
                "event_description": "不得挂接时间线。",
            },
        ]
        for sort_order, raw in enumerate(raws, 1):
            result = create_candidate_from_raw(db, job, run, raw, sort_order)
            assert result.get("bad_line")
            assert "目标 ID 已停用" in result["error"]

        assert db.query(CatalogingCandidate).filter_by(chapter_run_id=run.id).count() == 0
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()






def test_scene_gap_reports_the_exact_scene_number_for_incremental_repair():
    engine, db = database()
    try:
        project = Project(id="project-1", title="场景补缺")
        chapter = Chapter(
            id="chapter-1",
            project_id=project.id,
            title="第一章",
            content="正文包含六个连续场景。",
        )
        db.add_all([project, chapter])
        db.commit()
        job = create_cataloging_job(
            db,
            project.id,
            "auto",
            "deepseek:test",
            [chapter.id],
        )
        run = job.chapter_runs[0]
        base_rows(db, job, run, chapter, scene_count=6)
        for scene_number in range(1, 6):
            candidate(
                db,
                job,
                run,
                chapter,
                "outline_create",
                {
                    "character_ids": [],
                    "node_type": "section",
                    "title": f"第一章 / 场景{scene_number}",
                    "summary": f"场景 {scene_number}",
                    "scene_number": scene_number,
                    "purpose": "推进情节",
                    "location": "山门",
                    "entry_state": "进入场景",
                    "exit_state": "离开场景",
                },
                scene_number + 1,
            )

        message = _candidate_coverage_error(db, run)

        assert "section outlines for declared scenes (5/6)" in message
        assert "缺少 section 场景编号：6" in message
        assert "缺少场景状态字段的 scene_number：6" in message
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()




def test_candidate_coverage_rejects_more_sections_than_declared_scenes():
    engine, db = database()
    try:
        project = Project(id="project-scene-overflow", title="场景数量上限")
        chapter = Chapter(
            id="chapter-scene-overflow",
            project_id=project.id,
            title="第一章",
            content="正文。",
        )
        db.add_all([project, chapter])
        db.commit()
        job = create_cataloging_job(
            db,
            project.id,
            "auto",
            "deepseek:test",
            [chapter.id],
        )
        run = job.chapter_runs[0]
        rows = base_rows(db, job, run, chapter, scene_count=2)
        for scene_number in range(1, 4):
            rows.append(candidate(
                db,
                job,
                run,
                chapter,
                "outline_create",
                {
                    "character_ids": [],
                    "node_type": "section",
                    "title": f"第一章 / 场景{scene_number}",
                    "summary": f"场景 {scene_number}",
                    "scene_number": scene_number,
                    "purpose": "推进情节",
                    "location": "会议室",
                    "entry_state": "进入场景",
                    "exit_state": "离开场景",
                },
                scene_number + 1,
            ))

        coverage = inspect_candidate_coverage(rows, db=db, project_id=project.id)

        assert coverage.is_complete is False
        assert (
            "section outline candidates require unique scene_number within 1..2: "
            "out_of_range=3"
        ) in coverage.cli_parity_missing
    finally:
        db.close()
        Base.metadata.drop_all(engine)
        engine.dispose()



from app.services.cataloging.candidate_retry import candidate_coverage_error as _candidate_coverage_error

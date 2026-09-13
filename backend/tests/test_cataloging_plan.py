"""Single Agent decisions, explicit bindings and atomic chapter application."""
import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import (Base, Project, Chapter, Character, CatalogingFact,
                                 CatalogingCandidate, CatalogingApplyLog, ChapterSummary, OutlineNode)
from app.services.cataloging.orchestrator import create_cataloging_job
from app.services.cataloging import applier
from app.services.cataloging.plan_contract import validate_plan_references
from app.services.workspace.tools.external_cataloging import save_external_cataloging_candidates
from app.modules.continuity.domain.candidate_contract import validate_candidate_fields
from app.services.workspace.registry import registry


@pytest.fixture
def archive(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'plan.db').as_posix()}")
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine)() as db:
        db.add(Project(id="p", title="回归作品"))
        db.add(Chapter(id="c", project_id="p", title="旧炉", content="少年走近旧炉。一团红色残影回答他的问题，承认自己正是炉灵。"))
        db.commit()
        job = create_cataloging_job(db, "p", "manual", "test:model", ["c"])
        job.status = "running"
        run = job.chapter_runs[0]
        run.status = "extracting"
        db.commit()
        yield db, job, run
    engine.dispose()


def plan_rows(character=None):
    names = [character.name] if character else []
    ids = [character.id] if character else []
    summary = {"type": "chapter_summary", "summary_text": "少年走近旧炉后遇到一团红色残影，对方回答了少年的提问并确认自己就是此前已有档案的炉灵。本章记录了身份确认过程以及炉灵当前的状态，尚未确认的其他信息保留待后文核实。",
               "scenes": ["旧炉旁的交谈"], "character_bindings": [{"name": character.name, "id": character.id,
                    "decision": "existing", "source_labels": ["红色残影"], "reason": "本章对话确认身份"}] if character else [],
               "worldbuilding_bindings": [],
               "coverage_manifest": {"scene_count": 1, "characters": names, "worldbuilding": [],
                                     "relationships": [], "character_profiles": []},
               "narrative_state": {}, "narrative_review": {"source": "provided", "outcome": "assessed"}}
    rows = [summary, {"type": "outline_create", "title": "旧炉", "node_type": "chapter", "summary": "单场景：旧炉旁的交谈确认身份。", "character_ids": ids}]
    if character:
        rows.extend([{"type": "character_state_update", "id": character.id, "name": character.name, "mental_state": "愿意交谈"},
                     {"type": "chapter_link", "characters": [{"name": character.name, "appearance_type": "出场"}],
                      "worldbuilding_titles": [], "locations": [], "items": [], "events": []}])
    return rows


def submit(archive, rows, finalize=True):
    db, job, run = archive
    return asyncio.run(save_external_cataloging_candidates(db, job.project_id,
                       {"job_id": job.id, "chapter_id": run.chapter_id, "candidates": rows, "finalize": finalize}))


def test_old_anonymous_fact_cannot_veto_current_model_binding(archive):
    db, job, run = archive
    character = Character(project_id="p", name="炉灵")
    db.add(character)
    db.flush()
    db.add(CatalogingFact(project_id="p", job_id=job.id, chapter_run_id=run.id, chapter_id="c",
        fact_type="character_fact", raw_payload=json.dumps({"primary_name": "红色残影", "archive_identity": "anonymous_role"})))
    db.commit()
    result = submit(archive, plan_rows(character))
    assert result["data"]["candidate_set_complete"], result["data"]
    assert db.query(CatalogingApplyLog).count() == 0, "manual confirmation is required"


def test_unbound_narrative_label_is_not_a_character_reference(archive):
    db, _, run = archive
    summary = plan_rows()[0]
    summary["coverage_manifest"]["characters"] = ["红色残影"]
    with pytest.raises(ValueError, match="未绑定"):
        validate_plan_references(db, "p", run, {"item_type": "chapter_summary", "payload": summary})
    summary["coverage_manifest"]["characters"] = []
    validate_plan_references(db, "p", run, {"item_type": "chapter_summary", "payload": summary})


@pytest.mark.parametrize("kind,payload,error", [
    ("character_update", {"id": "test", "profile": {"reveal_chapter": "旧炉"}}, "reveal_chapter"),
    ("character_state_update", {"id": "test", "items_or_assets": []}, "items_or_assets"),
    ("chapter_link", {"importance": "high"}, "importance"),
])
def test_model_field_errors_use_the_same_exported_contract(kind, payload, error):
    with pytest.raises(ValueError, match=error):
        validate_candidate_fields(kind, payload)
    with pytest.raises(ValueError):
        registry.get_spec("save_external_cataloging_candidates").validate_input({
            "job_id": "job", "chapter_id": "chapter", "candidates": [{"type": kind, **payload}]})


def test_failed_candidate_preserves_accepted_plan_for_targeted_correction(archive):
    db, _, _ = archive
    rows = plan_rows()
    bad = {**rows[1], "character_ids": "[]"}
    result = submit(archive, [rows[0], bad])
    assert not result["data"]["candidate_set_complete"]
    assert len(result["data"]["candidate_errors"]) == 1
    summary_id = db.query(CatalogingCandidate).one().id
    result = submit(archive, [rows[1]])
    assert result["data"]["candidate_set_complete"], result
    assert db.query(CatalogingCandidate).filter_by(item_type="chapter_summary").one().id == summary_id


def test_finalization_is_explicit(archive):
    db, _, run = archive
    result = submit(archive, plan_rows(), finalize=False)
    assert not result["data"]["candidate_set_complete"]
    assert run.status == "extracting"
    assert submit(archive, [], finalize=True)["data"]["candidate_set_complete"]


def test_chapter_application_rolls_back_all_candidates_and_logs(archive, monkeypatch):
    db, job, run = archive
    assert submit(archive, plan_rows())["data"]["candidate_set_complete"]
    db.commit()
    original = applier.apply_candidate
    def fail_second(db, candidate):
        if candidate.item_type == "outline_create":
            raise ValueError("模拟第二项写入失败")
        return original(db, candidate)
    monkeypatch.setattr(applier, "apply_candidate", fail_second)
    events = applier.apply_candidates_for_run(db, job, run)
    db.commit()
    assert len(events) == 1 and events[0]["chapter_rolled_back"]
    assert db.query(ChapterSummary).count() == 0
    assert db.query(OutlineNode).count() == 0
    assert db.query(CatalogingApplyLog).count() == 0
    assert db.query(CatalogingCandidate).filter_by(status="applied").count() == 0
    monkeypatch.setattr(applier, "apply_candidate", original)
    assert all(e["type"] == "candidate_applied" for e in applier.apply_candidates_for_run(db, job, run))
    db.commit()
    assert db.query(ChapterSummary).count() == 1
    assert db.query(OutlineNode).filter_by(node_type="chapter").count() == 1
    assert applier.apply_candidates_for_run(db, job, run) == []
    assert db.query(CatalogingApplyLog).count() == 2


def test_stale_chapter_and_pause_prevent_submission(archive):
    db, job, run = archive
    job.status = "paused"
    db.commit()
    assert submit(archive, plan_rows())["status"] != "ok"
    job.status = "running"
    run.chapter.current_version += 1
    db.commit()
    assert submit(archive, plan_rows())["status"] != "ok"
    assert db.query(CatalogingCandidate).count() == 0


def test_cross_project_binding_is_rejected(archive):
    db, _, run = archive
    db.add(Project(id="other", title="其他作品"))
    person = Character(project_id="other", name="炉灵")
    db.add(person)
    db.commit()
    result = submit(archive, plan_rows(person))
    assert not result["data"]["candidate_set_complete"]
    assert "不属于当前作品" in str(result)


def test_api_native_agent_uses_shared_tools_and_finishes_one_plan(archive, monkeypatch, tmp_path):
    from app.services.cataloging import orchestrator
    from app.services.workspace.tools import external_cataloging
    db, job, run = archive
    chapter_file = tmp_path / "chapter.txt"
    chapter_file.write_text(run.chapter.content, encoding="utf-8")
    monkeypatch.setattr(external_cataloging, "ensure_chapter_mirror", lambda *a, **kw: (tmp_path, chapter_file))
    script = [("set_tool_categories", {"enabled_categories": ["cataloging"]}),
              ("get_next_external_cataloging_chapter", {"job_id": job.id, "include_prompt_pack": False}),
              ("read_cataloging_archive", {"kind": "character"}),
              ("save_external_cataloging_candidates", {"job_id": job.id, "chapter_id": "c", "candidates": plan_rows(), "finalize": True})]
    seen = []
    async def model(**kwargs):
        index = len(seen)
        seen.append(kwargs)
        name, args = script[index]
        yield {"type": "tool_call_delta", "index": 0, "id": f"native-{index}", "name": name,
               "arguments_delta": json.dumps(args, ensure_ascii=False)}
        yield {"type": "done", "reasoning_content": "", "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}}
    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion_with_tools", model)
    async def check():
        return [event async for event in orchestrator._extract_run(db, job, run)]
    events = asyncio.run(check())
    assert run.status == "awaiting_confirmation", events
    assert len(seen) == 4
    assert [tool["function"]["name"] for tool in seen[0]["tools"]] == ["set_tool_categories"]
    assert all("save_external_cataloging_facts" not in str(request["tools"]) for request in seen)
    assert any("read_cataloging_archive" in event for event in events)
    assert db.query(CatalogingApplyLog).count() == 0
    assert db.query(CatalogingFact).count() == 0


def test_late_api_result_cannot_write_after_pause(archive, monkeypatch):
    from app.services.cataloging import orchestrator
    db, job, run = archive
    async def model(**kwargs):
        job.status = "paused"
        db.commit()
        yield {"type": "tool_call_delta", "index": 0, "id": "late", "name": "set_tool_categories",
               "arguments_delta": '{"enabled_categories":["cataloging"]}'}
    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion_with_tools", model)
    async def check():
        return [event async for event in orchestrator._extract_run(db, job, run)]
    asyncio.run(check())
    assert db.query(CatalogingCandidate).count() == 0
    assert job.status == "paused"

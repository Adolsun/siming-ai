"""A rejected source mapping must be repaired on its worldbuilding candidate."""
import asyncio
import json

import pytest

from app.database.models import CatalogingCandidate, WorldbuildingEntry
from app.prompts.cataloging_source import (
    get_cataloging_candidate_schema,
    get_external_cataloging_system_prompt,
)
from app.services.cataloging import orchestrator
from app.services.cataloging.candidate_retry import candidate_issue, candidate_retry_reason
from app.services.cataloging.candidate_store import create_candidate_from_raw, try_create_candidates
from app.services.cataloging.fact_store import create_fact
from tests.test_cataloging_candidate_repair import summary_payload
from tests.test_cataloging_character_targets import archive as archive_fixture

archive = archive_fixture


@pytest.mark.parametrize("shape", ["wrapper", "payload", "flat"])
@pytest.mark.parametrize("mapping", [{"worldbuilding": ["原事实称呼"]}, ["原事实称呼"]])
def test_summary_source_mapping_is_rejected_with_the_actual_type(archive, shape, mapping):
    db, _, _, job, run = archive
    payload = {**summary_payload(), "source_fact_titles": mapping}
    if shape == "wrapper":
        raw = {"chapter_summary": payload}
    elif shape == "payload":
        raw = {"type": "chapter_summary", "payload": payload}
    else:
        raw = {"type": "chapter_summary", **payload}
    result = try_create_candidates(db, job, run, json.dumps(raw, ensure_ascii=False), 0)[0]
    assert "bad_line" in result
    issue = candidate_issue(result)
    assert issue["item_type"] == "chapter_summary"
    assert "当前候选是 chapter_summary" in issue["message"]
    assert "请从当前候选中移除该字段" in issue["message"]
    assert "另行输出" in issue["message"]
    assert db.query(CatalogingCandidate).count() == 0  # Never silently drop an invalid field.
    assert payload["source_fact_titles"] == mapping


@pytest.mark.parametrize("correct", [True, False], ids=["model-corrects-scope", "still-invalid"])
def test_saved_summary_can_be_repaired_separately_from_worldbuilding_source_mapping(
    archive, monkeypatch, correct,
):
    db, chapter, _, job, run = archive
    entry = WorldbuildingEntry(project_id=chapter.project_id, dimension="culture", title="校准规程",
                              content="校准规程已经生效。", status="active")
    db.add(entry)
    create_fact(db, job, run, {"fact_type": "worldbuilding_fact", "payload": {
        "canonical_title_hint": "校准事项", "archive_identity": "stable_setting",
        "stable_setting_change": True,
    }}, 0)
    original = summary_payload(worldbuilding=["校准事项"])
    original["summary_text"] = (
        "本章核验了现行校准规程，确认各项记录遵循一致的登记要求，并完成本轮资料复核。"
        "后续仍需按程序保存复核记录，尚未确认的问题继续保留，不据此产生新的独立设定。"
    )
    for index, row in enumerate([
        {"type": "chapter_summary", "payload": original},
        {"character_ids": [], "type": "outline_create", "title": chapter.title, "node_type": "chapter", "summary": "完成复核。"},
    ]):
        assert "candidate" in create_candidate_from_raw(db, job, run, row, index)
    db.commit()
    prior_ids = {row.id for row in db.query(CatalogingCandidate)}
    replacement = {**original, "coverage_manifest_mode": "replace",
                   "coverage_manifest": {**original["coverage_manifest"], "worldbuilding": [entry.title]}}
    rejected = {"chapter_summary": {**replacement, "source_fact_titles": {"worldbuilding": ["校准事项"]}}}
    calls = []

    async def stream(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1 or not correct:
            rows = [rejected]
        else:
            feedback = messages[1]["content"]
            assert '"item_type":"chapter_summary"' in feedback
            assert "当前候选是 chapter_summary" in feedback
            assert "请从当前候选中移除该字段" in feedback
            assert "另行输出对应 worldbuilding_update 或 worldbuilding_timeline" in feedback
            rows = [
                {"type": "chapter_summary", "payload": replacement},
                {"type": "worldbuilding_timeline", "id": entry.id, "title": entry.title,
                 "event_type": "confirmed", "event_description": "本章确认规程有效。",
                 "source_fact_titles": ["校准事项"]},
                {"type": "chapter_link", "worldbuilding_titles": [entry.title]},
            ]
        yield "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)

    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", stream)

    async def collect():
        return [event async for event in orchestrator._extract_run(db, job, run)]

    asyncio.run(collect())
    candidates = db.query(CatalogingCandidate).all()
    assert prior_ids <= {row.id for row in candidates}
    assert entry.content == "校准规程已经生效。"
    assert db.query(WorldbuildingEntry).count() == 1
    if correct:
        assert len(calls) == 2
        assert run.status == "awaiting_confirmation", run.error
        assert run.review_warning is None
        assert len(candidates) == 4
        summary = next(row for row in candidates if row.item_type == "chapter_summary")
        world = next(row for row in candidates if row.item_type == "worldbuilding_timeline")
        assert "source_fact_titles" not in json.loads(summary.raw_payload)
        assert json.loads(world.raw_payload)["source_fact_titles"] == ["校准事项"]
    else:
        assert len(calls) == 3
        assert run.status == "failed" and job.status == "paused_on_failure"
        assert len(candidates) == 2
        assert "当前候选是 chapter_summary" in run.error


def test_worldbuilding_examples_have_the_same_source_array_contract_for_both_entrypoints():
    schema = get_cataloging_candidate_schema()
    for item_type in ("worldbuilding_create", "worldbuilding_update", "worldbuilding_timeline"):
        example = next(line for line in schema.splitlines() if line.startswith(f"- {item_type}: "))
        payload = json.loads(example.split(": ", 1)[1])
        assert isinstance(payload["source_fact_titles"], list)
        assert all(isinstance(value, str) for value in payload["source_fact_titles"])
    for prompt in (get_external_cataloging_system_prompt(), orchestrator.CATALOGING_RESOLUTION_SYSTEM_PROMPT):
        assert "source_fact_titles 禁止放进 chapter_summary、coverage_manifest 或 chapter_link" in prompt


@pytest.mark.parametrize("incomplete_link", [False, True])
def test_retry_points_to_wrong_manifest_and_link_not_the_already_saved_worldbuilding(
    archive, monkeypatch, incomplete_link,
):
    db, chapter, _, job, run = archive
    entry = WorldbuildingEntry(project_id=chapter.project_id, dimension="history", title="馆藏卷宗",
                              content="已经入馆的卷宗。", status="active")
    db.add(entry)
    create_fact(db, job, run, {"fact_type": "worldbuilding_fact", "payload": {
        "canonical_title_hint": "001号卷", "archive_identity": "stable_setting",
        "stable_setting_change": True,
    }}, 0)
    summary = summary_payload(worldbuilding=["001号卷"])
    summary["summary_text"] = "本章核验了馆藏卷宗，确认现有记录与原始凭证一致，并将核验过程记录在案。" * 3
    rows = [
        {"type": "chapter_summary", "payload": summary},
        {"character_ids": [], "type": "outline_create", "title": chapter.title, "node_type": "chapter", "summary": "完成核验。"},
        {"type": "worldbuilding_timeline", "id": entry.id, "title": entry.title,
         "event_type": "confirmed", "event_description": "核验现有卷宗。", "source_fact_titles": ["001号卷"]},
        {"type": "chapter_link", "worldbuilding_titles": ["001号卷"]},
    ]
    for index, raw in enumerate(rows):
        assert "candidate" in create_candidate_from_raw(db, job, run, raw, index)
    db.commit()
    before = {r.id: r.raw_payload for r in db.query(CatalogingCandidate)}
    reason = orchestrator._candidate_coverage_error(db, run)
    assert reason
    feedback = json.loads(candidate_retry_reason(db, run, [], reason))
    repairs = feedback["coverage_repairs"]
    assert {r["field"] for r in repairs} == {"coverage_manifest.worldbuilding", "worldbuilding_titles"}
    assert all(r["current_value"] == "001号卷" and r["model_declared_title"] == entry.title
               and r["model_declared_target_id"] == entry.id for r in repairs)
    assert {r.id: r.raw_payload for r in db.query(CatalogingCandidate)} == before
    assert orchestrator._candidate_coverage_error(db, run) == reason  # The guard is unchanged.
    from app.services.workspace.tools.external_cataloging import save_external_cataloging_candidates
    run.status = "facts_saved"
    db.commit()
    cli_result = asyncio.run(save_external_cataloging_candidates(db, chapter.project_id, {
        "job_id": job.id, "chapter_id": chapter.id, "candidates": [],
    }))
    assert cli_result["data"]["coverage_repairs"] == repairs
    calls = []

    async def model(messages, **kwargs):
        calls.append(messages)
        assert '"coverage_repairs"' in messages[1]["content"]
        if len(calls) > 1:
            assert '"item_type":"chapter_link"' in messages[1]["content"]
            assert "missing or non-array fields" in messages[1]["content"]
        replacements = [
            {"type": "chapter_summary", "payload": {
                **summary, "coverage_manifest_mode": "replace",
                "coverage_manifest": {**summary["coverage_manifest"], "worldbuilding": [entry.title]},
            }},
            {"type": "chapter_link", "chapter_link_mode": "replace", "characters": [],
             "worldbuilding_titles": [entry.title], "locations": [], "items": [], "events": []},
        ]
        if incomplete_link and len(calls) == 1:
            for field in ("locations", "items", "events"):
                replacements[1].pop(field)
        for row in replacements:
            yield json.dumps(row, ensure_ascii=False) + "\n"

    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", model)

    async def check():
        return [raw async for raw in orchestrator._extract_run(db, job, run)]

    asyncio.run(check())
    assert len(calls) == (2 if incomplete_link else 1)
    assert run.status == "awaiting_confirmation", run.error
    assert {r.id for r in db.query(CatalogingCandidate)} == set(before)
    world = db.query(CatalogingCandidate).filter_by(item_type="worldbuilding_timeline").one()
    assert world.raw_payload == before[world.id]

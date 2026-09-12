"""Exact archive acknowledgement and actionable staged-model correction."""
import asyncio
import json

import pytest

from app.database.models import CatalogingCandidate, WorldbuildingEntry
from app.services.cataloging import orchestrator
from app.services.cataloging.candidate_retry import candidate_issue
from app.services.cataloging.candidate_store import create_candidate_from_raw, try_create_candidates
from app.services.cataloging.fact_store import create_fact
from app.services.cataloging.targeted_context import build_targeted_context
from tests.test_cataloging_candidate_repair import summary_payload
from tests.test_cataloging_character_targets import archive as archive_fixture

archive = archive_fixture


@pytest.mark.parametrize("local_runtime", [False, True], ids=["api", "local-runtime"])
def test_delivered_identity_review_satisfies_the_same_guard_for_all_related_cards(archive, local_runtime):
    db, chapter, _, job, run = archive
    entries = [WorldbuildingEntry(
        project_id=chapter.project_id, title=f"档案制度 {index}", dimension="culture",
        content="现有流程的档案制度。", status="active",
    ) for index in range(9)]  # More than the former local-runtime six-card excerpt.
    excluded = WorldbuildingEntry(
        project_id=chapter.project_id, title="档案制度旧版", dimension="culture",
        content="已过期的档案制度。", status="superseded",
    )
    db.add_all([*entries, excluded])
    facts = [{"fact_type": "worldbuilding_fact", "payload": {
        "canonical_title_hint": "档案制度", "details": "核对现有档案制度及本章独立机构。",
    }}]
    create_fact(db, job, run, facts[0], 0)
    db.commit()
    context = build_targeted_context(db, chapter.project_id, chapter, facts)
    if local_runtime:
        context = orchestrator._compact_local_runtime_context(context)
    delivered_ids = [row["id"] for row in context["worldbuilding_identity_review_required"]]
    assert set(delivered_ids) == {row.id for row in entries}
    assert {row["id"] for row in context["relevant_worldbuilding"]} == set(delivered_ids)
    raw = {
        "type": "worldbuilding_create", "title": "独立鉴定机构", "dimension": "factions",
        "content": "具备独立人员和独立授权的鉴定机构。",
        "identity_resolution": {
            "decision": "create", "reviewed_existing_ids": delivered_ids[:-1],
            "reason": "旧卡是档案制度，本条是具有独立人员及授权的机构，不能混为同一身份。",
        },
    }
    rejected = create_candidate_from_raw(db, job, run, raw, 0)
    assert "未覆盖本章已交付" in rejected["error"]
    assert delivered_ids[-1] in rejected["error"]
    raw["identity_resolution"]["reviewed_existing_ids"] = delivered_ids
    accepted = create_candidate_from_raw(db, job, run, raw, 0)
    assert "candidate" in accepted, accepted
    assert db.query(WorldbuildingEntry).count() == 10  # A pending candidate only.


@pytest.mark.parametrize("local_runtime", [False, True], ids=["api", "local-runtime"])
@pytest.mark.parametrize("field", ["items_or_assets", "background", "appearance"])
def test_delivered_full_field_can_pass_the_unchanged_write_guard(archive, field, local_runtime):
    db, chapter, character, job, run = archive
    original = " 逐字保留的历史档案𠮷🙂\n" * 150 + "末尾也不能丢失。 "
    setattr(character, field, original)
    chapter.content = "主角披上红衣，又收到一份回执。"
    db.commit()
    context = build_targeted_context(db, chapter.project_id, chapter, [
        {"fact_type": "character_fact", "payload": {"name": character.name}},
    ])
    if local_runtime:
        context = orchestrator._compact_local_runtime_context(context)
    delivered = next(row for row in context["relevant_characters"] if row["id"] == character.id)
    assert delivered[field] == original
    payload = {
        "type": "character_update" if field == "background" else "character_state_update",
        "id": delivered["id"], "name": character.name,
        field: original + "本章新增状态。", f"{field}_before": delivered[field],
    }
    if field == "appearance":
        payload.update(appearance="红衣", appearance_evidence="主角披上红衣")
    accepted = create_candidate_from_raw(db, job, run, payload, 0)
    assert "candidate" in accepted, accepted
    assert getattr(character, field) == original  # Only a pending candidate, not an author write.

    # Preserving the read cannot weaken stale/partial-write rejection.
    rejected = create_candidate_from_raw(db, job, run, {
        **payload, f"{field}_before": original[:260] + "...",
    }, 1)
    assert "bad_line" in rejected
    assert f"{field}_before" in rejected["error"]
    assert candidate_issue(rejected)["repair_context"] == {
        "target_id": character.id, "field": f"{field}_before", "expected_value": original,
    }
    assert db.query(CatalogingCandidate).filter_by(chapter_run_id=run.id).count() == 1


@pytest.mark.parametrize("repair", [True, False], ids=["model-corrects-id", "model-still-invalid"])
def test_staged_retry_delivers_validation_coverage_and_accepted_candidates(archive, monkeypatch, repair):
    db, chapter, character, job, run = archive
    calls = []
    preserved_ids = []

    async def stream(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            yield json.dumps({"fact_type": "chapter_overview", "payload": {
                "summary": "主角认真核对档案。",
            }}, ensure_ascii=False) + "\n"
            return
        candidate = {"type": "character_update", "name": character.name, "personality": "仔细核对证据"}
        if len(calls) == 2:
            rows = [
                {"type": "chapter_summary", "payload": summary_payload(character_profiles=[character.name])},
                {"character_ids": [], "type": "outline_create", "title": chapter.title, "node_type": "chapter", "summary": "核对档案。"},
                candidate,
            ]
        else:
            retry = messages[1]["content"]
            assert "character_update 必须填写已读取的真实角色 id" in retry
            assert '"candidate_errors"' in retry and '"coverage_error"' in retry
            assert '"rejected_candidate"' in retry and '"personality":"仔细核对证据"' in retry
            assert "缺少角色资料候选" in retry
            assert '"accepted_candidates"' in retry
            passed = db.query(CatalogingCandidate).filter_by(chapter_run_id=run.id).all()
            assert len(passed) == 2
            preserved_ids[:] = [row.id for row in passed]
            assert all(identity in retry for identity in preserved_ids)
            if repair:
                candidate["id"] = character.id
            rows = [candidate]
        # Include an unterminated final record to exercise the streaming tail too.
        yield "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)

    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", stream)

    async def collect():
        return [json.loads(event.removeprefix("data: "))
                async for event in orchestrator._extract_run(db, job, run)]

    events = asyncio.run(collect())
    candidates = db.query(CatalogingCandidate).filter_by(chapter_run_id=run.id).all()
    assert all(any(row.id == identity for row in candidates) for identity in preserved_ids)
    assert any(event["type"] == "parse_warning" and "真实角色 id" in event["error"] for event in events)
    assert character.personality is None  # Staging never auto-applies a guessed target.
    if repair:
        assert len(calls) == 3
        assert len(candidates) == 3
        assert run.status == "awaiting_confirmation"
        assert run.error is None
    else:
        assert len(calls) == 4  # One fact request plus the unchanged three-attempt limit.
        assert len(candidates) == 2
        assert run.status == "failed" and job.status == "paused_on_failure"
        assert "建档候选校验未通过" in run.error and "真实角色 id" in run.error
        assert "JSONL" not in run.error


@pytest.mark.parametrize("profile_changed", [False, True], ids=["correct-wrong-manifest", "retain-source-guard"])
def test_resume_supplies_saved_candidates_and_rechecks_a_model_corrected_manifest(
    archive, monkeypatch, profile_changed,
):
    db, chapter, character, job, run = archive
    chapter.content = "主角成为调查员，认真核对旧资料。"
    create_fact(db, job, run, {"fact_type": "character_fact", "payload": {
        "primary_name": character.name, "archive_identity": "stable_character",
        "stable_profile_change": profile_changed, "role_hint": "调查员",
    }}, 0)
    original = summary_payload(characters=[character.name], character_profiles=[character.name])
    original["summary_text"] = (
        "主角仔细核对旧资料，确认档案中的信息与保存的原始记录一致，并将本轮核对过程整理为记录。"
        "本次没有发现需要修改的稳定角色资料，后续仍需继续核验其余记录。"
    )
    for index, raw in enumerate([
        {"type": "chapter_summary", "payload": original},
        {"character_ids": [], "type": "outline_create", "title": chapter.title, "node_type": "chapter", "summary": "核对档案。"},
        {"type": "character_state_update", "id": character.id, "name": character.name, "mental_state": "冷静"},
        {"type": "chapter_link", "characters": [{"name": character.name, "appearance_type": "出场"}]},
    ]):
        assert "candidate" in create_candidate_from_raw(db, job, run, raw, index)
    db.commit()
    saved_ids = {row.id for row in db.query(CatalogingCandidate)}
    calls = []

    async def stream(messages, **kwargs):
        calls.append(messages)
        # Even the first resumed request must describe the durable checkpoint.
        retry = messages[1]["content"]
        assert '"accepted_candidates"' in retry
        assert all(identity in retry for identity in saved_ids)
        assert original["summary_text"] in retry
        assert '"mental_state":"冷静"' in retry
        yield json.dumps({"type": "chapter_summary", "payload": {
            **original, "coverage_manifest_mode": "replace",
            "coverage_manifest": {**original["coverage_manifest"], "character_profiles": []},
        }}, ensure_ascii=False)

    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", stream)

    async def collect():
        return [event async for event in orchestrator._extract_run(db, job, run)]

    asyncio.run(collect())
    assert {row.id for row in db.query(CatalogingCandidate)} == saved_ids
    assert character.background == "调查员，长期负责核对原始记录。"
    assert character.mental_state is None
    assert len(calls) == 1
    assert run.status == "awaiting_confirmation"
    if profile_changed:
        # Existing source-review semantics stay visible; replacement cannot erase the warning.
        assert "角色档案" in run.review_warning
    else:
        assert run.review_warning is None


@pytest.mark.parametrize("line,kind", [
    ("{invalid", "jsonl_parse"),
    ("[]", "jsonl_parse"),
    ('{"type":"character_update","name":"主角","personality":"谨慎"}', "candidate_validation"),
])
def test_json_syntax_and_candidate_validation_are_distinct(archive, line, kind):
    db, _, _, job, run = archive
    result = try_create_candidates(db, job, run, line, 0)[0]
    assert result["error_kind"] == kind
    assert "bad_line" in result
    issue = candidate_issue(result)
    assert issue["message"] == result["error"]
    assert issue["rejected_candidate"] == (line if line == "{invalid" else json.loads(line))
    assert db.query(CatalogingCandidate).count() == 0

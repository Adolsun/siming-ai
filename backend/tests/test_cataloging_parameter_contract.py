"""Model-visible candidate schemas, rejected writes, and same-model repair."""
import asyncio
import json

import pytest

from app.architecture.tool_spec import ToolInputSchemaValidationError
from app.database.models import CatalogingCandidate
from app.mcp.adapter import execute_tool, list_mcp_tools
from app.modules.continuity.domain.candidate_contract import candidate_contract_examples
from app.services.cataloging import orchestrator
from app.services.cataloging.candidate_store import create_candidate_from_raw
from app.services.cataloging.jsonl import normalize_candidate
from app.services.workspace.executor import execute_workspace_action
from app.services.workspace.registry import registry
from tests.test_cataloging_character_targets import archive as archive_fixture
from tests.test_cataloging_candidate_repair import summary_payload

archive = archive_fixture
TOOL = "save_external_cataloging_candidates"


def test_api_and_mcp_export_the_same_non_opaque_candidate_schema():
    spec = registry.get_spec(TOOL)
    parameters = spec.parameters_schema()
    assert spec.openai_schema()["function"]["parameters"] == spec.mcp_schema()["inputSchema"]
    variants = parameters["properties"]["candidates"]["items"]["anyOf"]
    fields = {s["properties"]["type"]["enum"][0]: s["properties"] for s in variants}
    assert fields["character_create"]["role_type"]["enum"] == [
        "protagonist", "supporting", "antagonist", "mentor", "other",
    ]
    assert fields["chapter_link"]["characters"]["items"]["required"] == ["name", "appearance_type"]
    assert fields["character_create"]["client_id"]["type"] == "string"
    for kind in ("outline_create", "outline_update"):
        variant = next(row for row in variants if row["properties"]["type"]["enum"] == [kind])
        assert "character_ids" in variant["required"]
        assert fields[kind]["character_ids"]["items"]["type"] == "string"
        assert "related_characters" not in fields[kind]
    sections = fields["scene_outline_replace"]["sections"]["items"]
    assert "character_ids" in sections["required"]
    for example in candidate_contract_examples():
        spec.validate_input({"job_id": "job", "chapter_id": "chapter", "candidates": [example]})


def test_managed_cli_schema_exposes_its_actual_batch_limit_without_changing_unbound_api(monkeypatch):
    parameters = registry.get_spec(TOOL).parameters_schema()
    monkeypatch.setenv("SIMING_MANAGED_AGENT_KIND", "cataloging")
    monkeypatch.setenv("SIMING_MANAGED_CATALOGING_JOB_ID", "job")
    tool = next(tool for tool in list_mcp_tools(permission_pack="cataloging_worker") if tool.name == TOOL)
    assert tool.input_schema["properties"]["candidates"]["maxItems"] == 3
    assert tool.input_schema["properties"]["candidates"]["items"] == parameters["properties"]["candidates"]["items"]
    assert "maxItems" not in registry.get_spec(TOOL).parameters_schema()["properties"]["candidates"]


def test_mcp_returns_exact_repair_context_then_accepts_corrected_field(archive):
    db, chapter, character, job, run = archive
    run.status = "facts_saved"
    chapter.content = "主角换上红衣，继续核对资料。"
    db.commit()
    candidate = {"type": "character_state_update", "id": character.id, "name": character.name,
                 "appearance": "红衣", "appearance_before": "模型记错的外貌", "appearance_evidence": "主角换上红衣"}

    def invoke():
        result = asyncio.run(execute_tool(db, chapter.project_id, TOOL, {
            "job_id": job.id, "chapter_id": chapter.id, "candidates": [candidate],
        }, permission_pack="cataloging_worker"))
        return json.loads(result.content[0]["text"])

    failure = invoke()
    assert failure["status"] == "skipped"
    repair = failure["data"]["candidate_errors"][0]["repair_context"]
    assert repair["expected_value"] == character.appearance
    assert "accepted_candidates" in failure["data"]["recovery_context"]
    assert db.query(CatalogingCandidate).count() == 0
    candidate["appearance_before"] = repair["expected_value"]
    success = invoke()
    assert success["data"]["candidates_saved"] == 1
    assert json.loads(db.query(CatalogingCandidate).one().raw_payload)["appearance"] == "红衣"
    assert character.appearance == "短发"  # Still staged for author/apply flow.


@pytest.mark.parametrize("field,bad,good,rule", [
    ("role_type", "主角，穿越者", "protagonist", "enum"),
    ("aliases", '["旧称"]', ["旧称"], "type"),
])
@pytest.mark.parametrize("route", ["mcp", "api-tool", "api-jsonl"])
def test_invalid_field_is_not_defaulted_and_corrected_record_is_accepted(archive, field, bad, good, rule, route):
    db, chapter, character, job, run = archive
    run.status = "facts_saved"
    db.commit()
    raw = {"type": "character_update", "id": character.id, "name": character.name,
           "personality": "认真核对证据", field: bad}

    def invoke(record):
        if route == "api-jsonl":
            return create_candidate_from_raw(db, job, run, record, 0)
        arguments = {"job_id": job.id, "chapter_id": chapter.id, "candidates": [record]}
        if route == "api-tool":
            return asyncio.run(execute_workspace_action(db, chapter.project_id, {"tool": TOOL, "arguments": arguments}))
        result = asyncio.run(execute_tool(db, chapter.project_id, TOOL, arguments, permission_pack="cataloging_worker"))
        return json.loads(result.content[0]["text"])

    failure = invoke(raw)
    assert db.query(CatalogingCandidate).count() == 0
    if route == "api-jsonl":
        assert field in failure["error"]
    else:
        assert failure["data"]["path"] in (f"$.candidates[0].{field}", f"$.candidates.0.{field}")
        assert failure["data"]["rule"] == rule
    success = invoke({**raw, field: good})
    candidate = db.query(CatalogingCandidate).one()
    assert json.loads(candidate.raw_payload)[field] == good, success
    assert character.personality is None


def test_nested_link_error_names_actual_field_instead_of_union_failure():
    spec = registry.get_spec(TOOL)
    with pytest.raises(ToolInputSchemaValidationError) as caught:
        spec.validate_input({"job_id": "job", "chapter_id": "chapter", "candidates": [{
            "type": "chapter_link", "characters": [{"name": "角色", "appearance_type": "出场|提及|回忆"}],
        }]})
    assert caught.value.path == ("candidates", "0", "characters", "0", "appearance_type") or caught.value.path == (
        "candidates", 0, "characters", 0, "appearance_type",
    )
    assert caught.value.rule == "enum"


@pytest.mark.parametrize("record", [
    {"name": "角色", "current_location": "大厅"},
    {"type": "new_character", "name": "角色", "background": "调查员"},
    {"type": "revealed_clue", "clue": "线索"},
    {"node_type": "worldbuilding_create", "title": "设定", "dimension": "culture"},
])
def test_api_never_guesses_candidate_type_from_natural_language_or_fields(record):
    with pytest.raises(ValueError, match="标准枚举"):
        normalize_candidate(record)


def test_explicit_chapter_link_is_never_changed_into_a_character_relationship():
    result = normalize_candidate({"type": "chapter_link", "source": "甲", "target": "乙", "relation": "grandfather_of"})
    assert result["item_type"] == "chapter_link"


def test_world_dimension_must_be_model_selected_not_inferred_from_category():
    with pytest.raises(ValueError, match="dimension"):
        normalize_candidate({"type": "worldbuilding_create", "title": "宗门", "category": "宗门", "content": "有独立组织的门派"})


def test_api_gateway_corrects_enum_on_next_request_without_repeating_saved_candidates(archive, monkeypatch):
    db, chapter, character, job, run = archive
    calls = []
    retained_ids = []

    async def stream(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 1:
            yield json.dumps({"fact_type": "chapter_overview", "payload": {"summary": "主角认真核对档案。"}}) + "\n"
            return
        record = {"type": "character_update", "id": character.id, "name": character.name,
                  "personality": "认真核对证据", "role_type": "主角，穿越者"}
        if len(calls) == 2:
            rows = [
                {"type": "chapter_summary", "payload": summary_payload(character_profiles=[character.name])},
                {"character_ids": [], "type": "outline_create", "title": chapter.title, "node_type": "chapter", "summary": "核对档案。"},
                record,
            ]
        else:
            feedback = messages[1]["content"]
            assert "role_type" in feedback and "protagonist" in feedback
            retained_ids[:] = [row.id for row in db.query(CatalogingCandidate)]
            assert all(identity in feedback for identity in retained_ids)
            rows = [{**record, "role_type": "protagonist"}]
        yield "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)

    monkeypatch.setattr(orchestrator.LLMGateway, "stream_chat_completion", stream)

    async def collect():
        return [event async for event in orchestrator._extract_run(db, job, run)]

    asyncio.run(collect())
    assert len(calls) == 3, run.error  # Facts, initial candidates, corrected candidate only.
    assert run.status == "awaiting_confirmation" and run.error is None
    rows = db.query(CatalogingCandidate).all()
    assert len(rows) == 3 and set(retained_ids) <= {row.id for row in rows}
    profile = next(row for row in rows if row.item_type == "character_update")
    assert json.loads(profile.raw_payload)["role_type"] == "protagonist"

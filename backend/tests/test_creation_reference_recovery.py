"""Regression coverage for entity renames and actionable generation references."""
from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from app.database.models import NovelCreationStageRun
from app.services.creation_agent_native_protocol import safe_creation_tool_result
from app.services.novel_creation_actions import delete_creation_entity, patch_creation_entity
from app.services.novel_creation_entities import get_creation_entity, list_creation_entities
from app.services.workspace.executor import execute_workspace_action
from app.services.workspace.registry import registry
from app.services.workspace.tool_result_projection import sanitize_diagnostic_tool_result
from app.services.workspace.tools import novel_creation_v2
from tests.test_novel_creation_workspace_v2 import _db, _ready_session


def test_entity_name_patch_preserves_original_id_and_other_entities():
    with _db() as db:
        session = _ready_session(db)
        entities = list_creation_entities(session, artifact="world_style")
        entity = get_creation_entity(db, entities[0]["id"])
        original_id = entity.id
        revision = session.revision
        others = {row["id"]: deepcopy(row["data"]) for row in entities[1:]}
        result = patch_creation_entity(session, entity, [
            {"action": "set", "path": "/name", "value": "通行九境（作者已确认）"},
        ], expected_revision=revision, source="assistant")
        db.commit()
        db.expire_all()
        assert result["entity"]["id"] == original_id
        assert result["entity"]["status"] == "active"
        assert get_creation_entity(db, original_id).status == "active"
        after = list_creation_entities(session, artifact="world_style")
        assert len(after) == len(entities)
        assert {row["id"]: row["data"] for row in after if row["id"] != original_id} == others
        assert session.revision == revision + 1


@pytest.mark.parametrize("via_executor", [False, True])
def test_deleted_context_entity_returns_a_recoverable_field_error_before_model(monkeypatch, via_executor):
    with _db() as db:
        session = _ready_session(db)
        entity = get_creation_entity(db, list_creation_entities(session, artifact="world_style")[0]["id"])
        delete_creation_entity(session, entity, expected_revision=session.revision)
        db.commit()
        before = deepcopy(session.draft_json)
        revision = session.revision
        before_runs = db.query(NovelCreationStageRun).count()
        model = AsyncMock(side_effect=AssertionError("Invalid reference must not call the provider"))
        monkeypatch.setattr(novel_creation_v2, "_enhance_with_model", model)
        monkeypatch.setattr(novel_creation_v2, "_resolve_creation_model", lambda *a, **k: "deepseek:deepseek-flash")
        args = {"session_id": session.id, "artifact": "characters", "entity_type": "character",
                "expected_revision": revision, "context_artifacts": ["constraints", "concepts", "world_style"],
                "context_entity_ids": [entity.id], "instruction": "生成主角档案"}
        if via_executor:
            result = asyncio.run(execute_workspace_action(db, "", {"tool": "generate_creation_artifact", "arguments": args}))
        else:
            result = asyncio.run(novel_creation_v2.generate_creation_artifact(db, "", args))
        assert result["status"] == "error"
        assert result["data"]["reason"] == "creation_context_entity_unavailable"
        assert result["data"]["path"] == "$.context_entity_ids[0]"
        assert "list_creation_entities" in result["detail"]
        assert safe_creation_tool_result("generate_creation_artifact", result) == result
        model.assert_not_called()
        assert db.query(NovelCreationStageRun).count() == before_runs
        assert session.revision == revision
        assert session.draft_json == before


def test_generation_schema_exposes_exact_entity_type_values():
    schema = registry.get_spec("generate_creation_artifact").parameters_schema()
    entity_schema = schema["properties"]["entity_type"]
    assert "character" in entity_schema["enum"]
    assert "characters" not in entity_schema["enum"]


def test_renamed_entity_can_be_used_as_generation_context(monkeypatch):
    with _db() as db:
        session = _ready_session(db)
        entity = get_creation_entity(db, list_creation_entities(session, artifact="world_style")[0]["id"])
        entity_id = entity.id
        patch_creation_entity(session, entity, [{"action": "set", "path": "/name", "value": "已确认九境"}],
                              expected_revision=session.revision)
        db.commit()
        revision = session.revision
        def model_stream(**kwargs):
            assert "已确认九境" in kwargs["messages"][1]["content"]
            async def generate():
                yield '{"data":{"characters":[{"name":"新主角","role_type":"protagonist","goal":"找到残碑"}],"relationships":[]}}'
            return generate()
        monkeypatch.setattr(novel_creation_v2, "_resolve_creation_model", lambda *a, **k: "openai:test")
        monkeypatch.setattr(novel_creation_v2.LLMGateway, "stream_chat_completion", model_stream)
        result = asyncio.run(execute_workspace_action(db, "", {"tool": "generate_creation_artifact", "arguments": {
            "session_id": session.id, "artifact": "characters", "entity_type": "character",
            "expected_revision": revision, "context_entity_ids": [entity_id], "instruction": "新增主角",
        }}))
        assert result["status"] == "ok", result
        assert session.revision == revision + 1
        assert get_creation_entity(db, entity_id).status == "active"
        assert any(row["name"] == "新主角" for row in session.draft_json["stages"]["characters"]["data"]["characters"])


def test_removing_entity_root_does_not_rebind_the_next_entity():
    with _db() as db:
        session = _ready_session(db)
        rows = list_creation_entities(session, artifact="world_style")
        entity = get_creation_entity(db, rows[0]["id"])
        before_other = deepcopy(rows[1])
        patch_creation_entity(session, entity, [{"action": "remove", "path": "/"}],
                              expected_revision=session.revision)
        assert get_creation_entity(db, entity.id).status == "deleted"
        other = get_creation_entity(db, before_other["id"])
        assert other.status == "active" and other.entity_key == before_other["entity_key"]


def test_reference_diagnostic_never_reflects_raw_exception_or_arguments():
    raw = {"status": "error", "detail": "private-provider-secret", "data": {
        "reason": "creation_context_entity_unavailable", "path": "$.context_entity_ids[0]",
        "exception": "private-database-path", "arguments": {"api_key": "private-key"},
    }}
    result = sanitize_diagnostic_tool_result("generate_creation_artifact", raw)
    assert result["data"] == {"reason": "creation_context_entity_unavailable", "path": "$.context_entity_ids[0]"}
    assert "private-" not in str(result)


def test_rename_collision_is_rejected_atomically():
    with _db() as db:
        session = _ready_session(db)
        rows = list_creation_entities(session, artifact="world_style")
        before = deepcopy(session.draft_json)
        revision = session.revision
        result = asyncio.run(execute_workspace_action(db, "", {"tool": "patch_creation_entity", "arguments": {
            "entity_id": rows[0]["id"], "expected_revision": revision,
            "changes": [{"action": "set", "path": "/name", "value": rows[1]["entity_key"]}],
        }}))
        assert result["data"]["reason"] == "creation_entity_identity_conflict"
        assert session.revision == revision and session.draft_json == before
        assert get_creation_entity(db, rows[0]["id"]).status == "active"

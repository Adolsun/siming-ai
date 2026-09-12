"""Generated factions use the same schema in prompts, validation and receipts."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.database.models import NovelCreationStageRun
from app.modules.creation.domain.generation_contract import (
    CreationGenerationError,
    validate_generated_entity,
)
from app.services.creation_agent_native_protocol import safe_creation_tool_result
from app.services.novel_creation_entities import list_creation_entities
from app.services.workspace.executor import execute_workspace_action
from app.services.workspace.registry import registry
from app.services.workspace.tool_result_projection import model_tool_result_projector
from app.services.workspace.tools import novel_creation_v2
from tests.test_novel_creation_workspace_v2 import _db, _ready_session

FIXTURE = Path(__file__).parents[2] / "contracts/fixtures/creation_entity_generation.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_generated_entity_contract_matches_shared_fixture(case):
    before = deepcopy(case["data"])
    if "error" not in case:
        validate_generated_entity(case["stage"], case["data"], case["target"])
    else:
        with pytest.raises(CreationGenerationError) as caught:
            validate_generated_entity(case["stage"], case["data"], case["target"])
        assert caught.value.reason == case["error"]["reason"]
        assert caught.value.path == case["error"]["path"]
        raw = caught.value.tool_result("generate_creation_artifact")
        public = safe_creation_tool_result("generate_creation_artifact", raw)
        assert public == raw
        projected = model_tool_result_projector.project(
            registry.get("generate_creation_artifact"), public
        )
        assert projected.payload == raw
    assert case["data"] == before


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_faction_generation_repairs_schema_or_preserves_data_with_actionable_error(
    monkeypatch, repair_succeeds
):
    calls = []
    factions = [
        {"title": title, "dimension": "factions", "content": "凡人组成的本地组织。"}
        for title in ("黑市会", "巡夜队", "纸业行", "驿站脚行")
    ]
    malformed = [
        {key: value for key, value in row.items() if key != "dimension"} for row in factions
    ]

    def stream(**kwargs):
        calls.append(kwargs)
        content = kwargs["messages"][1]["content"]
        assert '"required_values": {"dimension": "factions"}' in content
        assert '"field": "entries"' in content
        assert "目标模式：new" in content
        if len(calls) == 2:
            assert "$.data.entries[0].dimension" in content
        rows = factions if len(calls) == 2 and repair_succeeds else malformed

        async def generate():
            yield json.dumps({"data": {"entries": rows, "relations": []}}, ensure_ascii=False)

        return generate()

    monkeypatch.setattr(novel_creation_v2.LLMGateway, "stream_chat_completion", stream)
    with _db() as db:
        session = _ready_session(db)
        old_entities = list_creation_entities(session, artifact="locations")
        db.commit()
        before = deepcopy(session.draft_json["stages"])
        revision = session.revision
        result = asyncio.run(
            execute_workspace_action(
                db,
                "",
                {
                    "tool": "generate_creation_artifact",
                    "arguments": {
                        "session_id": session.id,
                        "artifact": "locations",
                        "entity_type": "faction",
                        "expected_revision": revision,
                        "instruction": "新增四个本地势力，保留已有地点。",
                        "model": "openai:test",
                        "use_model": True,
                    },
                },
            )
        )
        assert len(calls) == 2
        db.refresh(session)
        run = (
            db.query(NovelCreationStageRun)
            .order_by(NovelCreationStageRun.created_at.desc())
            .first()
        )
        if repair_succeeds:
            assert result["status"] == "ok", result
            assert session.revision == revision + 1
            after = list_creation_entities(session, artifact="locations")
            assert len(after) == len(old_entities) + 4
            assert {
                row["id"]: row["data"]
                for row in after
                if row["id"] in {x["id"] for x in old_entities}
            } == {row["id"]: row["data"] for row in old_entities}
            added = [row for row in after if row["entity_key"] in {x["title"] for x in factions}]
            assert len(added) == 4 and all(row["entity_type"] == "faction" for row in added)
        else:
            assert session.revision == revision
            assert session.draft_json["stages"] == before
            assert run.failure_class == "invalid_model_output"
            assert run.result_json["attempt"] == 2
            expected = {
                "reason": "creation_generated_dimension_invalid",
                "path": "$.data.entries[0].dimension",
                "retryable": True,
            }
            assert result["data"] == expected
            public = safe_creation_tool_result("generate_creation_artifact", result)
            assert public["data"] == expected
            wire = model_tool_result_projector.project(
                registry.get("generate_creation_artifact"), public
            )
            assert wire.payload["data"] == expected
            assert "dimension" in wire.payload["detail"] and "factions" in wire.payload["detail"]


def test_generated_diagnostic_does_not_echo_provider_text():
    raw = {
        "status": "error",
        "detail": "PRIVATE_PROVIDER_TEXT",
        "data": {
            "reason": "creation_generated_dimension_invalid",
            "path": "$.data.entries[0].dimension",
            "raw_response": "PRIVATE_MODEL_OUTPUT",
            "api_key": "PRIVATE_KEY",
        },
    }
    public = safe_creation_tool_result("generate_creation_artifact", raw)
    assert public["data"]["path"] == raw["data"]["path"]
    assert "PRIVATE_" not in json.dumps(public)


@pytest.mark.parametrize("entity_scope", [True, False])
def test_first_macro_outline_preserves_model_metadata_and_delivers_saved_receipt(
    monkeypatch, entity_scope
):
    outline = {
        "story_overview": "追索旧城秘密。",
        "core_conflict": "调查者与守密者争夺旧档。",
        "ending_direction": "公开旧档并承担代价。",
        "target_chapters": 240,
        "volumes": [
            {
                "title": f"第{i + 1}卷",
                "start_chapter": i * 48 + 1,
                "end_chapter": (i + 1) * 48,
                "summary": "调查取得新证据。",
            }
            for i in range(5)
        ],
        "stage_plan": [{"stage": "开局", "goal": "取得线索"}],
    }

    def stream(**kwargs):
        async def generate():
            yield json.dumps({"data": outline}, ensure_ascii=False)

        return generate()

    monkeypatch.setattr(novel_creation_v2.LLMGateway, "stream_chat_completion", stream)
    with _db() as db:
        session = _ready_session(db)
        draft = deepcopy(session.draft_json)
        draft["stages"]["macro_outline"] = {"status": "pending", "data": None}
        session.draft_json = draft
        db.commit()
        before = deepcopy(session.draft_json["stages"])
        revision = session.revision
        args = {
            "session_id": session.id,
            "artifact": "macro_outline",
            "expected_revision": revision,
            "model": "openai:test",
            "use_model": True,
            "instruction": "生成首版全书主线和五卷卷纲。",
        }
        if entity_scope:
            args["entity_type"] = "volume"
        result = asyncio.run(
            execute_workspace_action(
                db,
                "",
                {"tool": "generate_creation_artifact", "arguments": args},
            )
        )
        assert result["status"] == "ok", result["detail"]
        db.refresh(session)
        saved = session.draft_json["stages"]["macro_outline"]["data"]
        for field in ("story_overview", "core_conflict", "ending_direction", "stage_plan"):
            assert saved[field] == outline[field]
        assert len(saved["volumes"]) == 5
        assert session.revision == revision + 1
        for stage in ("world_style", "characters", "locations"):
            assert session.draft_json["stages"][stage] == before[stage]
        public = model_tool_result_projector.project(
            registry.get("generate_creation_artifact"),
            result,
        ).payload
        assert public["data"]["saved"] is True
        assert public["data"]["requires_confirmation"] is True
        assert public["data"]["revision"] == revision + 1
        assert public["data"]["artifact"] == "macro_outline"
        assert public["data"]["collection_counts"] == {"volumes": 5}
        assert public["data"]["run_id"]


@pytest.mark.parametrize("existing_target", [True, False])
def test_volume_entity_edit_preserves_existing_stage_metadata(monkeypatch, existing_target):
    with _db() as db:
        session = _ready_session(db)
        original = deepcopy(session.draft_json["stages"]["macro_outline"]["data"])
        entities = list_creation_entities(session, artifact="macro_outline")
        db.commit()
        revision = session.revision
        volume = deepcopy(original["volumes"][0])
        volume["summary"] = "模型修改后的卷摘要。"
        if not existing_target:
            volume["title"] = "新增卷"

        def stream(**kwargs):
            assert "initialize_stage=false" in kwargs["messages"][1]["content"]

            async def generate():
                yield json.dumps({"data": {"volumes": [volume]}}, ensure_ascii=False)

            return generate()

        monkeypatch.setattr(novel_creation_v2.LLMGateway, "stream_chat_completion", stream)
        tool = "refine_creation_artifact" if existing_target else "generate_creation_artifact"
        args = {
            "session_id": session.id,
            "artifact": "macro_outline",
            "expected_revision": revision,
            "model": "openai:test",
            "instruction": "调整卷纲",
        }
        args.update(
            {"entity_id": entities[0]["id"]} if existing_target else {"entity_type": "volume"}
        )
        result = asyncio.run(execute_workspace_action(db, "", {"tool": tool, "arguments": args}))
        assert result["status"] == "ok", result["detail"]
        db.refresh(session)
        saved = session.draft_json["stages"]["macro_outline"]["data"]
        assert {k: v for k, v in saved.items() if k != "volumes"} == {
            k: v for k, v in original.items() if k != "volumes"
        }
        if existing_target:
            assert saved["volumes"] == [volume, *original["volumes"][1:]]
        else:
            assert saved["volumes"] == [*original["volumes"], volume]
        assert session.revision == revision + 1


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_initial_volume_missing_stage_metadata_is_repaired_or_returns_diagnostic(
    monkeypatch, repair_succeeds
):
    calls = []
    volume = {"title": "第一卷", "start_chapter": 1, "end_chapter": 48, "summary": "追查旧案。"}

    def stream(**kwargs):
        calls.append(kwargs)
        prompt = kwargs["messages"][1]["content"]
        assert "initialize_stage=true" in prompt
        if len(calls) == 2:
            assert "$.data.story_overview" in prompt
        data = {"volumes": [volume]}
        if len(calls) == 2 and repair_succeeds:
            data.update(
                story_overview="追查旧案。",
                core_conflict="线索争夺。",
                ending_direction="揭开真相。",
            )

        async def generate():
            yield json.dumps({"data": data}, ensure_ascii=False)

        return generate()

    monkeypatch.setattr(novel_creation_v2.LLMGateway, "stream_chat_completion", stream)
    with _db() as db:
        session = _ready_session(db)
        draft = deepcopy(session.draft_json)
        draft["stages"]["macro_outline"] = {"status": "pending", "data": None}
        session.draft_json = draft
        db.commit()
        revision = session.revision
        result = asyncio.run(
            execute_workspace_action(
                db,
                "",
                {
                    "tool": "generate_creation_artifact",
                    "arguments": {
                        "session_id": session.id,
                        "artifact": "macro_outline",
                        "entity_type": "volume",
                        "expected_revision": revision,
                        "model": "openai:test",
                    },
                },
            )
        )
        assert len(calls) == 2
        db.refresh(session)
        if repair_succeeds:
            assert result["status"] == "ok", result
            assert session.revision == revision + 1
        else:
            assert result["status"] == "error"
            public = model_tool_result_projector.project(
                registry.get("generate_creation_artifact"), result
            ).payload
            assert public["data"]["reason"] == "creation_generated_stage_fields_missing"
            assert public["data"]["path"] == "$.data.story_overview"
            assert session.revision == revision
            assert session.draft_json["stages"]["macro_outline"] == draft["stages"]["macro_outline"]

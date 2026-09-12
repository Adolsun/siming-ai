"""Opening bodies and parents survive generation, author writes and materialization."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.database.models import OutlineNode, Project
from app.modules.creation.domain.generation_contract import CreationGenerationError
from app.modules.creation.domain.opening_outline_contract import (
    normalize_opening_outline,
    validate_opening_outline,
)
from app.services.novel_creation_entities import creation_volume_index
from app.services.novel_creation_workspace import save_stage
from app.services.workspace.tools import novel_creation_v2
from app.services.workspace.tools.novel_creation import finalize_creation_session
from tests.test_novel_creation_workspace_v2 import _db, _ready_session

FIXTURE = json.loads(
    (Path(__file__).parents[2] / "contracts/fixtures/creation_opening_outline.json").read_text(
        encoding="utf-8"
    )
)


@pytest.mark.parametrize("case", FIXTURE["invalid_cases"], ids=lambda case: case["name"])
def test_shared_contract_rejects_empty_bodies_and_invalid_links(case):
    data = deepcopy(FIXTURE["data"])
    data[case["field"]][case["index"]][case["key"]] = case["value"]
    with pytest.raises(CreationGenerationError) as caught:
        validate_opening_outline(data, volume_index=FIXTURE["volume_index"])
    assert caught.value.reason == case["reason"]
    assert caught.value.path == f"$.data.{case['field']}[{case['index']}].{case['key']}"


def _opening_for_session(session):
    macro = deepcopy(session.draft_json["stages"]["macro_outline"]["data"])
    macro["volumes"] = [{key: value for key, value in row.items() if key != "id"}
                        for row in FIXTURE["volume_index"]]
    save_stage(session, "macro_outline", macro, confirm=True)
    ids = creation_volume_index(session)
    data = deepcopy(FIXTURE["data"])
    mapping = {source["id"]: target["id"] for source, target in zip(FIXTURE["volume_index"], ids)}
    for chapter in data["chapters"]:
        chapter["volume_id"] = mapping[chapter["volume_id"]]
    return data


def test_materialization_preserves_bodies_metadata_and_ids_after_volumes_reorder():
    with _db() as db:
        session = _ready_session(db)
        opening = _opening_for_session(session)
        macro = deepcopy(session.draft_json["stages"]["macro_outline"]["data"])
        macro["volumes"].reverse()
        save_stage(session, "macro_outline", macro, confirm=True)
        save_stage(session, "opening_outline", opening, confirm=True)
        db.commit()
        result = asyncio.run(finalize_creation_session(db, "", {"session_id": session.id}))
        assert result["status"] == "ok", result
        nodes = db.query(OutlineNode).filter_by(project_id=result["data"]["project_id"]).all()
        volumes = {row.title: row.id for row in nodes if row.node_type == "volume"}
        chapters = sorted((row for row in nodes if row.node_type == "chapter"), key=lambda row: row.sort_order)
        assert [row.parent_id for row in chapters] == [volumes["卷一"], volumes["卷一"], volumes["卷二"]]
        scenes = [row for row in nodes if row.node_type == "section"]
        assert len(scenes) == 9
        assert all(row.summary and row.planned_summary == row.summary for row in chapters + scenes)
        for row, source in zip(chapters, opening["chapters"]):
            assert row.summary == source["summary"]
            assert row.metadata_json["key_events"] == source["key_events"]
            assert row.metadata_json["chapter_hook"] == source["chapter_hook"]
            assert sum(scene.parent_id == row.id for scene in scenes) == 3


@pytest.mark.parametrize("field", ["summary", "volume_id"])
def test_invalid_save_and_existing_invalid_confirmation_do_not_write(field):
    with _db() as db:
        session = _ready_session(db)
        data = deepcopy(session.draft_json["stages"]["opening_outline"]["data"])
        before = deepcopy(session.draft_json)
        revision = session.revision
        data["chapters"][0][field] = ""
        with pytest.raises(CreationGenerationError):
            save_stage(session, "opening_outline", data, confirm=True)
        assert session.draft_json == before
        assert session.revision == revision
        # Simulate a confirmed snapshot saved by an older app, then try confirmation/finalization.
        before["stages"]["opening_outline"]["data"] = data
        session.draft_json = before
        db.commit()
        confirmation = asyncio.run(novel_creation_v2.save_creation_artifact(db, "", {
            "session_id": session.id, "stage": "opening_outline", "data": data, "confirm": True,
        }))
        assert confirmation["status"] == "error"
        result = asyncio.run(finalize_creation_session(db, "", {"session_id": session.id}))
        assert result["status"] == "error"
        assert result["data"]["path"] == f"$.data.chapters[0].{field}"
        assert db.query(Project).count() == 0
        assert db.query(OutlineNode).count() == 0
        assert session.revision == revision


@pytest.mark.parametrize("repair_succeeds", [True, False])
def test_model_repairs_body_and_explicit_volume_reference_or_writes_nothing(monkeypatch, repair_succeeds):
    with _db() as db:
        session = _ready_session(db)
        valid = _opening_for_session(session)
        db.commit()
        invalid = deepcopy(valid)
        invalid["chapters"][0]["summary"] = ""
        invalid["chapters"][0].pop("volume_id")
        before = deepcopy(session.draft_json)
        revision = session.revision
        calls = []

        def stream(**kwargs):
            calls.append(kwargs)
            prompt = kwargs["messages"][1]["content"]
            assert "volume_index" in prompt
            assert valid["chapters"][0]["volume_id"] in prompt
            data = valid if len(calls) == 2 and repair_succeeds else invalid

            async def generate():
                yield json.dumps({"data": data}, ensure_ascii=False)

            return generate()

        monkeypatch.setattr(novel_creation_v2.LLMGateway, "stream_chat_completion", stream)
        result = asyncio.run(novel_creation_v2.run_creation_artifact_generation(db, "", {
            "session_id": session.id, "stage": "opening_outline", "model": "openai:test",
            "use_model": True,
        }))
        assert len(calls) == 2
        if repair_succeeds:
            assert result["status"] == "ok", result
            assert session.draft_json["stages"]["opening_outline"]["data"] == normalize_opening_outline(valid)
            assert session.revision == revision + 1
        else:
            assert result["status"] == "error"
            assert session.draft_json == before
            assert session.revision == revision


def test_single_entity_generation_still_validates_parent_against_owned_volume_index():
    data = {"chapters": [deepcopy(FIXTURE["data"]["chapters"][0])]}
    validate_opening_outline(data, volume_index=FIXTURE["volume_index"], partial=True)
    with pytest.raises(CreationGenerationError, match="volume_id"):
        validate_opening_outline(data, volume_index=[], partial=True)

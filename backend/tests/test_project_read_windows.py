"""Regressions for real-project read results that exceeded the old 16 KiB gate."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database.models import Base, Chapter, OutlineNode, Project
from app.modules.story.domain.project_read_contract import creation_document_page, project_info_page
from app.services.workspace.assistant_public_projection import public_step_payload, public_tool_log
from app.services.workspace.native_tool_batch import validate_workspace_native_tool_batch
from app.services.workspace.registry import registry
from app.services.workspace.tool_result_projection import (
    ToolResultBatchOverCapacity,
    admit_native_assistant_transaction,
    model_tool_result_projector,
)
from app.services.workspace.tools.projects import get_project_creation_brief, get_project_info
from app.services.workspace.tools.search import search_chapters, search_outline
from tests.tool_budget_helpers import request_budget


@pytest.mark.parametrize("character", ["汉", "𠮷", "\x01"])
def test_real_handlers_bound_long_overview_and_read_every_setting_character(character):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    text = character * 5201
    with Session(engine) as db:
        project = Project(
            id=str(uuid4()),
            title=character * 200,
            description=text,
            custom_style_prompt=text,
            rhetoric_guidelines=text,
            forbidden_sentence_patterns=text,
            tags=text,
        )
        db.add(project)
        db.commit()
        with patch(
            "app.services.workspace.tools.projects.get_project_creation_context"
        ) as creation:
            raw = asyncio.run(get_project_info(db, project.id, {}))
            creation.assert_not_called()
        projected = model_tool_result_projector.project(registry.get("get_project_info"), raw)
        assert projected.payload["data"]["id"] == project.id
        assert projected.payload["data"]["title"] == project.title
        assert "creation" not in projected.payload["data"]
        assert projected.payload["field_ranges"]["description"]["has_more"]
        args = projected.payload["field_ranges"]["description"]["read_arguments"]
        pages = []
        while True:
            raw = asyncio.run(get_project_info(db, project.id, args))
            page = model_tool_result_projector.project(
                registry.get("get_project_info"), raw, arguments=args
            ).payload
            pages.append(page["data"]["description"])
            window = page["field_ranges"]["description"]
            if not window["has_more"]:
                break
            args = window["next_arguments"]
            assert args["project_id"] == project.id
        assert "".join(pages) == text
        assert len(pages) == 3
        assert db.get(Project, project.id).description == text
    engine.dispose()


def test_creation_brief_is_complete_paged_json_and_pointer_can_read_a_single_value():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    document = {
        "constraints": {"target_chapters": 41, "brief": "真实长立项资料𠮷\n" * 4000},
        "creative_direction": {"title": "test"},
    }
    with Session(engine) as db:
        project = Project(id=str(uuid4()), title="Read-only project")
        db.add(project)
        db.commit()
        args, pages, hashes = {}, [], set()
        with (
            patch(
                "app.services.workspace.tools.projects.get_project_creation_context",
                return_value=document,
            ),
            patch(
                "app.services.workspace.tools.projects.resolve_project_creation_session",
                return_value=SimpleNamespace(id="session-fixture"),
            ),
        ):
            while True:
                raw = asyncio.run(get_project_creation_brief(db, project.id, args))
                page = model_tool_result_projector.project(
                    registry.get("get_project_creation_brief"), raw, arguments=args
                ).payload["data"]
                pages.append(page["content"])
                hashes.add(page["sha256"])
                if not page["content_range"]["has_more"]:
                    break
                args = page["next_arguments"]
                assert args["project_id"] == project.id
            single = asyncio.run(
                get_project_creation_brief(db, project.id, {"path": "/constraints/target_chapters"})
            )
            assert json.loads(single["data"]["content"]) == 41
        assert json.loads("".join(pages)) == document
        assert len(hashes) == 1
    engine.dispose()


@pytest.mark.parametrize("path", ["/items/-1", "/items/01", "/a~2b", "constraints", "/missing"])
def test_creation_pointer_rejects_invalid_or_missing_targets(path):
    with pytest.raises(ValueError):
        creation_document_page({"items": [1, 2], "a~2b": 3}, {"path": path})


def test_larger_outline_text_pages_are_schema_valid_and_charge_their_declared_size():
    tool = registry.get("search_outline")
    for chars in (150, 200, 500, 1000, 20000):
        calls = [
            {
                "id": "outline-call",
                "type": "function",
                "function": {
                    "name": tool.name,
                    "arguments": json.dumps({"limit": 1, "summary_chars": chars}),
                },
            }
        ]
        validated = validate_workspace_native_tool_batch(
            calls,
            allowed_tool_names={tool.name},
            resolve_tool=registry.get,
            require_initial_controller=False,
        )
        assert len(validated.calls) == 1
        assert tool.model_result_contract.bytes_for_arguments(
            {"limit": 1, "summary_chars": chars}
        ) >= 24 * min(chars, 1000)
    assert tool.model_result_contract.bytes_for_arguments(
        {"limit": 1, "summary_chars": 200}
    ) < tool.model_result_contract.bytes_for_arguments({"limit": 1, "summary_chars": 1000})


def test_delivery_failure_is_publicly_specific_without_losing_execution_receipt():
    raw = {
        "tool": "get_project_info",
        "status": "ok",
        "data": {"private": "private source"},
        "model_delivery": {
            "tool": "get_project_info",
            "status": "error",
            "data": {
                "reason": "tool_result_over_capacity",
                "actual_bytes": 37131,
                "max_bytes": 16384,
            },
        },
    }
    public = public_tool_log(raw)
    assert public["status"] == "error" and public["execution_status"] == "ok"
    assert "37131" in public["detail"] and "16384" in public["detail"]
    assert public_tool_log(public) == public
    step = SimpleNamespace(
        id="step-1",
        run_id="run-1",
        tool="get_project_info",
        status="ok",
        step_type="search",
        iteration=1,
        request_json="{}",
        result_json=json.dumps(raw),
        attempt_no=1,
        retry_of_step_id=None,
        resolved_step_id=None,
        output_refs=None,
        started_at=None,
        completed_at=None,
    )
    view = public_step_payload(step, can_retry=True, retry_block_reason=None)
    assert view["status"] == "error" and view["execution_status"] == "ok" and not view["can_retry"]
    assert "private source" not in json.dumps(view)
    assert raw["data"]["private"] == "private source"


def test_project_read_windows_share_a_stable_unicode_and_budget_contract():
    page = project_info_page(
        {"id": "project-1", "description": "𠮷" * 2111},
        {"field": "description", "offset_chars": 2000},
    )
    assert len(page["data"]["description"]) == 111
    assert page["field_ranges"]["description"]["total_chars"] == 2111


@pytest.mark.parametrize("length", [10_000, 20_000, 50_000])
@pytest.mark.parametrize("character", ["文", "𠮷", "\x01"])
def test_long_chapters_and_outlines_read_completely_in_stable_id_windows(length, character):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    text = character * length
    with Session(engine) as db:
        project = Project(id="long-project", title="长正文")
        foreign = Project(id="other-project", title="其他作品")
        outline = OutlineNode(
            id="long-outline",
            project_id=project.id,
            node_type="chapter",
            title="同名大纲",
            summary=text,
            planned_summary=text,
            actual_summary=text,
        )
        chapter = Chapter(
            id="long-chapter",
            project_id=project.id,
            outline_node_id=outline.id,
            title="同名章节",
            content=text,
            word_count=length,
        )
        db.add_all([project, foreign, outline, chapter])
        db.commit()
        # A request for the whole chapter is accepted and served as safe pages.
        args, pages = {"chapter_id": chapter.id, "content_chars": length, "limit": 1}, []
        calls = [
            {
                "id": "long-read",
                "type": "function",
                "function": {"name": "search_chapters", "arguments": json.dumps(args)},
            }
        ]
        validate_workspace_native_tool_batch(
            calls,
            allowed_tool_names={"search_chapters"},
            resolve_tool=registry.get,
            require_initial_controller=False,
        )
        while True:
            raw = asyncio.run(search_chapters(db, project.id, args))
            page = model_tool_result_projector.project(
                registry.get("search_chapters"), raw, arguments=args
            ).payload["data"][0]
            assert page["id"] == chapter.id
            pages.append(page["content"])
            if not page["content_range"]["has_more"]:
                break
            # Changing result order or a duplicate title cannot redirect the next window.
            if len(pages) == 1:
                db.add(
                    Chapter(
                        id="duplicate",
                        project_id=project.id,
                        title=chapter.title,
                        content="其他正文",
                    )
                )
                db.commit()
            args = page["next_arguments"]
        assert "".join(pages) == text
        assert len(pages) == (length + 3999) // 4000
        assert (
            asyncio.run(search_chapters(db, foreign.id, {"chapter_id": chapter.id}))["data"] == []
        )
        args = {"node_id": outline.id, "limit": 1, "summary_chars": length}
        summaries = {name: [] for name in ("summary", "planned_summary", "actual_summary")}
        for offset in range(0, length, 1000):
            args["summary_offset_chars"] = offset
            raw = asyncio.run(search_outline(db, project.id, args))
            page = model_tool_result_projector.project(
                registry.get("search_outline"), raw, arguments=args
            ).payload["data"][0]
            for name in summaries:
                summaries[name].append(page[name])
        assert all("".join(values) == text for values in summaries.values())
        assert db.get(Chapter, chapter.id).content == text
    engine.dispose()


def test_native_read_admission_never_spends_output_or_safety_reserves(caplog):
    tool = registry.get("search_chapters")
    payload = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "read-long",
                "type": "function",
                "function": {
                    "name": tool.name,
                    "arguments": json.dumps(
                        {"chapter_id": "long-chapter", "limit": 1, "content_chars": 4000}
                    ),
                },
            }
        ],
    }
    with caplog.at_level("INFO"):
        required = admit_native_assistant_transaction(
            payload, [tool], request_budget=request_budget()
        )
    exact = request_budget(required)
    assert exact.context_window_tokens - exact.current_input_tokens - required == 4512
    assert exact.output_reserve_tokens == 4000 and exact.safety_margin_tokens == 512
    assert admit_native_assistant_transaction(payload, [tool], request_budget=exact) == required
    with pytest.raises(ToolResultBatchOverCapacity) as blocked:
        admit_native_assistant_transaction(
            payload, [tool], request_budget=request_budget(required - 1)
        )
    assert blocked.value.available_tokens == required - 1
    assert "output_reserved=4000 safety_margin=512" in caplog.text


def test_visible_reasoning_handles_done_only_replacements_and_multiple_iterations():
    from app.services.workspace.assistant_native_turn import NativeStepCapture, WorkspaceNativeTurn
    from app.services.workspace.assistant_turn_state import WorkspaceAssistantTurnState

    state = WorkspaceAssistantTurnState(
        db=None,
        project_id="project-1",
        payload=None,
        selected_provider="test",
        supports_function_calling=True,
        local_cli_selected=False,
        local_cli_mcp_enabled=False,
        encode_event=json.dumps,
        execute_action=None,
        prepare_context=None,
        turn_telemetry=MagicMock(),
    )
    executor = WorkspaceNativeTurn(state, None, registry)
    first = NativeStepCapture()
    events = executor._capture_chunk(first, {"type": "reasoning_delta", "delta": "先读取"}, 1)
    events += executor._capture_done(
        first, {"reasoning_content": "已读取", "provider_state": [{"opaque": "PRIVATE"}]}, 1
    )
    second = NativeStepCapture()
    events += executor._capture_done(second, {"reasoning_content": "再核对"}, 2)
    assert executor._capture_done(second, {"reasoning_content": "再核对"}, 2) == []
    assert executor._capture_done(second, {"reasoning_content": ""}, 2) == []
    assert second.reasoning == "再核对"
    rendered = ""
    for event in events:
        data = json.loads(event)
        rendered = data["delta"] if data["replace"] else rendered + data["delta"]
    assert rendered == state.visible_reasoning == "已读取\n\n再核对"
    assert "PRIVATE" not in "".join(events)
    assert first.provider_state == [{"opaque": "PRIVATE"}]

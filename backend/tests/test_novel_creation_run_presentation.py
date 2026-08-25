from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.database.models import NovelCreationStageRun
from app.services.novel_creation_run_presentation import (
    build_run_presentation_evidence,
    judge_run_card_presentation,
    present_serialized_run,
)
from app.services.novel_creation_workspace import save_stage
from tests.test_novel_creation_workspace_v2 import _db, _ready_session


def _failed_character_run(db, session):
    run = NovelCreationStageRun(
        session_id=session.id,
        stage="characters",
        operation="refine",
        status="failed",
        model_source="deepseek:test",
        current_message="请先选择一个创意方向",
        failure_class="validation",
        input_revision=int(session.revision or 0),
        request_json={"instruction": "补充人物关系"},
    )
    db.add(run)
    db.flush()
    return run


def test_presentation_evidence_exposes_saved_artifact_without_full_content():
    db = _db()
    session = _ready_session(db)
    run = _failed_character_run(db, session)
    save_stage(
        session,
        "characters",
        {
            "characters": [{"name": "沈砚舟", "role_type": "protagonist"}],
            "relationships": [{"character_a": "沈砚舟", "character_b": "顾沉霜", "relationship_type": "宿敌"}],
        },
        source="assistant",
        change_type="refine",
        run_id=run.id,
    )
    db.commit()
    db.refresh(run)

    evidence = build_run_presentation_evidence(run, assistant_reply="关系已经写入")

    assert evidence["run"]["status"] == "failed"
    assert evidence["artifact"]["status"] == "generated"
    assert evidence["artifact"]["run_linked_version"]["revision"] == session.revision
    assert "characters" not in evidence["artifact"]


def test_api_model_can_present_failed_run_as_waiting_for_review():
    db = _db()
    session = _ready_session(db)
    run = _failed_character_run(db, session)
    completion = AsyncMock(return_value={"content": json.dumps({
        "status": "waiting_user",
        "label": "等待确认",
        "message": "角色关系已经写入作品资料，当前等待你确认；旧的前置条件报错已保留在运行日志中。",
        "show_retry": False,
        "reason": "目标资料存在本轮写入版本",
    }, ensure_ascii=False)})

    with patch(
        "app.services.novel_creation_run_presentation.LLMGateway.chat_completion",
        new=completion,
    ), patch(
        "app.services.novel_creation_run_presentation.LLMGateway.local_cli_extra_body",
        return_value=None,
    ), patch(
        "app.services.novel_creation_run_presentation.LLMGateway.model_identity",
        return_value=("deepseek", "test"),
    ):
        result = asyncio.run(judge_run_card_presentation(
            db,
            run=run,
            model="deepseek:test",
            assistant_reply="已写入四条关系",
        ))

    assert result["status"] == "waiting_user"
    assert result["judged_by"] == "model"
    assert result["show_retry"] is False
    assert result["route"] == "api"
    request = completion.call_args.kwargs
    assert request["model"] == "deepseek:test"
    assert request["extra_body"] is None


def test_local_cli_model_uses_isolated_text_only_adjudication():
    db = _db()
    session = _ready_session(db)
    run = _failed_character_run(db, session)
    completion = AsyncMock(return_value={"content": json.dumps({
        "status": "partial_success",
        "label": "部分完成",
        "message": "关系内容已保存，但前置创意方向仍需补齐。",
        "show_retry": True,
        "reason": "存在写入证据，同时保留一个未完成条件",
    }, ensure_ascii=False)})
    cli_body = {
        "moshu_task_type": "planning",
        "local_cli_isolated": True,
        "local_cli_allow_mcp": False,
        "local_cli_timeout_seconds": 180,
    }

    with patch(
        "app.services.novel_creation_run_presentation.LLMGateway.local_cli_extra_body",
        return_value=cli_body,
    ) as extra_body, patch(
        "app.services.novel_creation_run_presentation.LLMGateway.chat_completion",
        new=completion,
    ), patch(
        "app.services.novel_creation_run_presentation.LLMGateway.model_identity",
        return_value=("opencode_cli", "deepseek-v4-flash"),
    ):
        result = asyncio.run(judge_run_card_presentation(
            db,
            run=run,
            model="opencode_cli:deepseek-v4-flash",
        ))

    assert result["status"] == "partial_success"
    assert result["judged_by"] == "model"
    assert result["route"] == "cli"
    extra_body.assert_called_once()
    assert completion.call_args.kwargs["extra_body"]["local_cli_isolated"] is True
    assert completion.call_args.kwargs["extra_body"]["local_cli_allow_mcp"] is False


def test_adjudication_failure_preserves_raw_failed_status():
    db = _db()
    session = _ready_session(db)
    run = _failed_character_run(db, session)

    with patch(
        "app.services.novel_creation_run_presentation.LLMGateway.local_cli_extra_body",
        return_value=None,
    ), patch(
        "app.services.novel_creation_run_presentation.LLMGateway.chat_completion",
        new=AsyncMock(side_effect=RuntimeError("provider unavailable")),
    ):
        result = asyncio.run(judge_run_card_presentation(
            db,
            run=run,
            model="deepseek:test",
        ))

    assert result["status"] == "failed"
    assert result["judged_by"] == "fallback"
    assert "provider unavailable" in result["reason"]


def test_stored_model_presentation_is_reused_without_another_call():
    db = _db()
    session = _ready_session(db)
    run = _failed_character_run(db, session)
    run.result_json = {
        "card_presentation": {
            "status": "waiting_user",
            "label": "等待确认",
            "message": "已写入，等待确认。",
            "show_retry": False,
            "judged_by": "model",
            "model": "deepseek:test",
            "raw_status": "failed",
        },
    }
    db.commit()
    completion = AsyncMock()

    with patch(
        "app.services.novel_creation_run_presentation.LLMGateway.chat_completion",
        new=completion,
    ):
        result = asyncio.run(present_serialized_run(db, run=run, model="deepseek:test"))

    assert result["status"] == "failed"
    assert result["card_presentation"]["status"] == "waiting_user"
    completion.assert_not_awaited()


def test_stored_presentation_is_ignored_after_raw_status_changes():
    db = _db()
    session = _ready_session(db)
    run = _failed_character_run(db, session)
    run.status = "completed"
    run.result_json = {
        "card_presentation": {
            "status": "waiting_user",
            "label": "等待确认",
            "message": "旧结论",
            "show_retry": False,
            "judged_by": "model",
            "raw_status": "failed",
            "model": "deepseek:test",
        },
    }
    db.commit()
    completion = AsyncMock(return_value={"content": json.dumps({
        "status": "completed",
        "label": "已完成",
        "message": "阶段内容已经确认。",
        "show_retry": False,
        "reason": "底层状态已变为 completed",
    }, ensure_ascii=False)})

    with patch(
        "app.services.novel_creation_run_presentation.LLMGateway.local_cli_extra_body",
        return_value=None,
    ), patch(
        "app.services.novel_creation_run_presentation.LLMGateway.chat_completion",
        new=completion,
    ), patch(
        "app.services.novel_creation_run_presentation.LLMGateway.model_identity",
        return_value=("deepseek", "test"),
    ):
        result = asyncio.run(present_serialized_run(
            db,
            run=run,
            model="deepseek:test",
        ))

    assert result["card_presentation"]["status"] == "completed"
    completion.assert_awaited_once()

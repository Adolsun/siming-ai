"""Regression tests for lightweight concepts and staged new-book creation."""
from __future__ import annotations

import asyncio
import json
import pytest
from copy import deepcopy
from fastapi import HTTPException
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.models import NovelCreationSession, NovelCreationStageRun, OperationRun
from app.database.session import Base
from app.routers.novel_creation import (
    NovelCreationSessionPatchRequest,
    NovelCreationStageRunRequest,
    start_creation_stage_run,
    update_creation_session,
)
from app.services.novel_creation_workspace import (
    STAGE_ORDER,
    build_apply_blueprint,
    create_run as create_stage_run,
    derive_stage,
    initialize_session_draft,
    patch_session,
    save_compact_concepts,
    save_stage,
)
from app.services.workspace.tools.novel_creation import advance_novel_creation_interview, apply_novel_blueprint
from app.services.workspace.tools.novel_creation_v2 import (
    AuthorLockViolation,
    _validate_author_requirements,
    generate_novel_creation_stage,
)
from app.services.novel_creation_interview import INTERVIEW_CLI_TIMEOUT_SECONDS
from app.services.operation_runtime import input_snapshot_hash


def _streaming_completion(*results):
    queue = list(results)

    def create_stream(**_kwargs):
        result = queue.pop(0)

        async def generate():
            if isinstance(result, BaseException):
                raise result
            yield str(result.get("content") or "") if isinstance(result, dict) else str(result)

        return generate()

    return MagicMock(side_effect=create_stream)


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _session(db):
    session = NovelCreationSession(
        mode="internal_llm",
        status="drafting",
        user_brief="A thriller that shocks readers with a devastating reversal.",
        genre="suspense",
    )
    db.add(session)
    initialize_session_draft(session, {"preset_id": "suspense", "target_chapters": 240})
    db.commit()
    return session


def _concepts():
    return [
        {
            "title": f"Concept {index}",
            "subtitle": "High-concept suspense",
            "logline": f"A witness follows clue {index} and discovers the case has rewritten their past.",
            "protagonist_seed": {
                "name": f"Lead {index}",
                "identity": "Forensic archivist",
                "goal": "Expose the hidden trial",
                "lack": "Cannot trust their own memories",
            },
            "world_hook": "Every verified memory can be sold, but each sale changes the buyer's future.",
            "core_conflict": "The closer the lead gets to the truth, the less evidence they can trust.",
            "story_engine": "Each recovered record opens a clue and erases one reliable relationship.",
            "opening_hook": "The victim's final recording is spoken in the lead's own voice.",
            "differentiators": ["Memory evidence", f"Reversal route {index}"],
            "risks": ["Keep the memory rules observable"],
        }
        for index in range(1, 4)
    ]


def test_interview_ready_state_never_calls_full_blueprint_generation():
    db = _db()
    session = _session(db)
    with patch(
        "app.services.workspace.tools.novel_creation._evaluate_answers",
        new=AsyncMock(return_value={"action": "generate", "reason": "enough context"}),
    ):
        result = asyncio.run(advance_novel_creation_interview(db, "", {
            "session_id": session.id,
            "user_brief": session.user_brief,
            "qa_history": [{"question": "What should shock readers?", "answer": "A devastating reversal."}],
            "model": "openai:test",
        }))

    assert result["status"] == "ok"
    assert result["data"]["state"] == "ready"
    assert session.blueprint_json is None
    assert session.draft_json["interview"]["status"] == "completed"


def test_skip_interview_preserves_history_without_model_call():
    db = _db()
    session = _session(db)
    with patch("app.services.workspace.tools.novel_creation._evaluate_answers", new=AsyncMock()) as evaluate:
        result = asyncio.run(advance_novel_creation_interview(db, "", {
            "session_id": session.id,
            "qa_history": [{"question": "What should shock readers?", "answer": "A devastating reversal."}],
            "skip_questions": True,
        }))

    assert result["data"]["state"] == "ready"
    assert result["data"]["skipped"] is True
    assert session.draft_json["interview"]["history"]
    evaluate.assert_not_awaited()


def test_interview_runtime_reports_the_selected_model_and_cli_timeout():
    db = _db()
    session = _session(db)
    selection = SimpleNamespace(
        model="codex_cli:codex-cli",
        provider="codex_cli",
        source="explicit",
    )
    with patch(
        "app.services.workspace.tools.novel_creation._run_dynamic_interview",
        new=AsyncMock(return_value=(None, "", False)),
    ), patch(
        "app.services.workspace.tools.novel_creation.LLMGateway.select_model_for_task",
        return_value=selection,
    ), patch(
        "app.services.workspace.tools.novel_creation.is_local_cli_provider",
        return_value=True,
    ):
        result = asyncio.run(advance_novel_creation_interview(db, "", {
            "session_id": session.id,
            "model": "codex_cli:codex-cli",
        }))

    runtime = result["data"]["runtime"]
    assert result["status"] == "ok"
    assert runtime == {
        "effective_model": "codex_cli:codex-cli",
        "provider": "codex_cli",
        "model_source": "conversation_override",
        "tool_mode": "local_cli_text_json",
        "timeout_seconds": INTERVIEW_CLI_TIMEOUT_SECONDS,
        "quota_status": "unknown",
    }


def test_interview_runtime_marks_quota_failure_without_losing_recovery_guidance():
    db = _db()
    session = _session(db)
    selection = SimpleNamespace(
        model="opencode_cli:free-model",
        provider="opencode_cli",
        source="explicit",
    )
    failed_interview = {
        "status": "interview_failed",
        "detail": "Free usage exceeded, retrying in 9h",
        "data": {
            "failure_class": "quota_or_rate_limit",
            "next_action": "切换有额度的模型后重试。",
        },
    }
    with patch(
        "app.services.workspace.tools.novel_creation._run_dynamic_interview",
        new=AsyncMock(return_value=(failed_interview, "", False)),
    ), patch(
        "app.services.workspace.tools.novel_creation.LLMGateway.select_model_for_task",
        return_value=selection,
    ), patch(
        "app.services.workspace.tools.novel_creation.is_local_cli_provider",
        return_value=True,
    ):
        result = asyncio.run(advance_novel_creation_interview(db, "", {
            "session_id": session.id,
            "model": "opencode_cli:free-model",
        }))

    runtime = result["data"]["runtime"]
    assert result["status"] == "error"
    assert runtime["effective_model"] == "opencode_cli:free-model"
    assert runtime["failure_class"] == "quota_or_rate_limit"
    assert runtime["quota_status"] == "exhausted_or_limited"
    assert runtime["next_action"] == "切换有额度的模型后重试。"


def test_compact_concept_run_limits_output_and_keeps_legacy_blueprints_empty():
    db = _db()
    session = _session(db)
    content = json.dumps({"concepts": _concepts()})
    completion = _streaming_completion({"content": content})
    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=completion,
    ):
        result = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
        }))

    assert result["status"] == "ok"
    assert completion.call_args.kwargs["max_tokens"] == 3200
    assert completion.call_args.kwargs["retry"] == 0
    assert session.blueprint_json is None
    assert len(session.draft_json["concepts"]) == 3
    assert len(session.draft_json["concept_seeds"]) == 3
    assert result["data"]["run"]["status"] == "waiting_author"


def test_compact_concepts_never_switch_models_on_quota_failure():
    db = _db()
    session = _session(db)
    content = json.dumps({"concepts": _concepts()})
    completion = _streaming_completion(RuntimeError("free usage quota exceeded"))
    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=completion,
    ):
        result = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "opencode_cli:opencode/first-free",
            "use_model": True,
        }))

    assert result["status"] == "error"
    assert [item.kwargs["model"] for item in completion.call_args_list] == [
        "opencode_cli:opencode/first-free",
    ]
    assert not any(event["event_type"] == "model_fallback" for event in result["data"]["run"]["events"])


def test_invalid_concepts_create_safe_draft_then_a_retry_can_succeed():
    db = _db()
    session = _session(db)
    invalid = json.dumps({"concepts": _concepts()[:2]})
    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=_streaming_completion({"content": invalid}),
    ):
        recovered = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
        }))
    assert recovered["status"] == "ok"
    assert recovered["data"]["run"]["status"] == "waiting_author"
    assert recovered["data"]["run"]["result_mode"] == "deterministic_fallback"
    assert session.draft_json["stages"]["concepts"]["source"] == "contract_fallback"

    valid = json.dumps({"concepts": _concepts()})
    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=_streaming_completion({"content": valid}),
    ):
        retried = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
        }))
    assert retried["status"] == "ok"
    assert retried["data"]["run"]["id"] != recovered["data"]["run"]["id"]


def test_author_led_session_keeps_source_text_and_generates_one_author_plan():
    db = _db()
    session = NovelCreationSession(mode="internal_llm", status="drafting", user_brief="周遥调查公共温室的花色异常。")
    db.add(session)
    initialize_session_draft(session, {
        "creation_mode": "author_led",
        "author_brief": "周遥发现公共温室里的蓝花一夜变白。",
        "author_outline": "全书六卷，最终公开被调换的土壤试剂检测报告。",
        "locked_requirements": ["周遥必须是植物学实习生", "全书必须六卷"],
        "preset_id": "suspense",
    })
    db.commit()
    author_plan = deepcopy(_concepts()[0])
    author_plan["title"] = "温室异色记录"
    author_plan["protagonist_seed"]["name"] = "周遥"
    author_plan["protagonist_seed"]["identity"] = "植物学实习生"
    completion = _streaming_completion({"content": json.dumps({"concepts": [author_plan]}, ensure_ascii=False)})

    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=completion,
    ):
        result = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
        }))

    assert result["status"] == "ok"
    assert session.schema_version == 3
    assert session.draft_json["creation_mode"] == "author_led"
    assert session.draft_json["author_outline"].startswith("全书六卷")
    assert len(session.draft_json["concepts"]) == 1
    prompt = completion.call_args.kwargs["messages"][-1]["content"]
    assert "周遥必须是植物学实习生" in prompt
    assert "全书必须六卷" in prompt


def test_partial_stream_retries_same_model_once_before_persisting():
    db = _db()
    session = _session(db)
    completion = _streaming_completion(
        RuntimeError("peer closed connection without sending complete message body (incomplete chunked read)"),
        {"content": json.dumps({"concepts": _concepts()})},
    )
    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=completion,
    ):
        result = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
        }))

    assert result["status"] == "ok"
    assert completion.call_count == 2
    assert result["data"]["run"]["attempt"] == 2
    assert result["data"]["run"]["result_mode"] == "model"


def test_auth_and_configuration_failures_do_not_retry():
    for failure in (RuntimeError("401 Unauthorized"), RuntimeError("model configuration missing")):
        db = _db()
        session = _session(db)
        completion = _streaming_completion(failure)
        with patch(
            "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
            new=completion,
        ):
            result = asyncio.run(generate_novel_creation_stage(db, "", {
                "session_id": session.id,
                "stage": "concepts",
                "model": "openai:test",
                "use_model": True,
            }))
        assert result["status"] == "error"
        assert completion.call_count == 1


def test_durable_cancellation_after_model_return_never_saves_stage_data():
    db = _db()
    session = _session(db)
    original = deepcopy(session.draft_json)

    def cancel_before_return(**_kwargs):
        async def generate():
            run = db.query(NovelCreationStageRun).order_by(NovelCreationStageRun.created_at.desc()).first()
            operation = db.get(OperationRun, run.operation_id)
            operation.status = "cancelled"
            db.commit()
            yield json.dumps({"concepts": _concepts()})

        return generate()

    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=MagicMock(side_effect=cancel_before_return),
    ):
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(generate_novel_creation_stage(db, "", {
                "session_id": session.id,
                "stage": "concepts",
                "model": "openai:test",
                "use_model": True,
            }))

    db.refresh(session)
    assert session.draft_json == original


def test_refine_that_rewrites_author_locks_keeps_original_concepts():
    db = _db()
    session = NovelCreationSession(mode="internal_llm", status="drafting", user_brief="周遥调查花色异常")
    db.add(session)
    initialize_session_draft(session, {
        "creation_mode": "author_led",
        "author_brief": "周遥是植物学实习生，她调查公共温室的花色异常。",
        "author_outline": "全书六卷。",
        "locked_requirements": ["周遥必须是植物学实习生", "核心设定：温室按季节轮换花卉", "全书必须六卷"],
    })
    original = deepcopy(_concepts()[0])
    original["protagonist_seed"].update({"name": "周遥", "identity": "植物学实习生"})
    original["world_hook"] = "河谷镇依靠公共温室维持四季花展"
    save_compact_concepts(session, [original], source="author")
    db.commit()
    before = deepcopy(session.draft_json["concepts"])
    rewritten = deepcopy(original)
    rewritten["protagonist_seed"].update({"name": "程野", "identity": "记者"})
    rewritten["world_hook"] = "一座普通城市"
    completion = _streaming_completion(
        {"content": json.dumps({"concepts": [rewritten]}, ensure_ascii=False)},
        {"content": json.dumps({"concepts": [rewritten]}, ensure_ascii=False)},
    )

    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=completion,
    ):
        result = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
            "operation": "refine",
            "instruction": "加强悬疑感",
        }))

    assert result["status"] == "ok"
    assert result["data"]["run"]["result_mode"] == "deterministic_fallback"
    assert session.draft_json["concepts"] == before


def test_explicit_six_volume_lock_is_a_hard_result_contract():
    draft = {
        "creation_mode": "author_led",
        "author_outline": "全书六卷，最终公开被调换的土壤试剂检测报告。",
        "locked_requirements": ["全书必须六卷"],
    }
    invalid = {"volumes": [{"title": f"第{index}卷"} for index in range(1, 4)]}
    with pytest.raises(AuthorLockViolation, match="6 卷"):
        _validate_author_requirements("macro_outline", invalid, {}, draft)

    valid = {"volumes": [{"title": f"第{index}卷"} for index in range(1, 7)]}
    _validate_author_requirements("macro_outline", valid, {}, draft)


def test_author_locks_cannot_be_hidden_in_unrelated_concept_fields():
    draft = {
        "creation_mode": "author_led",
        "author_brief": "Zhou Yao is a botany intern investigating a greenhouse color anomaly.",
        "locked_requirements": [
            "\u5468\u9065\u5fc5\u987b\u662f\u690d\u7269\u5b66\u5b9e\u4e60\u751f",
            "\u6838\u5fc3\u8bbe\u5b9a\uff1a\u6e29\u5ba4\u6309\u5b63\u8282\u8f6e\u6362\u82b1\u5349",
        ],
    }
    rewritten = deepcopy(_concepts()[0])
    rewritten["protagonist_seed"] = {
        "name": "Cheng Ye",
        "identity": "Reporter",
        "goal": "Win a journalism prize",
        "lack": "Acts too quickly",
    }
    rewritten["world_hook"] = "A conventional contemporary city."
    rewritten["differentiators"] = list(draft["locked_requirements"])

    with pytest.raises(AuthorLockViolation):
        _validate_author_requirements(
            "concepts",
            {"options": [rewritten]},
            {},
            draft,
        )


def test_invalid_json_is_repaired_once_and_refine_failure_keeps_current_concepts():
    db = _db()
    session = _session(db)
    invalid = json.dumps({"concepts": _concepts()[:2]})
    valid = json.dumps({"concepts": _concepts()})
    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=_streaming_completion({"content": invalid}, {"content": valid}),
    ):
        repaired = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
        }))
    assert repaired["status"] == "ok"
    assert repaired["data"]["run"]["result_mode"] == "repaired"
    before = deepcopy(session.draft_json["concepts"])

    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=_streaming_completion({"content": invalid}, {"content": invalid}),
    ):
        refined = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
            "operation": "refine",
            "instruction": "保留人物，只加强开篇钩子",
        }))
    assert refined["status"] == "ok"
    assert refined["data"]["run"]["result_mode"] == "deterministic_fallback"
    assert session.draft_json["concepts"] == before


def test_stage_run_freezes_the_click_time_draft_revision_and_hash():
    db = _db()
    session = _session(db)
    clicked_revision = session.revision
    clicked_draft = json.loads(json.dumps(session.draft_json))
    run = create_stage_run(db, session, "concepts", {"model": "openai:test"})

    patch_session(session, {"form": {"brief": "A later author edit"}})
    db.commit()

    assert run.input_revision == clicked_revision
    assert run.request_json["input_snapshot"] == clicked_draft
    assert run.input_snapshot_hash == input_snapshot_hash(clicked_draft)
    assert run.request_json["input_snapshot"]["form"]["brief"] != session.draft_json["form"]["brief"]


def test_long_stage_save_uses_revision_cas_and_preserves_manual_edit():
    db = _db()
    session = _session(db)
    manual_brief = "Manual edit made while the model is still generating."

    def edit_then_stream(**_kwargs):
        async def generate():
            patch_session(session, {"author_brief": manual_brief})
            db.commit()
            yield json.dumps({"concepts": _concepts()})

        return generate()

    with patch(
        "app.services.workspace.tools.novel_creation_v2.LLMGateway.stream_chat_completion",
        new=MagicMock(side_effect=edit_then_stream),
    ):
        result = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
        }))

    db.refresh(session)
    run = db.query(NovelCreationStageRun).order_by(NovelCreationStageRun.created_at.desc()).first()
    operation = db.get(OperationRun, run.operation_id)
    assert result["status"] == "error"
    assert run.status == "failed"
    assert run.failure_class == "revision_conflict"
    assert session.draft_json["author_brief"] == manual_brief
    assert session.draft_json.get("concepts") == []
    assert operation.status == "failed"
    assert operation.can_cancel is False
    assert operation.can_retry is True


def test_unusable_context_finishes_run_operation_and_stream_contract():
    db = _db()
    session = _session(db)
    manifest = SimpleNamespace(id="context-stale", status="stale")

    with patch(
        "app.services.novel_creation_stage_execution.ContextOrchestrator.prepare",
        return_value=manifest,
    ), patch(
        "app.services.novel_creation_stage_execution.ContextOrchestrator.validate",
        return_value=(False, "The context must be rebuilt before generation."),
    ):
        result = asyncio.run(generate_novel_creation_stage(db, "", {
            "session_id": session.id,
            "stage": "concepts",
            "model": "openai:test",
            "use_model": True,
        }))

    run = db.query(NovelCreationStageRun).order_by(NovelCreationStageRun.created_at.desc()).first()
    operation = db.get(OperationRun, run.operation_id)
    assert result["status"] == "stale"
    assert run.status == "failed"
    assert run.failure_class == "stale"
    assert run.completed_at is not None
    assert any(event.event_type == "context_blocked" for event in run.events)
    assert operation.status == "failed"
    assert operation.can_cancel is False
    assert operation.can_retry is True


def test_author_source_changes_invalidate_concepts_and_downstream_stages():
    db = _db()
    session = _session(db)
    save_compact_concepts(session, _concepts())
    patch_session(session, {"selected_concept_id": "concept-1"})
    save_stage(
        session,
        "concepts",
        {"options": session.draft_json["concepts"], "selected_concept_id": "concept-1"},
        confirm=True,
    )
    save_stage(session, "world_style", derive_stage(session, "world_style"), confirm=True)
    db.commit()

    patch_session(session, {"author_outline": "A new author-controlled eight-volume outline."})
    db.commit()

    assert session.draft_json["stages"]["concepts"]["status"] == "stale"
    assert session.draft_json["stages"]["world_style"]["status"] == "stale"


def test_stale_session_patch_returns_conflict_without_overwriting_author_text():
    db = _db()
    session = _session(db)
    original_brief = session.draft_json["form"]["brief"]
    stale_revision = int(session.revision or 0) - 1

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(update_creation_session(
            session.id,
            NovelCreationSessionPatchRequest(
                form={"brief": "This stale text must not win"},
                expected_revision=stale_revision,
            ),
            db,
        ))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["current_revision"] == session.revision
    assert session.draft_json["form"]["brief"] == original_brief


def test_compact_seed_can_drive_stages_and_final_apply_blueprint():
    db = _db()
    session = _session(db)
    save_compact_concepts(session, _concepts())
    patch_session(session, {"selected_concept_id": "concept-1"})
    save_stage(session, "constraints", session.draft_json["form"], confirm=True)
    save_stage(session, "concepts", {"options": session.draft_json["concepts"], "selected_concept_id": "concept-1"}, confirm=True)
    for stage in STAGE_ORDER[2:]:
        save_stage(session, stage, derive_stage(session, stage), confirm=stage != "final_review")

    blueprint = build_apply_blueprint(session)
    assert blueprint["title"] == "Concept 1"
    assert blueprint["protagonist"]["name"] == "Lead 1"
    assert len(blueprint["outline"]) >= 15
    with patch("app.services.workspace.tools.novel_creation._is_real_session", return_value=False):
        applied = asyncio.run(apply_novel_blueprint(db, "", {"session_id": session.id, "mode": "auto"}))
    assert applied["status"] == "ok"


def test_duplicate_running_concept_request_reuses_existing_run():
    db = _db()
    session = _session(db)
    payload = NovelCreationStageRunRequest(stage="concepts", model="openai:test", operation="generate_concepts")
    assert payload.operation == "generate"

    def capture_task(coro):
        coro.close()
        return MagicMock()

    with patch("app.routers.novel_creation.asyncio.create_task", side_effect=capture_task) as create_task:
        first = asyncio.run(start_creation_stage_run(session.id, payload, db))
        second = asyncio.run(start_creation_stage_run(session.id, payload, db))

    assert first.data["run"]["id"] == second.data["run"]["id"]
    assert create_task.call_count == 1


def test_refine_run_request_requires_a_bounded_instruction():
    with pytest.raises(ValueError, match="requires an instruction"):
        NovelCreationStageRunRequest(stage="concepts", operation="refine")
    payload = NovelCreationStageRunRequest(stage="concepts", operation="refine", instruction="  保留角色姓名  ")
    assert payload.instruction == "保留角色姓名"

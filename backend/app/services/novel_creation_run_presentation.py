"""Model-adjudicated presentation for durable novel-creation run cards.

The durable run remains the source of truth for execution, retry, and audit.
This module only decides how that evidence should be explained to the author.
"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any, Literal

from sqlalchemy.orm import Session

from app.core.json_repair import parse_json_object
from app.database.models import NovelCreationStageRun
from app.modules.model_runtime.application.execution import model_executor as LLMGateway
from app.modules.model_runtime.domain.configuration import ModelProviderConfig
from app.services.novel_creation_contract import STAGE_LABELS
from app.services.novel_creation_runs import serialize_run

DISPLAY_STATUSES = frozenset({
    "queued",
    "running",
    "waiting_user",
    "paused",
    "completed",
    "partial_success",
    "failed",
    "cancelled",
    "interrupted",
})
TERMINAL_RUN_STATUSES = frozenset({
    "waiting_user",
    "waiting_author",
    "completed",
    "failed",
    "cancelled",
    "interrupted",
    "superseded",
})
_PRESENTATION_TASKS: dict[str, asyncio.Task[Any]] = {}

CardPresentationStatus = Literal[
    "queued",
    "running",
    "waiting_user",
    "paused",
    "completed",
    "partial_success",
    "failed",
    "cancelled",
    "interrupted",
]


def _text(value: Any, default: str = "") -> str:
    value = str(value or "").strip()
    return value or default


def _artifact_evidence(run: NovelCreationStageRun) -> dict[str, Any] | None:
    if run.stage == "all" or run.stage not in STAGE_LABELS:
        return None
    try:
        # Local import keeps the read-only presenter out of the workspace/run
        # dependency cycle while preserving one canonical artifact serializer.
        from app.services.novel_creation_workspace import serialize_creation_artifact

        artifact = serialize_creation_artifact(run.session, run.stage)
    except (TypeError, ValueError):
        return None
    versions = [
        item
        for item in (run.session.artifact_versions or [])
        if item.artifact_key == run.stage
    ]
    linked_versions = [
        item for item in versions
        if item.run_id == run.id or (
            run.operation_id and item.operation_id == run.operation_id
        )
    ]
    latest = versions[-1] if versions else None
    latest_linked = linked_versions[-1] if linked_versions else None
    return {
        "artifact": artifact.get("artifact"),
        "label": artifact.get("label"),
        "status": artifact.get("status"),
        "stored_status": artifact.get("stored_status"),
        "source": artifact.get("source"),
        "revision": int(artifact.get("revision") or 0),
        "has_data": isinstance(artifact.get("data"), dict) and bool(artifact.get("data")),
        "conflict": deepcopy(artifact.get("conflict")),
        "version_count": len(versions),
        "latest_version": {
            "revision": int(latest.revision or 0),
            "status": latest.status,
            "source": latest.source,
            "change_type": latest.change_type,
            "run_id": latest.run_id,
            "operation_id": latest.operation_id,
        } if latest else None,
        "run_linked_version": {
            "revision": int(latest_linked.revision or 0),
            "status": latest_linked.status,
            "source": latest_linked.source,
            "change_type": latest_linked.change_type,
        } if latest_linked else None,
    }


def build_run_presentation_evidence(
    run: NovelCreationStageRun,
    *,
    assistant_reply: str = "",
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build bounded, factual evidence without exposing full artifact content."""
    run_data = serialize_run(run)
    return {
        "run": {
            "id": run.id,
            "stage": run.stage,
            "stage_label": STAGE_LABELS.get(run.stage, run.stage),
            "operation": run.operation,
            "status": run_data.get("status"),
            "failure_class": run.failure_class,
            "current_message": run.current_message,
            "next_action": run.next_action,
            "input_revision": run.input_revision,
            "result": deepcopy(run.result_json) if isinstance(run.result_json, dict) else None,
            "events": [
                {
                    "sequence": item.get("sequence"),
                    "event_type": item.get("event_type"),
                    "status": item.get("status"),
                    "message": item.get("message"),
                    "payload": item.get("payload"),
                }
                for item in (run_data.get("events") or [])[-12:]
            ],
        },
        "artifact": _artifact_evidence(run),
        "assistant_reply": _text(assistant_reply)[:12_000],
        "tool_results": [
            {
                "tool": _text(item.get("tool"))[:100],
                "status": _text(item.get("status"))[:50],
                "detail": _text(item.get("detail"))[:1_000],
                "data_summary": (
                    {
                        key: deepcopy(value)
                        for key, value in item.get("data", {}).items()
                        if key in {"revision", "run", "artifact", "failure_class"}
                    }
                    if isinstance(item.get("data"), dict) else None
                ),
            }
            for item in (tool_results or [])[-12:]
            if isinstance(item, dict)
        ],
    }


def _fallback_presentation(evidence: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
    """Conservative UI fallback used only when model adjudication is unavailable."""
    run = evidence["run"]
    raw_status = (
        "waiting_user"
        if run.get("status") == "waiting_author"
        else _text(run.get("status"), "running")
    )
    display_status = raw_status if raw_status in DISPLAY_STATUSES else (
        "completed" if raw_status == "superseded" else "failed"
    )
    message = _text(run.get("current_message"), "任务状态正在同步…")
    if display_status == "completed" and raw_status == "superseded":
        message = "当前内容已由更新的任务取代，请以右侧作品资料为准。"
    return {
        "status": display_status,
        "label": {
            "queued": "排队中",
            "running": "正在生成",
            "waiting_user": "等待确认",
            "paused": "已暂停",
            "completed": "已完成",
            "partial_success": "部分完成",
            "failed": "失败",
            "cancelled": "已取消",
            "interrupted": "已中断",
        }[display_status],
        "message": message[:500],
        "show_retry": display_status in {"failed", "cancelled", "interrupted", "partial_success"},
        "judged_by": "fallback",
        "reason": reason[:500],
        "raw_status": run.get("status"),
    }


def _normalize_model_presentation(
    parsed: dict[str, Any] | None,
    *,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise ValueError("展示裁决模型没有返回 JSON 对象")
    status = _text(parsed.get("status"))
    if status not in DISPLAY_STATUSES:
        raise ValueError("展示裁决模型返回了未知状态")
    message = _text(parsed.get("message"))
    if not message:
        raise ValueError("展示裁决模型没有返回卡片说明")
    label = _text(parsed.get("label")) or {
        "queued": "排队中",
        "running": "正在生成",
        "waiting_user": "等待确认",
        "paused": "已暂停",
        "completed": "已完成",
        "partial_success": "部分完成",
        "failed": "失败",
        "cancelled": "已取消",
        "interrupted": "已中断",
    }[status]
    return {
        "status": status,
        "label": label[:20],
        "message": message[:500],
        "show_retry": bool(parsed.get(
            "show_retry",
            status in {"failed", "cancelled", "interrupted", "partial_success"},
        )),
        "judged_by": "model",
        "reason": _text(parsed.get("reason"))[:500],
        "raw_status": evidence["run"].get("status"),
    }


_SYSTEM_PROMPT = """你是司命的“立项任务卡片展示裁决器”。
你只决定卡片如何向作者展示，不修改底层 run 状态、数据、重试资格或审计记录。
请综合真实证据判断用户请求的实际结果，而不是机械复制 run.status：
- 只要目标 artifact 已被本 run 或本轮成功写入，并且现在可审阅，
  应显示 waiting_user；若已确认则 completed。
- 若本轮先成功写入、之后又有非关键步骤失败，可显示 partial_success，并准确说明已完成与未完成部分。
- 助手自然语言只是一项证据；不能用一句“已完成”覆盖没有写入、事件或版本佐证的失败。
- 若 artifact 的成功修改来自另一次操作，不能把本 run 冒充为成功；但可以说明最新内容已存在。
- queued/running/paused/cancelled/interrupted 应尊重运行事实，除非明确证据证明目标结果已落盘。
- 不要隐藏真实问题，不要编造数据；message 必须简洁、面向作者。
只输出一个 JSON 对象：
{"status":"queued|running|waiting_user|paused|completed|partial_success|failed|cancelled|interrupted","label":"短标签","message":"卡片说明","show_retry":true|false,"reason":"简短证据理由"}"""


async def judge_run_card_presentation(
    db: Session,
    *,
    run: NovelCreationStageRun,
    model: str | None,
    assistant_reply: str = "",
    tool_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Ask the selected API or local-CLI model to adjudicate one card."""
    evidence = build_run_presentation_evidence(
        run,
        assistant_reply=assistant_reply,
        tool_results=tool_results,
    )
    if not model:
        model = run.model_source
    if not model:
        return _fallback_presentation(evidence, reason="未配置可用于展示裁决的模型")
    try:
        extra_body = LLMGateway.local_cli_extra_body(
            model,
            base={
                "moshu_task_type": "planning",
                "local_cli_isolated": True,
                "local_cli_allow_mcp": False,
                "local_cli_timeout_seconds": 180,
            },
        )
        response = await LLMGateway.chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(evidence, ensure_ascii=False, default=str)},
            ],
            model=model,
            temperature=0,
            max_tokens=500,
            timeout=180,
            retry=1,
            extra_body=extra_body,
        )
        presentation = _normalize_model_presentation(
            parse_json_object(_text(response.get("content"))),
            evidence=evidence,
        )
        presentation["model"] = model
        try:
            provider, resolved_model = LLMGateway.model_identity(
                model,
                {"moshu_task_type": "planning"},
            )
            presentation["provider"] = provider
            presentation["resolved_model"] = resolved_model
            presentation["route"] = "cli" if str(provider).endswith("_cli") else "api"
        except Exception:
            presentation["route"] = "unknown"
        return presentation
    except Exception as exc:
        return _fallback_presentation(evidence, reason=f"展示裁决暂不可用：{str(exc)[:300]}")


async def present_serialized_run(
    db: Session,
    *,
    run: NovelCreationStageRun,
    model: str | None = None,
    assistant_reply: str = "",
    tool_results: list[dict[str, Any]] | None = None,
    include_events: bool = True,
) -> dict[str, Any]:
    if run.status in TERMINAL_RUN_STATUSES:
        requested_model = _text(model)
        scheduled = _PRESENTATION_TASKS.get(run.id)
        if (
            scheduled
            and not scheduled.done()
            and scheduled is not asyncio.current_task()
            and not assistant_reply
            and not tool_results
            and (not requested_model or requested_model == _text(run.model_source))
        ):
            try:
                await asyncio.shield(scheduled)
                db.refresh(run)
            except Exception:
                pass
    data = serialize_run(run, include_events=include_events)
    if run.status in TERMINAL_RUN_STATUSES:
        stored = (
            (run.result_json or {}).get("card_presentation")
            if isinstance(run.result_json, dict) else None
        )
        stored_model = _text(stored.get("model")) if isinstance(stored, dict) else ""
        raw_status = "waiting_user" if run.status == "waiting_author" else run.status
        if (
            isinstance(stored, dict)
            and stored.get("judged_by") == "model"
            and _text(stored.get("raw_status")) == raw_status
            and not assistant_reply
            and not tool_results
            and (not requested_model or requested_model == stored_model)
        ):
            data["card_presentation"] = deepcopy(stored)
        else:
            data["card_presentation"] = await judge_run_card_presentation(
                db,
                run=run,
                model=model,
                assistant_reply=assistant_reply,
                tool_results=tool_results,
            )
    return data


def schedule_run_card_presentation(
    run_id: str,
    *,
    request_provider: ModelProviderConfig | None = None,
) -> asyncio.Task[Any] | None:
    """Precompute the model view after a terminal background run is committed."""
    existing = _PRESENTATION_TASKS.get(run_id)
    if existing and not existing.done():
        return existing

    async def worker() -> None:
        from app.architecture.uow import commit_session
        from app.database.session import SessionLocal

        db = SessionLocal()
        try:
            run = db.get(NovelCreationStageRun, run_id)
            if not run or run.status not in TERMINAL_RUN_STATUSES:
                return
            if request_provider is None:
                presentation = await judge_run_card_presentation(
                    db,
                    run=run,
                    model=run.model_source,
                )
            else:
                from app.modules.model_runtime.application.request_override import use_request_provider

                with use_request_provider(request_provider):
                    presentation = await judge_run_card_presentation(
                        db,
                        run=run,
                        model=run.model_source,
                    )
            result = deepcopy(run.result_json) if isinstance(run.result_json, dict) else {}
            result["card_presentation"] = presentation
            run.result_json = result
            commit_session(db)
        finally:
            db.close()
            _PRESENTATION_TASKS.pop(run_id, None)

    try:
        task = asyncio.create_task(worker())
    except RuntimeError:
        return None
    _PRESENTATION_TASKS[run_id] = task
    return task


__all__ = [
    "DISPLAY_STATUSES",
    "TERMINAL_RUN_STATUSES",
    "build_run_presentation_evidence",
    "judge_run_card_presentation",
    "present_serialized_run",
    "schedule_run_card_presentation",
]

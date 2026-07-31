"""Small runtime helpers for novel-creation stage orchestration."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.architecture.uow import commit_session
from app.services.novel_creation_workspace import (
    STAGE_LABELS,
    add_run_event,
    serialize_run,
    serialize_session,
)
from app.services.observability.run_events import classify_failure


async def stage_data_with_fallback(
    db: Session,
    run: Any,
    session: Any,
    *,
    stage: str,
    baseline: dict[str, Any],
    model: str,
    use_model: bool,
    quick_run: bool,
    manifest: Any,
    working_draft: dict[str, Any],
    enhance: Any,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    if not use_model or not model or stage == "final_review":
        return baseline, "contract", {"attempt": 0, "result_mode": "deterministic_fallback", "warning": None}
    try:
        enhanced = await enhance(
            session,
            stage,
            baseline,
            model,
            context_manifest=manifest,
            input_snapshot=working_draft,
        )
        if isinstance(enhanced, tuple):
            data, metadata = enhanced
        else:
            data, metadata = enhanced, {"attempt": 1, "result_mode": "model", "warning": None}
        return data, "model" if metadata.get("result_mode") == "model" else "model_repaired", metadata
    except Exception as exc:
        failure_class = classify_failure(str(exc))
        if failure_class not in {"empty_response", "invalid_response"}:
            raise
        attempt = max(1, int(getattr(exc, "attempt", 1)))
        warning = f"{STAGE_LABELS.get(stage, stage)}的模型回复格式不可用，已保留可编辑安全草稿"
        add_run_event(
            db,
            run,
            "stage_repaired",
            "warning",
            warning,
            {
                "stage": stage,
                "failure_class": failure_class,
                "attempt": attempt,
                "result_mode": "deterministic_fallback",
                "storage_target": "session_draft",
                "next_action": "可在最终审阅前检查并编辑本阶段内容",
            },
        )
        commit_session(db)
        return baseline, "contract_fallback", {
            "attempt": attempt,
            "result_mode": "deterministic_fallback",
            "warning": warning,
        }


def stage_tool_result(status: str, detail: str, run: Any, session: Any) -> dict[str, Any]:
    return {
        "tool": "generate_novel_creation_stage",
        "status": status,
        "detail": detail,
        "data": {"run": serialize_run(run), "session": serialize_session(session)},
    }

"""Small runtime helpers for novel-creation stage orchestration."""
from __future__ import annotations

from typing import Any

from app.services.novel_creation_context_projection import artifact_data_shape
from app.services.novel_creation_workspace import (
    serialize_run,
    serialize_session,
)


async def generate_stage_data(
    session: Any,
    *,
    stage: str,
    baseline: dict[str, Any],
    model: str,
    use_model: bool,
    manifest: Any,
    working_draft: dict[str, Any],
    enhance: Any,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    if not use_model or not model:
        raise RuntimeError("当前没有可用于立项生成的模型")
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


def stage_tool_result(status: str, detail: str, run: Any, session: Any) -> dict[str, Any]:
    artifact = session.current_stage if run.stage == "all" else run.stage
    state = ((session.draft_json or {}).get("stages") or {}).get(artifact) or {}
    saved = status == "ok" and run.status in {"waiting_user", "waiting_author", "completed"}
    return {
        "tool": "generate_creation_artifact",
        "status": status,
        "detail": detail,
        "data": {
            "run": serialize_run(run), "session": serialize_session(session),
            "run_id": run.id, "session_id": session.id, "operation_id": run.operation_id,
            "artifact": artifact, "revision": int(session.revision or 0),
            "status": state.get("status") or "pending", "saved": saved,
            "requires_confirmation": saved and state.get("status") != "confirmed",
            "next_action": run.next_action,
            "collection_counts": artifact_data_shape(artifact, state.get("data"))["collection_counts"],
        },
    }

"""Read-time compatibility projections for historical novel-creation drafts."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def _record(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _looks_like_lifecycle_event(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    event_type = _text(data.get("type")).lower().replace("-", "_")
    part_type = _text(_record(data.get("part")).get("type")).lower().replace("-", "_")
    lifecycle_types = {"step_start", "step_finish", "message_start", "message_finish", "tool_start", "tool_finish"}
    return event_type in lifecycle_types or part_type in lifecycle_types


def project_legacy_draft(draft: dict[str, Any], stage_order: tuple[str, ...]) -> dict[str, Any]:
    projected = deepcopy(draft)
    try:
        schema_version = int(projected.get("schema_version") or 1)
    except (TypeError, ValueError):
        schema_version = 1
    if schema_version < 3:
        # V2 only supported the three-card exploration path. Present a complete
        # V3 read contract immediately, while leaving the stored historical
        # payload untouched until the author next saves it.
        projected["schema_version"] = 3
        projected["creation_mode"] = "explore"
        projected.setdefault("author_brief", "")
        projected.setdefault("author_outline", "")
        projected.setdefault("locked_requirements", [])
    elif projected.get("creation_mode") not in {"author_led", "explore"}:
        projected["creation_mode"] = "explore"
    stages = _record(projected.get("stages"))
    for stage in stage_order:
        state = _record(stages.get(stage))
        if _looks_like_lifecycle_event(state.get("data")):
            state.update({
                "status": "stale",
                "data": None,
                "stale_reason": "历史模型只返回了运行状态，请重新生成本阶段",
            })
            stages[stage] = state
    projected["stages"] = stages
    return projected


def projected_generation_blockers(
    draft: dict[str, Any],
    stage: str,
    stage_order: tuple[str, ...],
    stage_labels: dict[str, str],
) -> list[dict[str, str]]:
    if stage not in {*stage_order, "all"}:
        return [{"stage": stage, "label": stage, "reason": "unknown_stage"}]
    # 3.1.3 removes the fixed wizard order for artifact generation. True hard
    # dependencies are enforced by finalization and chapter-writing contracts,
    # while missing planning inputs are surfaced separately as soft hints.
    return []

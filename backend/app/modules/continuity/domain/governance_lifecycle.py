"""Narrative governance lifecycle invariants shared by every write path."""

from __future__ import annotations

from typing import Any

ITEM_TYPE_ALIASES = {
    "foreshadowing": "foreshadowings",
    "foreshadowings": "foreshadowings",
    "causal_edge": "causal-edges",
    "causal-edges": "causal-edges",
    "narrative_debt": "narrative-debts",
    "narrative-debts": "narrative-debts",
}

ALLOWED_STATUSES = {
    "foreshadowings": {"open", "pending_review", "deferred", "fulfilled", "abandoned", "stale"},
    "causal-edges": {"open", "pending_review", "resolved", "invalidated", "stale"},
    "narrative-debts": {"open", "pending_review", "deferred", "fulfilled", "abandoned", "stale"},
}

FINAL_STATUS = {
    "foreshadowings": "fulfilled",
    "causal-edges": "resolved",
    "narrative-debts": "fulfilled",
}

TERMINAL_STATUSES = {"fulfilled", "resolved", "abandoned", "invalidated"}

TRANSITIONS = {
    "open": {"pending_review", "deferred", "abandoned", "invalidated"},
    "deferred": {"open", "pending_review", "abandoned"},
    "pending_review": {"open", "fulfilled", "resolved", "abandoned", "invalidated"},
    "fulfilled": {"open"},
    "resolved": {"open"},
    "abandoned": {"open"},
    "invalidated": {"open"},
    "stale": {"open", "pending_review", "abandoned", "invalidated"},
}


def normalize_item_type(item_type: str) -> str:
    normalized = ITEM_TYPE_ALIASES.get(str(item_type or "").strip().lower())
    if not normalized:
        raise ValueError("不支持的治理对象类型")
    return normalized


def final_status_for(item_type: str) -> str:
    return FINAL_STATUS[normalize_item_type(item_type)]


def validate_transition(
    item_type: str,
    current_status: str,
    target_status: str,
    values: dict[str, Any],
) -> str:
    """Reject impossible or unverifiable lifecycle transitions."""

    normalized_type = normalize_item_type(item_type)
    current = str(current_status or "open")
    target = str(target_status or "").strip().lower()
    if target not in ALLOWED_STATUSES[normalized_type] or target == "stale":
        raise ValueError("该治理对象不支持目标状态")
    if target in {"fulfilled", "resolved"} and current != "pending_review":
        raise ValueError("必须先提交复检，不能直接关闭治理项")
    if target != current and target not in TRANSITIONS.get(current, set()):
        raise ValueError(f"不能从 {current} 直接变更为 {target}")

    resolution_note = str(values.get("resolution_note") or "").strip()
    verification_note = str(values.get("verification_note") or "").strip()
    resolved_chapter_id = str(values.get("resolved_chapter_id") or "").strip()

    if target == "pending_review":
        if not resolved_chapter_id:
            raise ValueError("提交复检前必须选择实际修订的章节")
        if len(resolution_note) < 4:
            raise ValueError("提交复检前请填写至少 4 个字符的解决说明")

    if target == "deferred" and not (
        values.get("target_chapter_id") or values.get("target_chapter_number")
    ):
        raise ValueError("延期治理项必须指定计划处理章节")

    if target in {"fulfilled", "resolved"}:
        if not resolved_chapter_id:
            raise ValueError("关闭治理项必须绑定解决章节")
        if len(resolution_note) < 4:
            raise ValueError("关闭治理项必须保留解决说明")
        if len(verification_note) < 4:
            raise ValueError("关闭治理项必须填写至少 4 个字符的复检结论")

    if target in {"abandoned", "invalidated"} and len(resolution_note) < 4:
        raise ValueError("放弃或作废治理项必须填写原因")

    if current in {*TERMINAL_STATUSES, "stale"} and target == "open" and len(resolution_note) < 4:
        raise ValueError("重新打开治理项必须填写原因")
    return normalized_type


__all__ = [
    "ALLOWED_STATUSES",
    "FINAL_STATUS",
    "TERMINAL_STATUSES",
    "final_status_for",
    "normalize_item_type",
    "validate_transition",
]

"""Deterministic presentation of tool execution states, never user intent."""

TOOL_COMPLETED_STATUSES = frozenset({"ok", "completed", "success", "succeeded"})
TOOL_SUCCESS_STATUSES = TOOL_COMPLETED_STATUSES | {"ready"}
TOOL_ERROR_STATUSES = frozenset({"error", "failed", "interrupted"})
TOOL_OPEN_STATUSES = frozenset({"pending", "queued", "running", "in_progress"})


def tool_status_detail(tool: str | None, status: str) -> str:
    """Describe only the declared state; unknown states are not failures."""

    label = tool or "工具步骤"
    status = status.strip().lower()
    if status == "ready":
        return f"{label} 已就绪"
    if status in TOOL_COMPLETED_STATUSES:
        return f"{label} 已完成"
    if status == "needs_confirmation":
        return f"{label} 等待确认"
    if status in {"cancelled", "canceled", "aborted"}:
        return f"{label} 已取消"
    if status in {"skipped", "superseded"}:
        return f"{label} 未执行"
    if status in TOOL_OPEN_STATUSES:
        return f"正在执行 {label}"
    if status in TOOL_ERROR_STATUSES:
        return f"{label} 执行失败"
    if status in {"denied", "rejected"}:
        return f"{label} 已拒绝"
    return f"{label} 状态已更新"

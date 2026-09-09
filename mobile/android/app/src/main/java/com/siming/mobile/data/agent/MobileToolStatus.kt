package com.siming.mobile.data.agent

/** Same deterministic state descriptions as the PC tool-status contract. */
internal fun mobileToolStatusDetail(tool: String, status: String): String = when (status.trim().lowercase()) {
    "ready" -> "$tool 已就绪"
    "ok", "completed", "success", "succeeded" -> "$tool 已完成"
    "needs_confirmation" -> "$tool 等待确认"
    "cancelled", "canceled", "aborted" -> "$tool 已取消"
    "skipped", "superseded" -> "$tool 未执行"
    "pending", "queued", "running", "in_progress" -> "正在执行 $tool"
    "error", "failed", "interrupted" -> "$tool 执行失败"
    "denied", "rejected" -> "$tool 已拒绝"
    else -> "$tool 状态已更新"
}

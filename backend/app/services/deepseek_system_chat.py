"""Reasoning-aware DeepSeek execution for open-ended system conversations."""
from __future__ import annotations

import time
from typing import Any

from app.modules.model_runtime.application.execution import model_executor as LLMGateway
from app.services.operation_runtime import current_operation_id, record_operation_signal


async def stream_deepseek_system_chat(
    *,
    messages: list[dict[str, str]],
    model: str | None,
    extra_body: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Preserve thinking, then recover once if no final answer is emitted."""
    operation_id = current_operation_id()
    reasoning_chars = 0
    content_chunks: list[str] = []
    finish_reason = ""
    last_report_at = 0.0
    thinking_body = dict(extra_body or {})
    thinking_body["thinking"] = {"type": "enabled"}
    thinking_body["reasoning_effort"] = "high"
    stream = LLMGateway.stream_chat_completion_with_tools(
        messages=messages,
        model=model,
        temperature=0.7,
        max_tokens=8000,
        timeout=0,
        retry=0,
        extra_body=thinking_body,
        tools=None,
        tool_choice=None,
    )
    async for event in stream:
        event_type = event.get("type")
        if event_type == "reasoning_delta":
            reasoning_chars += len(str(event.get("delta") or ""))
        elif event_type == "content_delta":
            content_chunks.append(str(event.get("delta") or ""))
        elif event_type == "done":
            finish_reason = str(event.get("finish_reason") or "")
        now = time.monotonic()
        if operation_id and now - last_report_at >= 2:
            last_report_at = now
            record_operation_signal(
                operation_id,
                "output",
                {
                    "reasoning_chars": reasoning_chars,
                    "output_chars": sum(len(item) for item in content_chunks),
                    "phase": "reasoning" if not content_chunks else "answering",
                },
                message="DeepSeek 正在思考" if not content_chunks else "司命正在组织回复",
            )

    reply = "".join(content_chunks).strip()
    diagnostics = {
        "thinking_enabled": True,
        "reasoning_chars": reasoning_chars,
        "finish_reason": finish_reason or None,
        "recovered_without_thinking": False,
    }
    if reply or not reasoning_chars:
        return reply, diagnostics

    fallback_body = dict(extra_body or {})
    fallback_body["thinking"] = {"type": "disabled"}
    fallback_chunks: list[str] = []
    fallback = LLMGateway.stream_chat_completion(
        messages=messages,
        model=model,
        temperature=0.7,
        max_tokens=1600,
        timeout=0,
        retry=0,
        extra_body=fallback_body,
    )
    async for chunk in fallback:
        fallback_chunks.append(chunk)
    diagnostics["recovered_without_thinking"] = True
    return "".join(fallback_chunks).strip(), diagnostics

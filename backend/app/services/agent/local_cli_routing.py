"""Model-decided routing for workspace requests sent to a local Agent CLI."""
from __future__ import annotations

import json
from typing import Any

from ...modules.model_runtime.application.execution import model_executor as LLMGateway


_ROUTES = {"general", "chapter_write", "chapter_rewrite", "cataloging"}


def _strict_json_object(text: str) -> dict[str, Any] | None:
    """Parse one JSON object without using wording/intent regular expressions."""
    value = str(text or "").strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines and lines[0].lstrip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        start = value.find("{")
        end = value.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            parsed = json.loads(value[start : end + 1])
        except (TypeError, ValueError):
            return None
    return parsed if isinstance(parsed, dict) else None


async def classify_local_cli_workspace_request(
    *,
    model: str,
    message: str,
    selected_outline_node_id: str | None = None,
) -> dict[str, Any]:
    """Ask the selected CLI itself which Siming execution route is required."""
    system = """你是司命本机 CLI 的请求路由器。只判断执行线路，不执行任务，不调用工具。
只返回一个 JSON 对象，禁止解释、Markdown 或额外文本。
route 只能是：
- general：问答、资料查询、设定/大纲/角色等一般项目协作
- chapter_write：创建新的章节正文
- chapter_rewrite：替换已有章节正文
- cataloging：对已导入小说进行建档、资料抽取或连续性归档
同时提取 chapter_number（明确出现才填写整数，否则 null）和 outline_query（用户用于指向章节的原话，没有则空字符串）。
不要依赖固定关键词；按整句话的真实意图判断。"""
    user = json.dumps(
        {
            "request": str(message or ""),
            "selected_outline_node_id": selected_outline_node_id or None,
            "output_schema": {
                "route": "general|chapter_write|chapter_rewrite|cataloging",
                "chapter_number": "integer|null",
                "outline_query": "string",
                "reason": "short string",
            },
        },
        ensure_ascii=False,
    )
    extra_body = LLMGateway.local_cli_extra_body(
        model,
        base={
            "local_cli_isolated": True,
            "local_cli_allow_mcp": False,
            "local_cli_timeout_seconds": 180,
        },
    )
    result = await LLMGateway.chat_completion(
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        model=model,
        temperature=0,
        max_tokens=500,
        timeout=180,
        retry=1,
        extra_body=extra_body,
    )
    parsed = _strict_json_object(str(result.get("content") or "")) or {}
    route = str(parsed.get("route") or "general").strip().lower()
    if route not in _ROUTES:
        route = "general"
    try:
        chapter_number = int(parsed["chapter_number"]) if parsed.get("chapter_number") is not None else None
    except (TypeError, ValueError):
        chapter_number = None
    if chapter_number is not None and chapter_number <= 0:
        chapter_number = None
    return {
        "route": route,
        "chapter_number": chapter_number,
        "outline_query": str(parsed.get("outline_query") or "").strip(),
        "reason": str(parsed.get("reason") or "").strip()[:300],
    }


__all__ = ["classify_local_cli_workspace_request"]

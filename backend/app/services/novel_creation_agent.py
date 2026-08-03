"""Tool-driven conversational control plane for a creation session."""
from __future__ import annotations

import json
import inspect
from typing import Any

from sqlalchemy.orm import Session

from app.core.json_repair import parse_json_object
from app.modules.model_runtime.application.execution import model_executor as LLMGateway
from app.services.workspace.executor import execute_workspace_action
from app.services.workspace.registry import registry


CREATION_AGENT_TOOLS = {
    "get_creation_session", "get_creation_snapshot", "get_creation_operation",
    "get_creation_artifact", "list_creation_artifacts", "get_creation_dependencies",
    "get_creation_dependency_graph", "validate_creation_consistency",
    "patch_creation_session", "patch_creation_artifact", "lock_creation_fields",
    "unlock_creation_fields", "undo_creation_artifact", "list_creation_entities",
    "get_creation_entity", "patch_creation_entity", "delete_creation_entity",
    "list_creation_artifact_versions", "get_creation_artifact_diff",
    "restore_creation_artifact_version", "confirm_creation_artifact",
    "generate_creation_artifact", "refine_creation_artifact",
    "regenerate_creation_artifact", "cancel_creation_operation",
    "pause_creation_operation", "resume_creation_operation", "retry_creation_operation",
    "validate_creation_session", "finalize_creation_session",
    "preview_creation_import", "apply_creation_import", "list_imported_files",
    "read_imported_file",
}

_SESSION_TOOLS = {
    name for name in CREATION_AGENT_TOOLS
    if name not in {
        "get_creation_operation", "get_creation_entity", "patch_creation_entity",
        "delete_creation_entity", "get_creation_artifact_diff",
        "restore_creation_artifact_version", "cancel_creation_operation",
        "pause_creation_operation", "resume_creation_operation",
        "retry_creation_operation", "read_imported_file",
    }
}

_REVISION_TOOLS = {
    "patch_creation_session", "patch_creation_artifact", "lock_creation_fields",
    "unlock_creation_fields", "undo_creation_artifact", "patch_creation_entity",
    "delete_creation_entity", "restore_creation_artifact_version",
    "confirm_creation_artifact", "generate_creation_artifact",
    "refine_creation_artifact", "regenerate_creation_artifact",
    "apply_creation_import",
}

_WRITE_TOOLS = {
    "patch_creation_session", "patch_creation_artifact", "lock_creation_fields",
    "unlock_creation_fields", "undo_creation_artifact", "patch_creation_entity",
    "delete_creation_entity", "restore_creation_artifact_version",
    "confirm_creation_artifact", "generate_creation_artifact",
    "refine_creation_artifact", "regenerate_creation_artifact",
    "cancel_creation_operation", "pause_creation_operation",
    "resume_creation_operation", "retry_creation_operation",
    "finalize_creation_session", "apply_creation_import",
}


def _tool_schemas() -> list[dict[str, Any]]:
    return [
        schema for schema in registry.get_schemas()
        if schema.get("function", {}).get("name") in CREATION_AGENT_TOOLS
    ]


def _cli_tool_bridge_prompt(schemas: list[dict[str, Any]]) -> str:
    """Expose Siming tools to text-only CLIs through a strict JSON bridge."""
    catalog = []
    for schema in schemas:
        function = schema.get("function") if isinstance(schema, dict) else None
        if not isinstance(function, dict):
            continue
        catalog.append({
            "name": function.get("name"),
            "description": function.get("description"),
            "parameters": function.get("parameters") or {"type": "object"},
        })
    return (
        "当前运行环境是文本型 CLI，但司命提供了一个由应用代为执行的立项工具桥。"
        "你不需要也不得直接修改数据库或项目文件。每次回复必须只输出一个 JSON 对象，格式为："
        '{"reply":"给用户的简短中文说明或追问","actions":[{"tool":"工具名","arguments":{}}]}。'
        "需要读取或写入时把调用放入 actions；司命会校验权限、自动绑定当前 session_id、补充 expected_revision，"
        "执行后把真实结果交回给你。拿到结果后可以继续调用，也可以返回 actions=[] 并在 reply 中总结。"
        "不得声称未成功的写入已经保存。可用工具如下：\n"
        + json.dumps(catalog, ensure_ascii=False, separators=(",", ":"))
    )


def _parse_cli_tool_bridge(content: str) -> tuple[bool, str, list[dict[str, Any]]]:
    """Convert the CLI bridge JSON into the same calls used by native tools."""
    payload = parse_json_object(content)
    if not isinstance(payload, dict) or "actions" not in payload:
        return False, content.strip(), []
    reply = str(payload.get("reply") or "").strip()
    raw_actions = payload.get("actions")
    calls: list[dict[str, Any]] = []
    if isinstance(raw_actions, list):
        for index, action in enumerate(raw_actions[:12]):
            if not isinstance(action, dict):
                continue
            name = str(action.get("tool") or action.get("name") or "").strip()
            if not name:
                continue
            arguments = action.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            calls.append({
                "id": f"cli-creation-tool-{index}",
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            })
    return True, reply, calls


def _system_prompt(session_id: str) -> str:
    return f"""你是司命的对话式立项助手。当前 creation session_id={session_id}。
所有世界观、角色、关系、地点、势力、分卷、章节细纲、场景细纲和创作约束都必须通过工具读取和修改。
你可以按任意顺序工作；不要强迫用户走固定阶段。缺少软依赖时说明影响，但不要阻止用户。
每轮先读取会话及相关 artifact/entity，结合当前数据缺口决定下一步，再自行调用零到多个工具。
如果用户给出了新事实、偏好或回答，先把能确定的内容立即增量写入对应结构化数据，再提出一个最有价值的后续问题；不要把数据积攒到“采访结束”后才生成。
用户对你上一轮问题的简短回答也是有效的新事实。只要含义足够明确，本轮必须至少调用一次 patch_creation_session、patch_creation_artifact、entity 写入或生成工具；不能只反复读取后声称已经保存。
提问必须基于刚读取到的现有数据，避免重复询问已经存在的内容。用户可以随时跳到世界观、角色、地点、势力、分卷或章节细纲，不能在创意阶段结束后停止协作。
用户要求新增对象时，把完整自然语言要求放入 instruction；对象数量由用户语义决定，不要假定固定数量。
局部请求优先使用 entity 工具或带 entity_type/entity_id 的生成工具，不要重写整个 artifact。
写入必须使用刚读取到的 revision；不得改动锁定字段，不得用旧结果覆盖人工新修改。
只有用户明确要求创建正式作品时才调用 finalize_creation_session。
工具返回 running 表示后台任务已经可靠创建，不要重复调用；告诉用户任务已开始即可。
完成工具调用后，用简洁中文说明读取了什么、修改/启动了什么、保留了什么以及可能受影响的数据。"""


async def _complete_tool_turn(**kwargs: Any) -> dict[str, Any]:
    """Collect the gateway's streaming tool protocol into one assistant turn."""
    stream = LLMGateway.stream_chat_completion_with_tools(**kwargs)
    if inspect.isawaitable(stream):
        completed = await stream
        if isinstance(completed, dict):
            return completed

    content: list[str] = []
    calls: dict[int, dict[str, str]] = {}
    async for event in stream:
        event_type = event.get("type")
        if event_type == "content_delta":
            content.append(str(event.get("delta") or ""))
        elif event_type == "tool_call_delta":
            index = int(event.get("index") or 0)
            call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
            if event.get("id"):
                call["id"] = str(event["id"])
            if event.get("name"):
                call["name"] = str(event["name"])
            if event.get("arguments_delta"):
                call["arguments"] += str(event["arguments_delta"])
    tool_calls = [
        {
            "id": call["id"] or f"creation-tool-{index}",
            "type": "function",
            "function": {"name": call["name"], "arguments": call["arguments"] or "{}"},
        }
        for index, call in sorted(calls.items())
        if call["name"]
    ]
    return {"content": "".join(content), "tool_calls": tool_calls}


async def run_creation_agent(
    db: Session,
    *,
    session: Any,
    message: str,
    model: str | None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    messages: list[dict[str, Any]] = [{"role": "system", "content": _system_prompt(session.id)}]
    for item in (history or [])[-12:]:
        role = item.get("role")
        content = str(item.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content[:80_000]})
    messages.append({"role": "user", "content": message})

    tool_results: list[dict[str, Any]] = []
    write_results: list[dict[str, Any]] = []
    seen_calls: set[str] = set()
    final_reply = ""
    schemas = _tool_schemas()
    native_tool_calls = LLMGateway.supports_tool_calling(model)
    if not native_tool_calls:
        messages.insert(1, {"role": "system", "content": _cli_tool_bridge_prompt(schemas)})
    cli_protocol_retries = 0
    for _iteration in range(6):
        result = await _complete_tool_turn(
            messages=messages,
            tools=schemas if native_tool_calls else [],
            model=model,
            temperature=0.25,
            # Do not impose a second fixed cap here. The selected provider and
            # configured model capability remain the source of truth.
            max_tokens=None,
            timeout=0,
        )
        content = str(result.get("content") or "")
        calls = result.get("tool_calls") if isinstance(result.get("tool_calls"), list) else []
        if not native_tool_calls:
            recognized, bridged_reply, bridged_calls = _parse_cli_tool_bridge(content)
            if recognized:
                content = bridged_reply
                calls = bridged_calls
            elif cli_protocol_retries < 1:
                cli_protocol_retries += 1
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": (
                        "上一条回复没有使用司命 CLI 工具桥协议，因此任何内容都尚未写入。"
                        "请立即按系统给出的 JSON 格式返回；需要修改立项数据时必须在 actions 中调用对应写入工具。"
                    ),
                })
                continue
        if not calls:
            final_reply = content.strip()
            break
        messages.append({"role": "assistant", "content": content, "tool_calls": calls})
        for call in calls[:12]:
            function = call.get("function") if isinstance(call, dict) else {}
            name = str((function or {}).get("name") or "")
            raw_arguments = (function or {}).get("arguments") or "{}"
            try:
                arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
            except (json.JSONDecodeError, TypeError, ValueError):
                arguments = parse_json_object(str(raw_arguments)) or {}
            if name not in CREATION_AGENT_TOOLS:
                tool_result = {"tool": name, "status": "skipped", "detail": "该工具不属于立项会话"}
            else:
                if name in _SESSION_TOOLS:
                    arguments["session_id"] = session.id
                if name in _REVISION_TOOLS and not arguments.get("expected_revision"):
                    db.refresh(session)
                    arguments["expected_revision"] = int(session.revision or 0)
                if name in {"generate_creation_artifact", "refine_creation_artifact", "regenerate_creation_artifact"}:
                    arguments.setdefault("model", model)
                signature = json.dumps({"name": name, "arguments": arguments}, ensure_ascii=False, sort_keys=True, default=str)
                if signature in seen_calls:
                    tool_result = {"tool": name, "status": "skipped", "detail": "相同工具调用已执行，本轮不重复提交"}
                else:
                    seen_calls.add(signature)
                    tool_result = await execute_workspace_action(
                        db, "", {"tool": name, "arguments": arguments},
                    )
            tool_results.append(tool_result)
            if name in _WRITE_TOOLS and tool_result.get("status") in {"ok", "running"}:
                write_results.append(tool_result)
            messages.append({
                "role": "tool",
                "tool_call_id": str(call.get("id") or ""),
                "content": json.dumps(tool_result, ensure_ascii=False, default=str)[:120_000],
            })

    if not final_reply and tool_results:
        # Some providers finish a tool round without producing the required
        # user-facing summary. Give the same model one text-only turn grounded
        # in the real tool results; it may summarize but cannot invent writes.
        messages.append({
            "role": "user",
            "content": (
                "请根据以上真实工具返回，用两到四句中文说明本轮实际修改了什么、"
                "哪些内容没有修改，并提出一个基于当前立项数据的后续问题。"
                "不得声称未成功的写入已经保存。"
            ),
        })
        try:
            summary = await _complete_tool_turn(
                messages=messages,
                tools=[],
                model=model,
                temperature=0.2,
                max_tokens=None,
                timeout=0,
            )
            final_reply = str(summary.get("content") or "").strip()
        except Exception:
            final_reply = ""

    if not write_results and final_reply and any(word in final_reply for word in ("已保存", "已写入", "已修改", "已更新")):
        failures = [
            str(item.get("detail") or "工具未完成写入")
            for item in tool_results
            if item.get("status") not in {"ok", "running"}
        ]
        reason = failures[-1] if failures else "本轮只读取了数据，没有执行写入"
        final_reply = f"我读取了当前立项数据，但本轮没有保存任何修改：{reason}。这句话要作为创意核心、世界观、角色还是大纲内容？你确认后我会立即写入。"

    if not final_reply:
        if write_results:
            details = [str(item.get("detail") or item.get("tool") or "已更新立项数据") for item in write_results[:3]]
            final_reply = f"本轮已完成：{'；'.join(details)}。接下来你最想补充哪一部分？"
        elif tool_results:
            failures = [
                str(item.get("detail") or "工具未完成写入")
                for item in tool_results
                if item.get("status") not in {"ok", "running"}
            ]
            reason = failures[-1] if failures else "本轮只读取了数据，没有执行写入"
            final_reply = f"我读取了当前立项数据，但本轮没有保存任何修改：{reason}。请再说明这句话要作为创意核心、世界观、角色还是大纲内容，我会立即写入。"
        else:
            final_reply = "我已读取当前立项上下文，但这一轮没有执行数据修改。你希望先补充创意核心、世界观、角色还是大纲？"

    active_run = None
    for item in reversed(tool_results):
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        candidate = data.get("run") if isinstance(data.get("run"), dict) else None
        if candidate:
            active_run = candidate
            break
    return {
        "reply": final_reply,
        "tool_results": tool_results,
        "write_count": len(write_results),
        "run": active_run,
    }


__all__ = ["CREATION_AGENT_TOOLS", "run_creation_agent"]

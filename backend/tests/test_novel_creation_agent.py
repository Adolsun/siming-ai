from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

from app.services.novel_creation_agent import _parse_cli_tool_bridge, run_creation_agent
from tests.test_novel_creation_workspace_v2 import _db, _ready_session


def test_creation_agent_lets_model_read_then_call_any_creation_tool():
    db = _db()
    session = _ready_session(db)
    completion = AsyncMock(side_effect=[
        {
            "content": "",
            "tool_calls": [{
                "id": "call-read",
                "type": "function",
                "function": {"name": "get_creation_snapshot", "arguments": "{}"},
            }],
        },
        {
            "content": "",
            "tool_calls": [{
                "id": "call-generate",
                "type": "function",
                "function": {
                    "name": "generate_creation_artifact",
                    "arguments": json.dumps({
                        "artifact": "world_style",
                        "entity_type": "worldbuilding",
                        "instruction": "新增用户描述的两条修炼规则",
                    }, ensure_ascii=False),
                },
            }],
        },
        {"content": "已读取当前设定，并开始新增修炼规则。", "tool_calls": []},
    ])
    executor = AsyncMock(side_effect=[
        {"tool": "get_creation_snapshot", "status": "ok", "data": {"revision": session.revision}},
        {"tool": "generate_creation_artifact", "status": "ok", "data": {"run": {"id": "run-1", "status": "running"}}},
    ])

    with patch(
        "app.services.novel_creation_agent.LLMGateway.stream_chat_completion_with_tools",
        new=completion,
    ), patch(
        "app.services.novel_creation_agent.execute_workspace_action",
        new=executor,
    ):
        result = asyncio.run(run_creation_agent(
            db,
            session=session,
            message="在世界观里加入两条修炼规则",
            model="openai:test",
            history=[{"role": "user", "content": "这是仙侠小说"}],
        ))

    read_action = executor.call_args_list[0].args[2]
    write_action = executor.call_args_list[1].args[2]
    assert read_action["tool"] == "get_creation_snapshot"
    assert read_action["arguments"]["session_id"] == session.id
    assert write_action["tool"] == "generate_creation_artifact"
    assert write_action["arguments"]["session_id"] == session.id
    assert write_action["arguments"]["expected_revision"] == session.revision
    assert write_action["arguments"]["model"] == "openai:test"
    assert result["run"]["id"] == "run-1"
    assert "开始新增" in result["reply"]


def test_creation_agent_rejects_non_creation_tools_even_if_model_requests_one():
    db = _db()
    session = _ready_session(db)
    completion = AsyncMock(side_effect=[
        {
            "content": "",
            "tool_calls": [{
                "id": "call-invalid",
                "type": "function",
                "function": {"name": "delete_project", "arguments": "{}"},
            }],
        },
        {"content": "没有执行越权操作。", "tool_calls": []},
    ])

    with patch(
        "app.services.novel_creation_agent.LLMGateway.stream_chat_completion_with_tools",
        new=completion,
    ):
        result = asyncio.run(run_creation_agent(
            db, session=session, message="继续处理立项", model="openai:test",
        ))

    assert result["tool_results"][0]["status"] == "skipped"
    assert "不属于立项会话" in result["tool_results"][0]["detail"]


def test_creation_agent_gives_text_only_cli_a_validated_write_tool_bridge():
    db = _db()
    session = _ready_session(db)
    completion = AsyncMock(side_effect=[
        {
            "content": json.dumps({
                "reply": "我会把这项要求写入文风与世界观。",
                "actions": [{
                    "tool": "patch_creation_artifact",
                    "arguments": {
                        "artifact": "world_style",
                        "changes": [{
                            "path": "/world_tone",
                            "action": "replace",
                            "value": "厚重史诗",
                        }],
                    },
                }],
            }, ensure_ascii=False),
            "tool_calls": [],
        },
        {
            "content": json.dumps({
                "reply": "已把文风基调更新为厚重史诗。接下来要补充叙事视角吗？",
                "actions": [],
            }, ensure_ascii=False),
            "tool_calls": [],
        },
    ])
    executor = AsyncMock(return_value={
        "tool": "patch_creation_artifact",
        "status": "ok",
        "detail": "文风与世界观已更新",
    })

    with patch(
        "app.services.novel_creation_agent.LLMGateway.supports_tool_calling",
        return_value=False,
    ), patch(
        "app.services.novel_creation_agent.LLMGateway.stream_chat_completion_with_tools",
        new=completion,
    ), patch(
        "app.services.novel_creation_agent.execute_workspace_action",
        new=executor,
    ):
        result = asyncio.run(run_creation_agent(
            db,
            session=session,
            message="生成文风与世界观，基调要厚重史诗",
            model="opencode_cli:opencode/deepseek-v4-flash-free",
        ))

    first_request = completion.call_args_list[0].kwargs
    assert first_request["tools"] == []
    assert "patch_creation_artifact" in first_request["messages"][1]["content"]
    action = executor.call_args.args[2]
    assert action["tool"] == "patch_creation_artifact"
    assert action["arguments"]["session_id"] == session.id
    assert action["arguments"]["expected_revision"] == session.revision
    assert result["write_count"] == 1
    assert "厚重史诗" in result["reply"]


def test_cli_tool_bridge_repairs_missing_nested_closer_in_model_json():
    malformed = (
        '{"reply":"开始生成文风与世界观",'
        '"actions":[{"tool":"generate_creation_artifact",'
        '"arguments":{"artifact":"world_style","instruction":"生成完整世界观"}]}'
    )

    recognized, reply, calls = _parse_cli_tool_bridge(malformed)

    assert recognized is True
    assert reply == "开始生成文风与世界观"
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "generate_creation_artifact"
    assert json.loads(calls[0]["function"]["arguments"])["artifact"] == "world_style"

import asyncio
from unittest.mock import AsyncMock, patch

from app.services.agent.local_cli_routing import (
    _strict_json_object,
    classify_local_cli_workspace_request,
)


def test_strict_router_json_accepts_fenced_object_without_intent_regex() -> None:
    assert _strict_json_object('```json\n{"route":"chapter_write"}\n```') == {
        "route": "chapter_write"
    }


def test_selected_cli_decides_chapter_route_and_target() -> None:
    with patch(
        "app.services.agent.local_cli_routing.LLMGateway.chat_completion",
        new=AsyncMock(return_value={
            "content": '{"route":"chapter_write","chapter_number":1,'
            '"outline_query":"开头那一章","reason":"需要创建正文"}'
        }),
    ) as completion, patch(
        "app.services.agent.local_cli_routing.LLMGateway.local_cli_extra_body",
        return_value={"local_cli_isolated": True},
    ):
        result = asyncio.run(
            classify_local_cli_workspace_request(
                model="opencode_cli:opencode/deepseek-v4-flash-free",
                message="从故事开头正式落笔吧",
            )
        )

    assert result == {
        "route": "chapter_write",
        "chapter_number": 1,
        "outline_query": "开头那一章",
        "reason": "需要创建正文",
    }
    prompt = completion.call_args.kwargs["messages"]
    assert "不要依赖固定关键词" in prompt[0]["content"]
    assert "从故事开头正式落笔吧" in prompt[1]["content"]


def test_invalid_cli_route_falls_back_to_general() -> None:
    with patch(
        "app.services.agent.local_cli_routing.LLMGateway.chat_completion",
        new=AsyncMock(return_value={"content": '{"route":"unknown"}'}),
    ), patch(
        "app.services.agent.local_cli_routing.LLMGateway.local_cli_extra_body",
        return_value={},
    ):
        result = asyncio.run(
            classify_local_cli_workspace_request(
                model="claude_cli:claude-code",
                message="聊聊角色",
            )
        )

    assert result["route"] == "general"

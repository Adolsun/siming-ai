from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.deepseek_adapter import DeepSeekAdapter
from app.core.exceptions import LLMError
from app.services.agent_tool_stream import collect_tool_turn
from app.services.creation_agent_reply import creation_receipt_reply, creation_reply_error
from app.services.novel_creation_agent import run_creation_agent
from app.services.workspace.executor import execute_workspace_action
from tests.test_novel_creation_agent import _stream_completion, _test_context_preparer
from tests.test_novel_creation_workspace_v2 import _db, _ready_session
from tests.tool_budget_helpers import request_budget

DSML = (
    '<｜｜DSML｜｜ calls><｜｜DSML｜｜ invoke name="get_creation_entity">'
    '<｜｜DSML｜｜ parameter name="entity_id" string="true">entity-1'
    '</｜｜DSML｜｜ parameter></｜｜DSML｜｜ invoke></｜｜DSML｜｜ calls>'
)
REPLY = "题材已更新为玄幻。主角有什么目标？"


def _call(name: str, arguments: dict) -> dict:
    return {"content": "", "tool_calls": [{
        "id": f"call-{name}", "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }]}


def _run_after_write(*summaries: dict | BaseException) -> tuple[dict, list[dict], MagicMock]:
    db = _db()
    session = _ready_session(db)
    baseline = int(session.revision)
    contexts: list[dict] = []
    responses = iter([
        _call("set_tool_categories", {"enabled_categories": ["creation_data"]}),
        _call("get_creation_snapshot", {}),
        _call("patch_creation_session", {"changes": {"genre": "玄幻"}}),
        *summaries,
    ])

    def response(**_kwargs):
        item = next(responses)
        if isinstance(item, BaseException):
            raise item
        return item

    completion = _stream_completion(response)
    executor = AsyncMock(wraps=execute_workspace_action)
    try:
        with (
            patch("app.services.novel_creation_agent.LLMGateway.stream_chat_completion_with_tools", new=completion),
            patch("app.services.creation_agent_execution.execute_workspace_action", new=executor),
        ):
            result = asyncio.run(run_creation_agent(
                db, session=session, message="把题材设为玄幻", model="openai:test",
                provider_request_budget=request_budget,
                prepare_model_messages=_test_context_preparer("把题材设为玄幻", captured=contexts),
            ))
        db.refresh(session)
        assert session.revision == baseline + 1
        assert result["write_count"] == 1
        assert [call.args[2]["tool"] for call in executor.await_args_list] == [
            "get_creation_snapshot", "patch_creation_session",
        ]
        assert any(receipt["write_committed"] for receipt in result["_turn_trace"]["execution_receipts"])
        assert result["_turn_trace"]["pending_tool_transactions"] == []
        return result, contexts, completion
    finally:
        db.close()


def test_successful_write_enters_explicit_summary_without_replanning():
    result, contexts, completion = _run_after_write({"content": REPLY})

    assert result["reply"] == REPLY
    assert completion.call_count == 4
    assert "工具已关闭" in contexts[-1]["extra_runtime_instruction"]
    assert "[SERVER_RUNTIME_INSTRUCTION]" in contexts[-1]["messages"][0]["content"]
    assert contexts[-1]["current_tools"] == ()
    assert result["_turn_trace"]["prompt_metrics"][-1]["phase"] == "summary"


@pytest.mark.parametrize("bad_summary", [
    {"content": DSML},
    {"content": "已经保存。\n" + DSML},
    {"content": DSML.replace("｜｜", "｜")},
    {"content": DSML.replace("｜", "|")},
    {"content": DSML.replace("<", "&lt;")},
    {"content": "<｜｜DSML  "},
    {"content": ""},
    _call("patch_creation_session", {"changes": {"genre": "科幻"}}),
])
def test_invalid_summary_is_repaired_without_replaying_any_tool(bad_summary):
    result, contexts, completion = _run_after_write(bad_summary, {"content": REPLY})

    assert result["reply"] == REPLY
    assert completion.call_count == 5
    assert all(context["current_tools"] == () for context in contexts[3:])
    visible = "".join(
        event["data"].get("delta", "") for event in result["_turn_trace"]["progress_events"]
        if event["type"] == "reply_delta"
    )
    assert visible == REPLY
    assert "DSML" not in json.dumps(result["_turn_trace"]["messages"], ensure_ascii=False)


def test_repeated_invalid_summary_stops_with_explicit_receipt_and_preserves_write():
    result, contexts, completion = _run_after_write({"content": DSML}, {"content": DSML})

    assert completion.call_count == 5
    assert "DSML" not in result["reply"]
    assert "总结" in result["reply"]
    assert "已保存" in result["reply"]
    assert result["_turn_trace"]["outcome"]["reply_status"] == "receipt_only"
    assert all(context["current_tools"] == () for context in contexts[3:])


def test_summary_transport_failure_does_not_undo_or_replay_a_committed_write():
    result, _, completion = _run_after_write(LLMError("response disconnected"))

    assert completion.call_count == 4
    assert "已保存" in result["reply"]
    assert result["_turn_trace"]["outcome"]["reply_diagnostics"] == [
        {"reason": "summary_request_failed", "attempt": 1},
    ]


def test_receipt_for_a_started_task_does_not_claim_its_contents_are_complete():
    receipt = {"tool": "generate_creation_artifact", "status": "running", "detail": ""}
    reply = creation_receipt_reply([receipt], [receipt], tool_mode="native")

    assert "任务已启动" in reply
    assert "已保存" not in reply
    assert "已完成" not in reply


def test_created_project_closes_receipts_without_requesting_another_model_step():
    db = _db()
    session = _ready_session(db)
    completion = _stream_completion([
        _call("set_tool_categories", {"enabled_categories": ["creation_data", "creation_flow"]}),
        _call("get_creation_snapshot", {}),
        _call("finalize_creation_session", {}),
    ])
    try:
        with patch("app.services.novel_creation_agent.LLMGateway.stream_chat_completion_with_tools", new=completion):
            result = asyncio.run(run_creation_agent(
                db, session=session, message="把这个立项创建为正式作品", model="openai:test",
                provider_request_budget=request_budget,
                prepare_model_messages=_test_context_preparer("把这个立项创建为正式作品"),
            ))
        assert completion.call_count == 3
        assert result["created_project_id"]
        assert "正式作品已创建" in result["reply"]
        assert result["_turn_trace"]["pending_tool_transactions"] == []
        assert result["_turn_trace"]["outcome"]["reply_status"] == "project_created"
    finally:
        db.close()


def test_deepseek_api_tool_free_stream_preserves_content_for_validation_not_execution():
    async def chunks():
        for start in range(0, len(DSML), 7):
            yield SimpleNamespace(choices=[SimpleNamespace(
                delta=SimpleNamespace(content=DSML[start:start + 7]), finish_reason=None,
            )])
        yield SimpleNamespace(choices=[SimpleNamespace(delta=None, finish_reason="stop")])

    adapter = DeepSeekAdapter(api_key="test-placeholder")
    client = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=chunks())
    adapter._get_client = MagicMock(return_value=client)
    response = asyncio.run(collect_tool_turn(
        adapter, messages=[{"role": "user", "content": "总结已完成的写入"}],
        model="deepseek-flash", tools=[], tool_choice=None,
    ))

    assert response["content"] == DSML
    assert response["tool_calls"] == []
    assert creation_reply_error(response["content"], response["tool_calls"]) == "tool_protocol_text"
    sent = client.chat.completions.create.await_args.kwargs
    assert sent["model"] == "deepseek-flash"
    assert "tools" not in sent
    assert "tool_choice" not in sent

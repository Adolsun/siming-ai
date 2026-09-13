"""Shared PC/mobile incident replay and hard rejection boundaries; no live model."""
import asyncio
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.conversation_context import ConversationContextError
from app.services.workspace import assistant_native_turn as native_module
from app.services.workspace.assistant_native_turn import WorkspaceNativeTurn
from app.services.workspace.assistant_turn_state import WorkspaceAssistantTurnState, WorkspaceTurnSuperseded
from app.services.workspace.native_tool_batch import (
    MAX_NATIVE_TOOL_NAME_REJECTIONS,
    NativeToolBatchNotOpen,
    NativeToolBatchValidationError,
    validate_workspace_native_tool_batch,
)
from app.services.workspace.registry import registry
from tests.tool_budget_helpers import request_budget


@pytest.fixture
def incident():
    return json.loads((Path(__file__).resolve().parents[2] /
                       "contracts/fixtures/native-tool-name-rejection.json").read_text(encoding="utf-8"))


def validate(calls, offered):
    return validate_workspace_native_tool_batch(calls, allowed_tool_names=set(offered),
                                               resolve_tool=registry.get, require_initial_controller=False)


def test_incident_receipts_match_mobile_contract(incident):
    calls = incident["assistant"]["tool_calls"]
    with pytest.raises(NativeToolBatchNotOpen) as caught:
        validate(calls, incident["offered_tools"])
    error = caught.value
    assert error.calls == calls
    assert MAX_NATIVE_TOOL_NAME_REJECTIONS == incident["max_rejections"]
    error.recovery_fits = True
    for call in calls:
        assert error.model_error_result(call["function"]["name"])["data"] == incident["denial_data"]


def test_registered_but_closed_tool_does_not_gain_permission(incident):
    calls = [{"id": "closed", "function": {"name": "list_cataloging_jobs", "arguments": "{}"}}]
    assert registry.get("list_cataloging_jobs") is not None
    with pytest.raises(NativeToolBatchNotOpen) as caught:
        validate(calls, incident["offered_tools"])
    assert "list_cataloging_jobs" not in caught.value.allowed_tool_names


@pytest.mark.parametrize("invalid", ["missing_id", "duplicate_id", "empty_arguments", "invalid_json", "array_arguments"])
def test_malformed_batch_cannot_enter_name_recovery(incident, invalid):
    calls = incident["assistant"]["tool_calls"]
    if invalid == "missing_id":
        calls[1]["id"] = ""
    elif invalid == "duplicate_id":
        calls[1]["id"] = calls[0]["id"]
    else:
        calls[1]["function"]["arguments"] = {
            "empty_arguments": "", "invalid_json": "{bad", "array_arguments": "[]",
        }[invalid]
    with pytest.raises(NativeToolBatchValidationError) as caught:
        validate(calls, incident["offered_tools"])
    assert not isinstance(caught.value, NativeToolBatchNotOpen)


@pytest.mark.parametrize("capacity, superseded", [(250_000, False), (100, False), (250_000, True)])
def test_exact_provider_state_budget_and_supersession_are_preserved(incident, monkeypatch, capacity, superseded):
    original = incident["assistant"]
    persisted = []

    def start(*_args, **kwargs):
        step = SimpleNamespace(id=f"step-{len(persisted)}", request=kwargs["request"])
        persisted.append(step)
        return step

    def finish(_db, step, **kwargs):
        step.result = kwargs["result"]

    monkeypatch.setattr(native_module, "start_run_step", start)
    monkeypatch.setattr(native_module, "finish_run_step", finish)

    async def stream(**_kwargs):
        for index, call in enumerate(original["tool_calls"]):
            yield {"type": "tool_call_delta", "index": index, "id": call["id"],
                   "name": call["function"]["name"], "arguments_delta": call["function"]["arguments"]}
        yield {"type": "done", "reasoning_content": original["reasoning_content"],
               "provider_state": original["provider_state"]}
        if superseded:
            state.require_current_run = Mock(side_effect=WorkspaceTurnSuperseded("new author turn"))

    state = WorkspaceAssistantTurnState(
        db=None, project_id="fixture", payload=SimpleNamespace(model="test:fixture", temperature=0.3, max_tokens=4000),
        selected_provider="test", supports_function_calling=True, local_cli_selected=False,
        local_cli_mcp_enabled=False, encode_event=json.dumps, execute_action=AsyncMock(),
        prepare_context=None, turn_telemetry=Mock(), category_selected=True,
        assistant_run=SimpleNamespace(id="run"), assistant_message=SimpleNamespace(id="message"),
        request_budget=request_budget(capacity),
    )
    turn = WorkspaceNativeTurn(state, SimpleNamespace(stream_chat_completion_with_tools=stream), registry)

    async def run():
        return [event async for event in turn.run(
            messages=[{"role": "user", "content": "继续写下一章"}], iteration=2,
            tool_schemas=[{"function": {"name": name}} for name in incident["offered_tools"]], tool_choice="auto",
        )]

    if superseded:
        with pytest.raises(WorkspaceTurnSuperseded):
            asyncio.run(run())
        assert not persisted
        assert not state.tool_transactions
    else:
        if capacity < 1000:
            with pytest.raises(ConversationContextError):
                asyncio.run(run())
        else:
            asyncio.run(run())
            assert state.loop_action == "continue"
        assert len(persisted) == 2
        messages = state.tool_transactions[0].native_messages()
        assert messages[0] == original
        assert [message["tool_call_id"] for message in messages[1:]] == [call["id"] for call in original["tool_calls"]]
        expected_data = copy.deepcopy(incident["denial_data"])
        expected_data["retryable"] = capacity >= 1000
        for message in messages[1:]:
            assert json.loads(message["content"])["data"] == expected_data
    state.execute_action.assert_not_awaited()

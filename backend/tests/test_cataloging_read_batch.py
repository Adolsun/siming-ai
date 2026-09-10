"""Cataloging reads must not terminate preparation for a new chapter."""
from types import SimpleNamespace
import pytest
from app.services.workspace.registry import registry
from app.services.workspace.native_tool_batch import validate_workspace_native_tool_batch, NativeToolBatchValidationError
from app.services.workspace.assistant_native_turn import WorkspaceNativeTurn


def call(name, i):
    return {"id": f"call-{i}", "function": {"name": name, "arguments": "{}"}}


@pytest.mark.parametrize("name", ["list_cataloging_jobs", "get_cataloging_job", "get_cataloging_control_state", "list_cataloging_facts", "list_cataloging_candidates"])
def test_cataloging_read_can_share_preparation_batch_and_continue(name):
    names = [name, "list_chapters", "search_outline_tree"]
    batch = validate_workspace_native_tool_batch(
        [call(n, i) for i, n in enumerate(names)], allowed_tool_names=set(names),
        resolve_tool=registry.get, require_initial_controller=False,
    )
    assert batch.names == tuple(names)
    state = SimpleNamespace(turn_terminal_result=None, applied_actions=[])
    turn = WorkspaceNativeTurn(state, None, registry)
    assert turn._record_terminal(name, {"tool": name, "status": "ok"}, False) == ""
    assert state.turn_terminal_result is None


@pytest.mark.parametrize("name", ["start_cataloging_job", "pause_cataloging_job", "apply_pending_cataloging"])
def test_cataloging_mutation_still_requires_singleton_and_stops(name):
    with pytest.raises(NativeToolBatchValidationError):
        validate_workspace_native_tool_batch([call(name, 0), call("list_chapters", 1)],
            allowed_tool_names={name, "list_chapters"}, resolve_tool=registry.get,
            require_initial_controller=False)
    state = SimpleNamespace(turn_terminal_result=None, applied_actions=[])
    turn = WorkspaceNativeTurn(state, None, registry)
    assert turn._record_terminal(name, {"tool": name, "status": "ok"}, True)


def test_explicit_cataloging_block_still_ends_writing_turn():
    state = SimpleNamespace(turn_terminal_result=None, applied_actions=[])
    turn = WorkspaceNativeTurn(state, None, registry)
    result = {"tool": "list_cataloging_jobs", "turn_terminal": True, "turn_directive": "blocked_on_cataloging"}
    assert turn._record_terminal("list_cataloging_jobs", result, False) == "terminal_tool"

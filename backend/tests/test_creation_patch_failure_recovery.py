"""Offline reproduction of stringified patch arrays and actionable failure reports."""
import asyncio
from app.mcp.adapter import execute_tool
from app.services.creation_agent_native_protocol import safe_creation_tool_result
from app.services.novel_creation_agent import _direct_mcp_boundary_reply
from app.services.tool_category_state import create_tool_category_state, remove_tool_category_state, record_creation_turn_write_result
from tests.test_creation_session_mcp import _payload
from tests.test_novel_creation_workspace_v2 import _db, _ready_session


def test_mcp_stringified_patch_fails_without_writes_then_native_array_succeeds():
    db = _db()
    session = _ready_session(db)
    revision = session.revision
    base = {"session_id": session.id, "artifact": "constraints", "expected_revision": revision}
    async def invoke(changes):
        return await execute_tool(db, "", "patch_creation_artifact", {**base, "changes": changes},
            permission_pack="creation_session", creation_session_id=session.id)
    try:
        invalid = asyncio.run(invoke('[{"path":"/brief","action":"set","value":"test"}]'))
        assert invalid.is_error
        failure = _payload(invalid)
        assert failure["data"]["path"] == "$.changes"
        assert failure["data"]["rule"] == "list_type"
        assert "只改字符串内容或转义不能解决" in failure["detail"]
        assert safe_creation_tool_result("patch_creation_artifact", failure) == failure
        db.expire_all()
        assert session.revision == revision
        valid = asyncio.run(invoke([{"path": "/brief", "action": "set", "value": "test"}]))
        assert not valid.is_error
        db.expire_all()
        assert session.revision == revision + 1
    finally:
        db.close()


def test_three_failed_attempts_report_parameter_error_not_author_data_problem():
    state_file = create_tool_category_state()
    failure = {"tool": "patch_creation_artifact", "status": "error", "detail": "DO_NOT_REFLECT_RAW",
        "data": {"reason": "native_tool_contract_invalid", "failure_class": "invalid_tool_arguments", "path": "$.changes", "rule": "list_type"}}
    try:
        assert record_creation_turn_write_result(state_file, "patch_creation_artifact", failure) is None
        assert record_creation_turn_write_result(state_file, "patch_creation_artifact", failure) is None
        event = record_creation_turn_write_result(state_file, "patch_creation_artifact", failure)
        assert event["data"]["failed_writes"] == 3
        reply = _direct_mcp_boundary_reply(event)
        assert "$.changes" in reply and "JSON 数组" in reply
        assert "检查当前资料结构" not in reply
        assert "DO_NOT_REFLECT_RAW" not in reply
        assert "本轮没有成功写入新资料" in reply
    finally:
        remove_tool_category_state(state_file)

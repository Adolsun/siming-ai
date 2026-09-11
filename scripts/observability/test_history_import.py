import json
import sqlite3

from import_creation_history import build_trace, read_turn


def test_history_import_is_read_only_partial_and_does_not_invent_usage_or_latency(
    tmp_path,
):
    path = tmp_path / "test.db"
    turn = {
        "model": "test-model",
        "session_id": "session-1",
        "messages": [
            {"role": "user", "content": "测试"},
            {
                "role": "assistant",
                "reasoning_content": "provider-returned",
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "generate_creation_artifact",
                            "arguments": '{"context_entity_ids":["old"]}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "content": '{"status":"error","detail":"工具执行失败"}',
            },
            {"role": "assistant", "content": "未写入"},
        ],
        "prompt_metrics": [
            {"usage_reported": True, "prompt_tokens": 42},
            {"usage_reported": False},
        ],
        "outcome": {"write_count": 0},
    }
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE system_assistant_messages (id TEXT, payload_json TEXT, content TEXT, created_at TEXT, updated_at TEXT)"
        )
        db.execute(
            "INSERT INTO system_assistant_messages VALUES (?, ?, ?, ?, ?)",
            (
                "message-1",
                json.dumps({"creation_agent_turn": turn}),
                "未写入",
                "2026-09-11 05:00:00",
                "2026-09-11 05:00:10",
            ),
        )
    before = path.read_bytes()
    request, summary = build_trace(*read_turn(path, "message-1"), "test-history")
    assert path.read_bytes() == before
    assert summary["reported_input_tokens"] == 42
    assert summary["failed_tools"] == 1
    assert summary["full_api_request_available"] is False
    (resource,) = request.resource_spans
    assert any(
        a.key == "openinference.project.name" and a.value.string_value == "test-history"
        for a in resource.resource.attributes
    )
    spans = resource.scope_spans[0].spans
    assert spans[0].end_time_unix_nano > spans[0].start_time_unix_nano
    assert all(s.start_time_unix_nano == s.end_time_unix_nano for s in spans[1:])
    attrs = {a.key: a.value for a in spans[1].attributes}
    assert "recorded_current_turn_prefix" in attrs["input.value"].string_value
    assert "provider-returned" in attrs["output.value"].string_value
    assert "llm.token_count.completion" not in attrs
    assert "llm.input_messages.0.message.content" not in attrs
    assert (
        request.SerializeToString()
        == build_trace(*read_turn(path, "message-1"), "test-history")[
            0
        ].SerializeToString()
    )

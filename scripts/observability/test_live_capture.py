"""No paid API calls: verify tracing does not change requests or streaming bytes."""

import asyncio
import gzip
import json

import httpx
from live_capture import (
    TraceRequests,
    configure,
    instrument_httpx,
    instrument_workspace,
)
from openai import AsyncOpenAI
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def recorder():
    sink = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(sink))
    return sink, instrument_httpx(provider.get_tracer("test"))


def test_deepseek_adapter_actual_body_reasoning_tools_and_gzip_stream():
    from app.ai.deepseek_adapter import DeepSeekAdapter

    received = []
    chunks = [
        {
            "choices": [
                {"index": 0, "delta": {"reasoning_content": "测试提供商返回的思考字段"}}
            ]
        },
        {
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-test",
                                "type": "function",
                                "function": {
                                    "name": "get_creation_entity",
                                    "arguments": '{"entity_id":"entity-1"}',
                                },
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ]
        },
        {
            "choices": [],
            "usage": {"prompt_tokens": 42, "completion_tokens": 8, "total_tokens": 50},
        },
    ]
    body = (
        "\n\n".join(
            "data: " + json.dumps(chunk, ensure_ascii=False) for chunk in chunks
        )
        + "\n\ndata: [DONE]\n\n"
    ).encode()
    compressed = gzip.compress(body)

    class Streaming(httpx.AsyncByteStream):
        async def __aiter__(self):
            for offset in range(0, len(compressed), 17):
                yield compressed[offset : offset + 17]

    def handler(request):
        received.append(request)
        return httpx.Response(
            200,
            headers={"Content-Type": "text/event-stream", "Content-Encoding": "gzip"},
            stream=Streaming(),
        )

    async def run():
        client = AsyncOpenAI(
            api_key="test-secret-must-not-be-captured",
            base_url="https://api.deepseek.invalid/v1",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            max_retries=0,
        )
        adapter = DeepSeekAdapter(api_key="test-secret-must-not-be-captured")
        adapter._get_client = lambda: client
        try:
            return [
                event
                async for event in adapter.stream_chat_completion_with_tools(
                    [
                        {"role": "system", "content": "独立测试上下文"},
                        {"role": "user", "content": "读取实体"},
                    ],
                    model="deepseek-flash",
                    extra_body={"thinking": {"type": "enabled"}},
                    tools=[
                        {
                            "type": "function",
                            "function": {
                                "name": "get_creation_entity",
                                "parameters": {"type": "object"},
                            },
                        }
                    ],
                )
            ]
        finally:
            await client.close()

    sink, restore = recorder()
    try:
        events = asyncio.run(run())
    finally:
        restore()
    assert len(received) == 1
    assert str(received[0].url) == "https://api.deepseek.invalid/v1/chat/completions"
    assert any(e.get("type") == "reasoning_delta" for e in events)
    (span,) = sink.get_finished_spans()
    attrs = span.attributes
    assert json.loads(attrs["input.value"]) == json.loads(received[0].content)
    assert json.loads(attrs["input.value"])["thinking"] == {"type": "enabled"}
    assert json.loads(attrs["output.value"])["provider_response_records"] == chunks
    assert attrs["llm.token_count.prompt"] == 42
    assert attrs["siming.response_state"] == "complete"
    assert attrs["siming.response_decoding"] == "decoded"
    assert "test-secret-must-not-be-captured" not in str(attrs)


def test_error_response_and_non_streaming_data_are_preserved():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    400, json={"error": {"message": "invalid request"}}
                ),
            )
        ) as client:
            response = await client.post(
                "https://example.invalid/chat/completions",
                json={"model": "test", "messages": [], "tools": None},
            )
            assert response.status_code == 400
            assert response.json() == {"error": {"message": "invalid request"}}

    sink, restore = recorder()
    try:
        asyncio.run(run())
    finally:
        restore()
    (span,) = sink.get_finished_spans()
    assert span.status.is_ok is False
    assert span.attributes["http.response.status_code"] == 400


def test_cancelled_stream_finishes_trace_without_swallowing_cancellation():
    class Cancelled(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices": []}\n\n'
            raise asyncio.CancelledError()

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, stream=Cancelled()),
            )
        ) as client:
            try:
                async with client.stream(
                    "POST",
                    "https://example.invalid/chat/completions",
                    json={"model": "test", "messages": []},
                ) as response:
                    await response.aread()
            except asyncio.CancelledError:
                return
            raise AssertionError("Cancellation was swallowed")

    sink, restore = recorder()
    try:
        asyncio.run(run())
    finally:
        restore()
    (span,) = sink.get_finished_spans()
    assert span.attributes["siming.response_state"] == "CancelledError"


def test_collector_rejects_non_local_export():
    try:
        configure("https://external.invalid/v1/traces")
    except ValueError:
        return
    raise AssertionError("Diagnostic data must stay local")


def test_in_process_request_and_real_tool_keep_result_and_trace_parent(monkeypatch):
    from app.services import workspace
    from app.services.workspace.tools import novel_creation_v2
    from fastapi import FastAPI
    from tests.test_novel_creation_workspace_v2 import _db, _ready_session

    sink = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(sink))
    tracer = provider.get_tracer("asgi-test")
    restore = instrument_workspace(tracer)
    monkeypatch.setattr(
        novel_creation_v2,
        "_resolve_creation_model",
        lambda *a, **k: "deepseek:deepseek-flash",
    )
    try:
        with _db() as db:
            session = _ready_session(db)
            before = session.revision
            app = FastAPI()

            @app.get("/trace-test")
            async def request():
                return await workspace.execute_workspace_action(
                    db,
                    "",
                    {
                        "tool": "generate_creation_artifact",
                        "arguments": {
                            "session_id": session.id,
                            "artifact": "characters",
                            "entity_type": "character",
                            "context_entity_ids": ["unavailable-entity"],
                            "expected_revision": session.revision,
                        },
                    },
                )

            observed = TraceRequests(app)
            observed.tracer = tracer

            async def run():
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=observed), base_url="http://test"
                ) as client:
                    response = await client.get("/trace-test")
                    assert response.status_code == 200
                    return response.json()

            result = asyncio.run(run())
            assert result["data"]["reason"] == "creation_context_entity_unavailable"
            assert session.revision == before
    finally:
        restore()
    tool_span, request_span = sink.get_finished_spans()
    assert tool_span.parent.span_id == request_span.context.span_id
    assert json.loads(tool_span.attributes["output.value"]) == result
    assert tool_span.status.is_ok is False

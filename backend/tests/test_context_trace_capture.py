"""Offline regression coverage for native diagnostics, isolation and transport fidelity."""

import asyncio
import functools
import gzip
import json

import httpx
import pytest

from app.modules.operations.application.trace_capture import (
    Span,
    configure_trace_sink,
    record_payload,
    request_identity,
    trace_scope,
)
from app.modules.operations.domain.context_trace import TraceScope
from app.modules.operations.infrastructure.http_trace import ObservedHttpClient
from app.modules.operations.infrastructure.trace_queries import TraceQueries
from app.modules.operations.infrastructure.trace_store import TraceStore


def run_async(function):
    @functools.wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


@pytest.fixture
def store(tmp_path):
    value = TraceStore(tmp_path / "diagnostics.sqlite3")
    value.set_policy("local", "full", None)
    configure_trace_sink(value)
    yield value
    configure_trace_sink(None)
    value.close()


def all_events(store, trace):
    store.flush()
    return store.events("local", trace.id, limit=200)


def content(store, trace, event):
    return json.loads(store.payload("local", trace.id, event["event_id"])["content"])


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        for item in self.chunks:
            self.reads += 1
            yield item

    async def aclose(self):
        self.closed = True


@run_async
async def test_wire_stream_is_unchanged_and_credentials_never_persist(store):
    raw = b'data: {"choices":[{"delta":{"content":"hello"}}]}\n\ndata: [DONE]\n\n'
    compressed = gzip.compress(raw)
    chunks = Chunks([compressed[:13], compressed[13:]])
    received = []

    async def handle(request):
        received.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream", "content-encoding": "gzip"},
            stream=chunks,
        )

    async with ObservedHttpClient(transport=httpx.MockTransport(handle)) as client:
        with trace_scope(TraceScope(kind="creation_session", id="session-a")) as trace:
            with Span("model"):
                async with client.stream(
                    "POST",
                    "https://provider.invalid/v1/chat/completions?key=secret-query",
                    headers={"Authorization": "Bearer secret-api"},
                    json={
                        "messages": [{"role": "user", "content": "secret-api"}],
                        "api_key": "secret-body",
                    },
                ) as response:
                    assert b"".join([part async for part in response.aiter_bytes()]) == raw
    events = all_events(store, trace)
    assert str(received[0].url).endswith("?key=secret-query")
    assert received[0].headers["authorization"] == "Bearer secret-api"
    assert chunks.reads == 2 and chunks.closed
    payloads = [e for e in events if e["event_type"] == "payload"]
    assert len(payloads) == 2
    sent = content(store, trace, payloads[0])
    assert sent["api_key"] == "[REDACTED]"
    assert sent["messages"][0]["content"] == "[REDACTED]"
    assert content(store, trace, payloads[1])[-1] == "[DONE]"
    assert "?" not in payloads[0]["data"]["endpoint"]
    assert b"secret-api" not in store.path.read_bytes()
    assert b"secret-body" not in store.path.read_bytes()
    assert b"secret-query" not in store.path.read_bytes()


@run_async
async def test_redirects_are_separate_physical_attempts(store):
    def handle(request):
        if request.url.path == "/start":
            return httpx.Response(307, headers={"location": "/middle"}, json={})
        if request.url.path == "/middle":
            return httpx.Response(307, headers={"location": "/finish"}, json={})
        return httpx.Response(200, json={"usage": {"input_tokens": 7}})

    async with ObservedHttpClient(
        transport=httpx.MockTransport(handle), follow_redirects=True
    ) as client:
        with trace_scope(TraceScope(kind="project_conversation", id="project-a")) as trace:
            response = await client.post(
                "https://provider.invalid/start", json={"model": "synthetic"}
            )
            assert response.json()["usage"]["input_tokens"] == 7
    requests = [e for e in all_events(store, trace) if e["data"].get("layer") == "provider_request"]
    assert len(requests) == 3
    assert len({e["data"]["attempt_id"] for e in requests}) == 3


@run_async
async def test_early_stream_close_and_summary_do_not_capture_content(store):
    store.set_policy("local", "summary", None)
    stream = Chunks([b'data: {"text":"private"}\n\n', b"data: [DONE]\n\n"])
    async with ObservedHttpClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream
            )
        )
    ) as client:
        with trace_scope(TraceScope(kind="creation_session", id="session")) as trace:
            async with client.stream(
                "POST", "https://provider.invalid/api", json={"secret": "unrecorded"}
            ) as response:
                async for _ in response.aiter_bytes():
                    break
    events = all_events(store, trace)
    assert stream.closed
    assert all(not e["data"].get("content_hash") for e in events)
    assert b"private" not in store.path.read_bytes()
    assert any(e["data"].get("missing_reason") == "recording_not_enabled" for e in events)
    assert all(
        e["data"]["completeness"] == "not_recorded" for e in events if e["event_type"] == "payload"
    )


@run_async
async def test_concurrent_tasks_and_device_ownership_are_isolated(store):
    async def task(name):
        token = request_identity.set({"gateway_device_id": name})
        try:
            store.set_policy(f"device:{name}", "full", None)
            with trace_scope(
                TraceScope(kind="creation_session", id=name), assistant_message_id=name
            ) as trace:
                await asyncio.sleep(0)
                record_payload("tool_arguments", {"entity_id": name})
            return trace
        finally:
            request_identity.reset(token)

    first, second = await asyncio.gather(task("a"), task("b"))
    store.flush()
    assert store.trace("device:a", second.id) is None
    assert store.events("device:b", first.id) == []
    assert store.list_traces("device:a")[0]["scope_id"] == "a"
    assert len(store.list_traces("device:b")) == 1


@run_async
async def test_broken_recorder_never_changes_api_result(store, monkeypatch):
    def broken(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(store, "submit", broken)
    async with ObservedHttpClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"ok": True}))
    ) as client:
        with trace_scope(TraceScope(kind="operation", id="operation-a")):
            response = await client.post("https://provider.invalid/api", json={"messages": []})
            assert response.json() == {"ok": True}


def test_invalid_payload_is_not_stored_and_export_is_self_contained(store):
    with trace_scope(TraceScope(kind="creation_session", id="a")) as trace:
        trace.emit(
            "payload",
            {"layer": "provider_response", "media_type": "application/json"},
            raw=b'{"key":"secret',
        )
        record_payload("tool_receipt", {"reason": "entity_not_found", "path": "$.entity_id"})
    events = all_events(store, trace)
    assert any(e["data"].get("missing_reason") == "unparseable_body" for e in events)
    assert b"secret" not in store.path.read_bytes()
    queries = TraceQueries(store)
    import zipfile

    path = queries.export("local", trace.id)
    try:
        with zipfile.ZipFile(path) as archive:
            manifest = json.loads(archive.read("manifest.json"))
            assert manifest["capture_status"] == "partial"
            assert "events.jsonl" in archive.namelist()
            assert len([n for n in archive.namelist() if n.startswith("payloads/")]) == 1
    finally:
        path.unlink()
    assert store.clear("local") == 1
    assert store.events("local", trace.id) == []

"""Diagnostic route ownership, preflight errors and safe Unicode pagination."""

import asyncio
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.modules.gateway.application.project_access import configure_project_access
from app.modules.operations.application.trace_capture import (
    configure_trace_sink,
    record_payload,
    request_identity,
    trace_scope,
)
from app.modules.operations.application.trace_queries import configure_trace_queries
from app.modules.operations.domain.context_trace import TraceScope
from app.modules.operations.infrastructure.trace_queries import TraceQueries
from app.modules.operations.infrastructure.trace_store import TraceStore
from app.routers.context_traces import router
from app.services.workspace.executor import execute_workspace_action


@pytest.fixture
def store(tmp_path):
    value = TraceStore(tmp_path / "traces.sqlite3")
    configure_trace_sink(value)
    configure_trace_queries(TraceQueries(value))
    yield value
    configure_trace_sink(None)
    configure_trace_queries(None)
    value.close()


def test_route_checks_device_and_payload_owner_and_current_project_grant(store):
    configure_project_access(lambda project: project == "shared")
    token = request_identity.set({"gateway_device_id": "device-a"})
    try:
        store.set_policy("device:device-a", "full", None)
        with trace_scope(TraceScope(kind="project_conversation", id="shared")) as first:
            record_payload("provider_request", {"messages": ["private"]})
        with trace_scope(TraceScope(kind="creation_session", id="draft")) as second:
            record_payload("tool_receipt", {"value": 1})
    finally:
        request_identity.reset(token)
    store.flush()
    payload_id = next(
        e["event_id"]
        for e in store.events("device:device-a", first.id)
        if e["event_type"] == "payload"
    )
    app = FastAPI()

    @app.middleware("http")
    async def authenticated_fixture(request, call_next):
        # Authentication itself is covered by test_gateway_sync/test_http_security.
        request.state.gateway_device_id = request.headers.get("x-test-identity", "device-a")
        return await call_next(request)

    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        url = f"/api/v1/context-traces/{first.id}"
        assert client.get(url).status_code == 200
        for suffix in ("", "/events", f"/payloads/{payload_id}", "/export"):
            assert (
                client.get(url + suffix, headers={"x-test-identity": "device-b"}).status_code == 404
            )
        assert (
            client.get(f"/api/v1/context-traces/{second.id}/payloads/{payload_id}").status_code
            == 404
        )
        configure_project_access(lambda _: False)
        assert client.get(url).status_code == 404
        # Settings and cleanup apply only to the authenticated device.
        client.delete("/api/v1/context-traces", headers={"x-test-identity": "device-b"})
        assert store.trace("device:device-a", first.id) is not None


def test_actual_tool_contract_rejection_has_no_provider_request(store):
    store.set_policy("local", "full", None)
    with trace_scope(TraceScope(kind="creation_session", id="fixture")) as trace:
        result = asyncio.run(
            execute_workspace_action(
                None,
                "",
                {
                    "tool": "generate_creation_artifact",
                    "arguments": {
                        "session_id": "fixture",
                        "artifact": "characters",
                        "expected_revision": 16,
                        "context_entity_ids": '["wrong-type"]',
                    },
                },
            )
        )
    assert result["status"] == "error"
    assert result["data"]["reason"] == "native_tool_contract_invalid"
    store.flush()
    events = store.events("local", trace.id)
    assert not any(e["data"].get("layer") == "provider_request" for e in events)
    output = next(e for e in events if e["data"].get("layer") == "model_visible_tool_result")
    assert json.loads(store.payload("local", trace.id, output["event_id"])["content"]) == result


def test_payload_page_offsets_do_not_skip_non_bmp_characters(store):
    store.set_policy("local", "full", None)
    value = {"text": "🙂中" * 45000}
    with trace_scope(TraceScope(kind="operation", id="unicode")) as trace:
        record_payload("provider_response", value)
    store.flush()
    event = next(e for e in store.events("local", trace.id) if e["event_type"] == "payload")
    offset, pieces = 0, []
    while True:
        part = store.payload("local", trace.id, event["event_id"], offset)
        pieces.append(part["content"])
        offset = part["next_offset"]
        if offset >= part["total_characters"]:
            break
    assert len(pieces) == 2
    assert json.loads("".join(pieces)) == value

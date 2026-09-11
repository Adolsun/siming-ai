"""Opt-in local OpenTelemetry instrumentation, loaded only by the diagnostic runner.

Observes JSON requests at HTTPX's send boundary, after provider adaptation, and
tees original response bytes. No proxy, model/base URL change or extra LLM call.
"""

from __future__ import annotations

import functools
import gzip
import io
import json
import zlib
from urllib.parse import urlsplit

import httpx
import requests
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode

CAPTURE_LIMIT = 16 * 1024 * 1024
_SECRET_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "secret_key",
    "password",
}


def redact(value):
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if k.lower() in _SECRET_KEYS else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def dump(value):
    return json.dumps(redact(value), ensure_ascii=False, default=str)


def configure(endpoint="http://127.0.0.1:6006/v1/traces", project="siming-api-live"):
    url = urlsplit(endpoint)
    if (
        url.scheme != "http"
        or url.hostname not in {"127.0.0.1", "localhost", "::1"}
        or url.username
        or url.query
    ):
        raise ValueError(
            "Diagnostic collector must be a loopback HTTP endpoint without credentials"
        )
    session = requests.Session()
    session.trust_env = False
    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "siming-api-diagnostic",
                "openinference.project.name": project,
            }
        ),
        span_limits=SpanLimits(max_attributes=512),
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=endpoint, session=session, timeout=3)
        )
    )
    trace.set_tracer_provider(provider)
    return provider


def _response_records(raw):
    """Parse JSON/SSE framing only; retain the provider's original fields."""
    try:
        value = json.loads(raw)
        return [value] if isinstance(value, dict) else []
    except ValueError:
        records = []
        for event in raw.replace("\r\n", "\n").split("\n\n"):
            data = "\n".join(
                line[5:].lstrip(" ")
                for line in event.splitlines()
                if line.startswith("data:")
            )
            if data and data != "[DONE]":
                try:
                    value = json.loads(data)
                    if isinstance(value, dict):
                        records.append(value)
                except ValueError:
                    pass
        return records


class ResponseCapture(httpx.AsyncByteStream):
    def __init__(self, inner, span, encoding=""):
        self.inner, self.span = inner, span
        self.buffer = bytearray()
        self.total = 0
        self.finished = False
        self.encoding = encoding

    def append(self, data):
        self.total += len(data)
        self.buffer.extend(data[: max(0, CAPTURE_LIMIT - len(self.buffer))])

    def finish(self, state):
        if self.finished:
            return
        self.finished = True
        captured = bytes(self.buffer)
        decoding = "decoded"
        try:
            if self.encoding == "gzip":
                with gzip.GzipFile(fileobj=io.BytesIO(captured)) as zipped:
                    captured = zipped.read(CAPTURE_LIMIT + 1)
            elif self.encoding == "deflate":
                captured = zlib.decompressobj().decompress(captured, CAPTURE_LIMIT + 1)
            elif self.encoding not in {"", "identity"}:
                decoding = "unsupported_content_encoding:" + self.encoding
        except (OSError, EOFError, zlib.error):
            decoding = "incomplete_encoded_response"
        raw = captured[:CAPTURE_LIMIT].decode("utf-8", errors="replace")
        self.span.set_attribute("output.mime_type", "application/json")
        records = _response_records(raw)
        self.span.set_attribute(
            "output.value",
            dump(
                {
                    "response_state": state,
                    "provider_response_records": records,
                    "raw_body_if_unparsed": raw if not records else None,
                }
            ),
        )
        self.span.set_attribute("siming.response_bytes", self.total)
        self.span.set_attribute(
            "siming.response_capture_truncated",
            self.total > len(self.buffer) or len(captured) > CAPTURE_LIMIT,
        )
        self.span.set_attribute("siming.response_decoding", decoding)
        self.span.set_attribute("siming.response_state", state)
        if state != "complete":
            self.span.set_status(Status(StatusCode.ERROR, state))
        for record in records:
            nested = record.get("response")
            usage = (
                record.get("usage")
                or (nested.get("usage") if isinstance(nested, dict) else {})
                or {}
            )
            if not isinstance(usage, dict):
                continue
            for source, target in (
                ("prompt_tokens", "prompt"),
                ("input_tokens", "prompt"),
                ("completion_tokens", "completion"),
                ("output_tokens", "completion"),
                ("total_tokens", "total"),
            ):
                if isinstance(usage.get(source), int):
                    self.span.set_attribute("llm.token_count." + target, usage[source])
        self.span.end()

    async def __aiter__(self):
        try:
            async for chunk in self.inner:
                self.append(chunk)
                yield chunk
        except BaseException as error:
            self.finish(type(error).__name__)
            raise
        else:
            self.finish("complete")

    async def aclose(self):
        try:
            await self.inner.aclose()
        finally:
            self.finish("closed_before_complete")


def instrument_httpx(tracer=None):
    tracer = tracer or trace.get_tracer("siming.api.boundary")
    original = httpx.AsyncClient.send
    if getattr(original, "_siming_diagnostic", False):
        raise RuntimeError("HTTPX diagnostic capture is already installed")

    @functools.wraps(original)
    async def send(client, request, *args, **kwargs):
        try:
            body = json.loads(request.content)
        except (ValueError, httpx.RequestNotRead):
            return await original(client, request, *args, **kwargs)
        if (
            request.method != "POST"
            or not isinstance(body, dict)
            or "model" not in body
            or not ("messages" in body or "input" in body)
        ):
            return await original(client, request, *args, **kwargs)
        encoded = dump(body)
        messages = (
            body.get("messages") if isinstance(body.get("messages"), list) else []
        )
        tools = body.get("tools") if isinstance(body.get("tools"), list) else []
        truncated = len(encoded.encode("utf-8")) > CAPTURE_LIMIT
        span = tracer.start_span(
            "API " + str(body["model"]),
            attributes={
                "openinference.span.kind": "LLM",
                "llm.model_name": str(body["model"]),
                "input.mime_type": "application/json",
                "input.value": encoded
                if not truncated
                else encoded[: CAPTURE_LIMIT // 4],
                "siming.capture_source": "httpx_request_body_and_provider_response",
                "siming.request_capture_truncated": truncated,
                "siming.credentials_policy": "HTTP headers and URL query not collected; credential JSON fields redacted",
                "http.request.method": request.method,
                "server.address": request.url.host,
                "url.path": request.url.path,
                "siming.tool_count": len(tools),
                "siming.message_count": len(messages),
                "siming.request_bytes": len(request.content),
                "metadata": dump(
                    {
                        "message_sizes_bytes": [
                            len(dump(m).encode("utf-8")) for m in messages
                        ],
                        "tools_size_bytes": len(dump(tools).encode("utf-8")),
                    }
                ),
            },
        )
        try:
            response = await original(client, request, *args, **kwargs)
        except BaseException as error:
            span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            span.end()
            raise
        span.set_attribute("http.response.status_code", response.status_code)
        if response.status_code >= 400:
            span.set_status(Status(StatusCode.ERROR, f"HTTP {response.status_code}"))
        capture = ResponseCapture(
            response.stream,
            span,
            ""
            if response.is_stream_consumed
            else response.headers.get("content-encoding", ""),
        )
        if response.is_stream_consumed:
            capture.append(response.content)
            capture.finish("complete")
        else:
            response.stream = capture
        return response

    send._siming_diagnostic = True
    httpx.AsyncClient.send = send
    return lambda: setattr(httpx.AsyncClient, "send", original)


def instrument_workspace(tracer=None):
    # Install before importing application services that bind the dispatcher.
    from app.services import workspace
    from app.services.workspace import executor

    tracer = tracer or trace.get_tracer("siming.workspace.tools")
    original = executor.execute_workspace_action

    @functools.wraps(original)
    async def execute(db, project_id, action):
        name = str(action.get("tool", "unknown"))
        with tracer.start_as_current_span(
            name,
            attributes={
                "openinference.span.kind": "TOOL",
                "tool.name": name,
                "input.mime_type": "application/json",
                "input.value": dump(action.get("arguments", {})),
                "siming.project_id": project_id,
            },
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                result = await original(db, project_id, action)
            except BaseException as error:
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                raise
            span.set_attribute("output.mime_type", "application/json")
            span.set_attribute("output.value", dump(result))
            if result.get("status") in {"error", "failed", "denied"}:
                span.set_status(Status(StatusCode.ERROR, str(result.get("status"))))
            return result

    executor.execute_workspace_action = execute
    workspace.execute_workspace_action = execute

    def restore():
        executor.execute_workspace_action = original
        workspace.execute_workspace_action = original

    return restore


class TraceRequests:
    def __init__(self, app):
        self.app = app
        self.tracer = trace.get_tracer("siming.backend.requests")

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        with self.tracer.start_as_current_span(
            f"{scope['method']} {scope['path']}",
            attributes={
                "openinference.span.kind": "CHAIN",
                "siming.capture_source": "diagnostic_backend_request",
            },
            record_exception=False,
            set_status_on_exception=False,
        ):
            await self.app(scope, receive, send)

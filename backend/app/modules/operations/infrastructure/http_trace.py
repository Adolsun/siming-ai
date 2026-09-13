"""Observe physical HTTP exchanges without changing client configuration or streams."""

from __future__ import annotations

import contextlib
import threading
import zlib

import httpx

from ..application.trace_capture import Span, active_trace
from ..domain.context_trace import MEMORY_LIMIT, PAYLOAD_LIMIT
from .trace_payload import safe_endpoint
from .trace_wire_usage import WireUsage

_buffer_lock = threading.Lock()
_buffer_bytes = 0


class ResponseCapture:
    def __init__(self, span: Span, response: httpx.Response, *, decoded: bool = False) -> None:
        self.span, self.trace = span, span.trace
        self.media = response.headers.get("content-type", "").split(";")[0]
        self.body = bytearray()
        self.observed = 0
        self.reason = None
        self.closed = False
        self.usage = WireUsage(self.trace, span.id, self.media)
        encoding = "" if decoded else response.headers.get("content-encoding", "").lower()
        self.decoder = (
            zlib.decompressobj(16 + zlib.MAX_WBITS)
            if encoding == "gzip"
            else (zlib.decompressobj() if encoding == "deflate" else None)
        )
        if encoding not in {"", "identity", "gzip", "deflate"}:
            self.reason = "unsupported_encoding"
        if self.trace and self.trace.policy.mode != "full":
            self.reason = "recording_not_enabled"

    def append(self, chunk: bytes) -> None:
        global _buffer_bytes
        self.observed += len(chunk)
        if self.reason and self.reason != "recording_not_enabled":
            return
        try:
            if self.decoder:
                chunk = self.decoder.decompress(chunk, PAYLOAD_LIMIT - len(self.body) + 1)
            self.usage.feed(chunk)
            if self.reason:
                return
            with _buffer_lock:
                if (
                    len(self.body) + len(chunk) > PAYLOAD_LIMIT
                    or _buffer_bytes + len(chunk) > MEMORY_LIMIT
                ):
                    self.reason = "size_limit"
                    return
                self.body.extend(chunk)
                _buffer_bytes += len(chunk)
        except Exception:
            self.reason = "decoding_failed"

    def finish(self, status: str) -> None:
        global _buffer_bytes
        if self.closed:
            return
        self.closed = True
        try:
            self.usage.finish()
            if self.decoder and status == "completed" and not self.decoder.eof:
                self.reason = self.reason or "incomplete_encoding"
            if self.trace:
                raw = bytes(self.body) if not self.reason else None
                self.trace.emit(
                    "payload",
                    {
                        "span_id": self.span.id,
                        "layer": "provider_response",
                        "media_type": self.media,
                        "capture_source": "http_transport",
                        "completeness": "not_recorded"
                        if self.reason == "recording_not_enabled"
                        else (
                            "complete" if status == "completed" and not self.reason else "partial"
                        ),
                        "observed_bytes": self.observed,
                        "missing_reason": self.reason
                        or ("stream_interrupted" if status != "completed" else None),
                    },
                    raw=raw,
                )
            self.span.finish(status)
        finally:
            with _buffer_lock:
                _buffer_bytes -= len(self.body)
            self.body.clear()


class ObservedStream(httpx.AsyncByteStream):
    def __init__(self, wrapped: httpx.AsyncByteStream, capture: ResponseCapture) -> None:
        self.wrapped, self.capture = wrapped, capture

    async def __aiter__(self):
        status = "partial"
        try:
            async for chunk in self.wrapped:
                with contextlib.suppress(Exception):
                    self.capture.append(chunk)
                yield chunk
            status = "completed"
        except BaseException as exc:
            status = (
                "cancelled"
                if type(exc).__name__ in {"CancelledError", "GeneratorExit"}
                else "error"
            )
            raise
        finally:
            with contextlib.suppress(Exception):
                self.capture.finish(status)

    async def aclose(self) -> None:
        try:
            await self.wrapped.aclose()
        finally:
            with contextlib.suppress(Exception):
                self.capture.finish("partial")


class ObservedRequestStream(httpx.AsyncByteStream):
    def __init__(self, wrapped, span: Span, metadata: dict) -> None:
        self.wrapped, self.span, self.metadata = wrapped, span, metadata
        self.body = bytearray()
        self.too_large = False

    async def __aiter__(self):
        global _buffer_bytes
        complete = False
        try:
            async for chunk in self.wrapped:
                with contextlib.suppress(Exception), _buffer_lock:
                    if not self.too_large:
                        if (
                            len(self.body) + len(chunk) <= PAYLOAD_LIMIT
                            and _buffer_bytes + len(chunk) <= MEMORY_LIMIT
                        ):
                            self.body.extend(chunk)
                            _buffer_bytes += len(chunk)
                        else:
                            self.too_large = True
                yield chunk
            complete = True
        finally:
            with contextlib.suppress(Exception):
                reason = (
                    "size_limit"
                    if self.too_large
                    else (None if complete else "request_interrupted")
                )
                if self.span.trace:
                    self.span.trace.emit(
                        "payload",
                        {
                            **self.metadata,
                            "missing_reason": reason,
                            "completeness": "complete" if reason is None else "partial",
                        },
                        raw=bytes(self.body) if reason is None else None,
                    )
            with _buffer_lock:
                _buffer_bytes -= len(self.body)
                self.body.clear()

    async def aclose(self):
        await self.wrapped.aclose()


class TraceHttpMixin:
    async def _send_single_request(self, request: httpx.Request) -> httpx.Response:
        """HTTPX's dispatch boundary also sees SDK retries, redirects and mounted transports."""
        trace = active_trace()
        if trace is None or trace.policy.mode == "off":
            return await super()._send_single_request(request)
        span = Span("provider_request", request.method)
        with contextlib.suppress(Exception):
            for name in ("authorization", "x-api-key", "api-key"):
                secret = request.headers.get(name, "")
                if secret:
                    trace.secrets.add(secret)
                    trace.secrets.add(secret.removeprefix("Bearer "))
            metadata = {
                "span_id": span.id,
                "attempt_id": span.id,
                "layer": "provider_request",
                "capture_source": "http_transport",
                "media_type": "application/json",
                "endpoint": safe_endpoint(str(request.url)),
                "method": request.method,
            }
            try:
                raw = request.content if trace.policy.mode == "full" else None
                streaming = False
            except httpx.RequestNotRead:
                raw, streaming = None, True
                outgoing = request.stream
                if isinstance(outgoing, ObservedRequestStream):
                    outgoing = outgoing.wrapped
                request.stream = ObservedRequestStream(outgoing, span, metadata)
            reason = "recording_not_enabled" if raw is None else None
            if raw is not None and len(raw) > PAYLOAD_LIMIT:
                raw, reason = None, "size_limit"
            if not streaming:
                trace.emit(
                    "payload",
                    {
                        **metadata,
                        "completeness": "not_recorded"
                        if reason == "recording_not_enabled"
                        else ("partial" if reason else "complete"),
                        "missing_reason": reason,
                    },
                    raw=raw,
                )
        try:
            response = await super()._send_single_request(request)
        except BaseException as exc:
            span.finish(
                "cancelled" if type(exc).__name__ == "CancelledError" else "error",
                error_type=type(exc).__name__,
            )
            raise
        with contextlib.suppress(Exception):
            trace.emit("http_response", {"span_id": span.id, "status_code": response.status_code})
            capture = ResponseCapture(span, response, decoded=response.is_stream_consumed)
            if response.is_stream_consumed:
                capture.append(response.content)
                capture.finish("completed")
            else:
                response.stream = ObservedStream(response.stream, capture)
        return response


class ObservedHttpClient(TraceHttpMixin, httpx.AsyncClient):
    pass

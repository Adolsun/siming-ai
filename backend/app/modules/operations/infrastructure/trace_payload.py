"""Bounded payload processing. Unparseable wire bodies are never persisted."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ..domain.context_trace import PAYLOAD_LIMIT

_CREDENTIAL_KEYS = frozenset(
    {
        "apikey",
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "password",
        "secret",
        "secretkey",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "clientsecret",
        "credential",
        "credentials",
        "token",
    }
)


def safe_endpoint(value: str) -> str:
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        if url.port:
            host += f":{url.port}"
        return urlunsplit((url.scheme, host, url.path, "", ""))
    except ValueError:
        return "[invalid endpoint]"


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]"
            if re.sub(r"[^a-z]", "", str(key).lower()) in _CREDENTIAL_KEYS
            else redact(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    return value


def encode_bounded(value: Any, limit: int = PAYLOAD_LIMIT) -> bytes | None:
    """Bound serialization without retaining mutable business objects in a queue."""
    result = bytearray()
    try:
        for part in _json_parts(value):
            encoded = part.encode("utf-8")
            if len(result) + len(encoded) > limit:
                return None
            result.extend(encoded)
    except (ValueError, TypeError, RecursionError):
        return None
    return bytes(result)


def _json_parts(value, depth=0):
    if depth > 64:
        raise ValueError("diagnostic structure too deep")
    if isinstance(value, str):
        yield '"'
        for offset in range(0, len(value), 4096):
            yield json.dumps(value[offset : offset + 4096], ensure_ascii=False)[1:-1]
        yield '"'
    elif isinstance(value, dict):
        yield "{"
        for index, (key, item) in enumerate(value.items()):
            if index:
                yield ","
            yield from _json_parts(str(key), depth + 1)
            yield ":"
            yield from _json_parts(item, depth + 1)
        yield "}"
    elif isinstance(value, (list, tuple)):
        yield "["
        for index, item in enumerate(value):
            if index:
                yield ","
            yield from _json_parts(item, depth + 1)
        yield "]"
    else:
        yield json.dumps(value, allow_nan=False)


def process_payload(raw: bytes, media: str, secrets: tuple[str, ...]) -> dict:
    try:
        text = raw.decode("utf-8")
        if media == "text/event-stream":
            frames = []
            for block in re.split(r"\r?\n\r?\n", text):
                parts = [
                    line[5:].lstrip() for line in block.splitlines() if line.startswith("data:")
                ]
                if parts:
                    data = "\n".join(parts)
                    frames.append("[DONE]" if data == "[DONE]" else json.loads(data))
            value = frames
        else:
            value = json.loads(text)
        clean = json.dumps(redact(value, secrets), ensure_ascii=False, separators=(",", ":"))
        encoded = clean.encode("utf-8")
        if len(encoded) > PAYLOAD_LIMIT:
            return {"content": None, "missing_reason": "size_limit", "completeness": "partial"}
        return {
            "content": clean,
            "stored_bytes": len(encoded),
            "content_hash": hashlib.sha256(encoded).hexdigest(),
            "redaction": "applied",
            "missing_reason": None,
        }
    except (ValueError, UnicodeError, RecursionError):
        return {"content": None, "missing_reason": "unparseable_body", "completeness": "partial"}

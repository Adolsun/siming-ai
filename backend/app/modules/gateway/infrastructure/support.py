"""Shared value objects and deterministic helpers for Gateway services."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.core.exceptions import AppException
from app.modules.gateway.application.contracts import SYNC_PROTOCOL_VERSION

MAX_ENTITY_PAYLOAD_BYTES = 1024 * 1024


def utcnow() -> datetime:
    return datetime.utcnow()


def token_digest(token: str) -> str:
    """Digest a high-entropy opaque token before persistence."""

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def canonical_payload(payload: dict[str, Any] | None) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def payload_hash(payload: dict[str, Any] | None) -> str:
    return hashlib.sha256(canonical_payload(payload)).hexdigest()


def require_protocol(version: int) -> None:
    if version != SYNC_PROTOCOL_VERSION:
        raise AppException(
            code=426,
            status_code=426,
            message=(
                f"同步协议版本不兼容：服务端为 {SYNC_PROTOCOL_VERSION}，"
                f"客户端为 {version}。请更新司命后重试。"
            ),
        )


@dataclass(frozen=True)
class GatewayAuthContext:
    device_id: str
    role: str
    platform: str


__all__ = [
    "GatewayAuthContext",
    "MAX_ENTITY_PAYLOAD_BYTES",
    "canonical_payload",
    "payload_hash",
    "require_protocol",
    "token_digest",
    "utcnow",
]

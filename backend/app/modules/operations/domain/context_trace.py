"""Versioned, provider-neutral diagnostic records (never business authority)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

TRACE_SCHEMA = "siming.context_trace.v1"
PAYLOAD_LIMIT = 16 * 1024 * 1024
MEMORY_LIMIT = 32 * 1024 * 1024


class TraceScope(BaseModel):
    kind: Literal["project_conversation", "creation_session", "system_conversation", "operation"]
    id: str = Field(min_length=1, max_length=200)


class TracePolicy(BaseModel):
    mode: Literal["off", "summary", "full"] = "summary"
    full_until: float | None = None
    retention_days: int = Field(default=7, ge=1, le=30)
    max_bytes: int = Field(default=256 * 1024 * 1024, ge=8 * 1024 * 1024, le=512 * 1024 * 1024)


class TracePolicyUpdate(BaseModel):
    mode: Literal["off", "summary", "full"]
    duration_minutes: Literal[60] | None = None


class TraceQuery(BaseModel):
    scope: TraceScope | None = None
    correlation_id: str | None = Field(default=None, max_length=200)
    before: int | None = Field(default=None, ge=1)
    limit: int = Field(default=30, ge=1, le=100)

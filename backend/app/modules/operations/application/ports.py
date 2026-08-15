"""Application ports for operation queries and controls."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol


class OperationServicePort(Protocol):
    def list(
        self,
        *,
        active_only: bool,
        limit: int,
        project_id: str | None = None,
        source_kind: str | None = None,
    ) -> list[dict]: ...

    def get(self, operation_id: str, *, include_events: bool = True) -> dict | None: ...

    def complete_author_confirmation(self, operation_id: str) -> bool: ...

    def mark_attention_read(self, operation_ids: list[str]) -> int: ...

    def delete(self, operation_id: str) -> str: ...

    def stream(self, operation_id: str, *, after: int = 0) -> AsyncIterator[tuple[str, dict]]: ...

    async def action(self, operation_id: str, action: str) -> tuple[str, dict | None]: ...

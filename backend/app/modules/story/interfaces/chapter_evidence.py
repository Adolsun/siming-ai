"""Cross-module read port for chapter identity and version evidence."""

from __future__ import annotations

from typing import Any, Protocol


class ChapterEvidenceReader(Protocol):
    def get(
        self,
        session: Any,
        *,
        project_id: str,
        chapter_id: str,
    ) -> dict[str, Any] | None: ...


__all__ = ["ChapterEvidenceReader"]
